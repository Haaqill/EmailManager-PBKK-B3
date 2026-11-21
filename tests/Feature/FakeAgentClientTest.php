<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Models\BatchPlanItem;
use App\Models\User;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\FakeAgentClient;
use App\Services\Agent\PlanVersionMismatch;
use Illuminate\Foundation\Testing\RefreshDatabase;
use LogicException;
use Tests\TestCase;

class FakeAgentClientTest extends TestCase
{
    use RefreshDatabase;

    private FakeAgentClient $agent;

    protected function setUp(): void
    {
        parent::setUp();
        config(['agent.driver' => 'fake', 'agent.fake.step_seconds' => 2, 'agent.max_threads' => 10]);
        $this->agent = new FakeAgentClient();
    }

    /**
     * @return array<string, mixed>
     */
    private function fixture(): array
    {
        return json_decode((string) file_get_contents(resource_path(FakeAgentClient::FIXTURE)), true);
    }

    private function reviewBatch(int $userId, int $threads = 10): string
    {
        $id = $this->agent->startBatch($userId, ['max_results' => $threads]);
        $this->travel(10)->seconds();

        return $id;
    }

    public function test_status_maju_sesuai_waktu_sampai_awaiting_review(): void
    {
        $id = $this->agent->startBatch(1, ['max_results' => 10]);
        $seen = [];
        foreach (range(0, 5) as $_) {
            $payload = $this->agent->getBatch(1, $id);
            $seen[] = $payload['status'];
            $this->assertSame($payload['status'] === 'awaiting_review', $payload['plan'] !== null);
            $this->travel(2)->seconds();
        }

        $this->assertSame(['queued', 'scanning', 'classifying', 'drafting', 'awaiting_review', 'awaiting_review'], $seen);
    }

    public function test_jumlah_item_dibatasi_max_threads_dan_filter(): void
    {
        $this->assertCount(8, $this->agent->getBatch(1, $this->reviewBatch(1))['plan']['items']);
        $this->assertCount(3, $this->agent->getBatch(1, $this->reviewBatch(1, 3))['plan']['items']);

        config(['agent.max_threads' => 2]);
        $this->assertCount(2, $this->agent->getBatch(1, $this->reviewBatch(1))['plan']['items']);
    }

    public function test_payload_tiap_tahap_lolos_batch_sync_service(): void
    {
        $user = User::factory()->create();
        $sync = new BatchSyncService();
        $id = $this->agent->startBatch($user->id, ['max_results' => 10]);

        foreach (range(0, 4) as $_) {
            $sync->sync($user->id, $this->agent->getBatch($user->id, $id));
            $this->travel(2)->seconds();
        }
        $batch = $sync->sync($user->id, $this->agent->getBatch($user->id, $id));
        $this->assertSame(BatchStatus::AwaitingReview, $batch->status);
        $this->assertSame(8, $batch->items()->count());

        $this->agent->execute($user->id, $id, 1, [['item_id' => 'i_01', 'decision' => 'approve']]);
        $this->assertSame(BatchStatus::Executing, $sync->sync($user->id, $this->agent->getBatch($user->id, $id))->status);
        $this->travel(2)->seconds();
        $done = $sync->sync($user->id, $this->agent->getBatch($user->id, $id));
        $this->assertSame(BatchStatus::Done, $done->status);
        $this->assertSame(0, BatchPlanItem::query()->whereNotNull('review_data')->count());
    }

    public function test_report_dihitung_dari_keputusan(): void
    {
        $id = $this->reviewBatch(1);
        $this->agent->execute(1, $id, 1, [
            ['item_id' => 'i_04', 'decision' => 'approve'],                        // draf + also_archive
            ['item_id' => 'i_02', 'decision' => 'reject'],
            ['item_id' => 'i_07', 'decision' => 'approve', 'confirmed_trash' => true],
            ['item_id' => 'i_03', 'decision' => 'approve'],
        ]);
        $this->travel(2)->seconds();
        $report = $this->agent->getBatch(1, $id)['report'];
        $results = collect($report['results'])->keyBy('item_id');

        $this->assertSame('ok', $results['i_04']['status']);
        $this->assertTrue($results['i_04']['applied']['archived']);
        $this->assertNotNull($results['i_04']['applied']['draft_id']);
        $this->assertSame('rejected', $results['i_02']['status']);
        $this->assertSame('ok', $results['i_07']['status']);
        $this->assertSame([], $results['i_07']['applied']['labels']);
        $this->assertTrue($results['i_03']['applied']['archived']);
        $this->assertSame('skipped', $results['i_01']['status']);   // tidak diputuskan
        $this->assertSame(['approved' => 3, 'rejected' => 1, 'skipped' => 4, 'actions_ok' => 3, 'actions_failed' => 0], $report['summary']);
    }

    public function test_trash_tanpa_confirmed_trash_tidak_dijalankan(): void
    {
        $id = $this->reviewBatch(1);
        $this->agent->execute(1, $id, 1, [['item_id' => 'i_07', 'decision' => 'approve']]);
        $this->travel(2)->seconds();

        $result = collect($this->agent->getBatch(1, $id)['report']['results'])->firstWhere('item_id', 'i_07');
        $this->assertSame('skipped', $result['status']);
    }

    public function test_execute_ganda_tidak_mengeksekusi_dua_kali(): void
    {
        $id = $this->reviewBatch(1);
        $this->agent->execute(1, $id, 1, [['item_id' => 'i_01', 'decision' => 'approve']]);
        $this->agent->execute(1, $id, 1, [['item_id' => 'i_01', 'decision' => 'reject']]);
        $this->travel(2)->seconds();
        $this->agent->execute(1, $id, 1, [['item_id' => 'i_01', 'decision' => 'reject']]);

        $this->assertSame(1, $this->agent->executions(1, $id));
        $result = collect($this->agent->getBatch(1, $id)['report']['results'])->firstWhere('item_id', 'i_01');
        $this->assertSame('ok', $result['status']);
    }

    public function test_versi_plan_salah_melempar_plan_version_mismatch(): void
    {
        $id = $this->reviewBatch(1);
        $this->assertSame(2, $this->agent->revisePlan(1, $id));

        $this->expectException(PlanVersionMismatch::class);
        $this->agent->execute(1, $id, 1, []);
    }

    public function test_execute_sebelum_review_dan_batch_orang_lain_ditolak(): void
    {
        $id = $this->agent->startBatch(1, ['max_results' => 10]);
        try {
            $this->agent->execute(1, $id, 1, []);
            $this->fail('execute sebelum review harus ditolak');
        } catch (AgentUnavailable) {
        }

        $this->expectException(AgentUnavailable::class);
        $this->agent->getBatch(2, $id);
    }

    public function test_cancel_mengubah_status(): void
    {
        $id = $this->reviewBatch(1);
        $this->agent->cancel(1, $id);
        $payload = $this->agent->getBatch(1, $id);

        $this->assertSame('cancelled', $payload['status']);
        $this->assertNull($payload['report']);
    }

    public function test_driver_http_melempar_pengecualian_berpesan_jelas(): void
    {
        $this->assertInstanceOf(FakeAgentClient::class, app(AgentClient::class));

        config(['agent.driver' => 'http']);
        $this->expectException(LogicException::class);
        $this->expectExceptionMessage('Driver agen "http" belum diimplementasikan');
        app(AgentClient::class);
    }

    public function test_fixture_demo_memenuhi_skenario(): void
    {
        $items = collect($this->fixture()['plan']['items']);

        $this->assertCount(8, $items);
        $this->assertEqualsCanonicalizing(['akademik', 'tugas', 'pengumuman', 'pribadi', 'promosi', 'spam'], $items->pluck('category')->unique()->values()->all());
        $this->assertEqualsCanonicalizing(['label_only', 'archive', 'draft_reply', 'trash'], $items->pluck('action')->unique()->values()->all());
        $this->assertTrue($items->contains(fn ($i) => $i['action'] === 'trash' && $i['requires_confirmation']));
        $this->assertTrue($items->contains(fn ($i) => $i['action'] === 'draft_reply' && $i['also_archive']));
        $codes = $items->flatMap(fn ($i) => array_column($i['warnings'], 'code'));
        $this->assertTrue($items->contains(fn ($i) => $i['action'] === 'draft_reply'
            && in_array('UNRESOLVED_PLACEHOLDER', array_column($i['warnings'], 'code'), true)));
        $this->assertTrue($codes->contains(fn ($c) => $c !== 'UNRESOLVED_PLACEHOLDER'));
        $this->assertTrue($items->contains(fn ($i) => $i['confidence'] === null));
        $this->assertTrue($items->contains(fn ($i) => $i['confidence'] === 'rendah'));
    }
}
