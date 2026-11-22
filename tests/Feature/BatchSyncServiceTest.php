<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanCategory;
use App\Enums\PlanDecision;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use App\Models\User;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\InvalidAgentPayload;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class BatchSyncServiceTest extends TestCase
{
    use RefreshDatabase;

    private BatchSyncService $sync;

    private User $user;

    protected function setUp(): void
    {
        parent::setUp();
        $this->sync = new BatchSyncService();
        $this->user = User::factory()->create();
    }

    /** @return array<string, mixed> */
    private function fixture(string $name): array
    {
        return json_decode(
            file_get_contents(base_path("tests/Fixtures/agent/{$name}.json")),
            true,
            flags: JSON_THROW_ON_ERROR,
        );
    }

    private function item(Batch $batch, string $itemId): BatchPlanItem
    {
        return BatchPlanItem::query()->where('batch_id', $batch->id)->where('item_id', $itemId)->firstOrFail();
    }

    public function test_sync_awaiting_review_fills_permanent_columns_and_review_data(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));

        $this->assertSame(BatchStatus::AwaitingReview, $batch->status);
        $this->assertSame('b_fiktif_0001', $batch->agent_batch_id);
        $this->assertSame(1, $batch->plan_version);
        $this->assertSame(['unread_only' => true, 'newer_than_days' => 7, 'max_results' => 10], $batch->filters);
        $this->assertNull($batch->finished_at);

        $draft = $this->item($batch, 'i_01');
        $this->assertSame('18c0fiktif01', $draft->thread_id);
        $this->assertSame('Konfirmasi jadwal bimbingan', $draft->subject);
        $this->assertSame('Dosen Fiktif', $draft->from_name);
        $this->assertSame(PlanCategory::Akademik, $draft->category);
        $this->assertSame(PlanAction::DraftReply, $draft->action);
        $this->assertSame(PlanDecision::Pending, $draft->decision);
        $this->assertNull($draft->chat_session_id);
        $this->assertSame('Sekretariat Fiktif <sekretariat@domain-lain.example>', $draft->review_data['draft']['to']);
        $this->assertSame('tinggi', $draft->review_data['confidence']);
        $this->assertSame('REPLY_TO_DOMAIN_MISMATCH', $draft->review_data['warnings'][0]['code']);
        $this->assertSame([['filename' => 'jadwal.pdf', 'type' => 'application/pdf', 'size' => 2048]], $draft->review_data['attachments']);

        $trash = $this->item($batch, 'i_02');
        $this->assertSame(PlanAction::Trash, $trash->action);
        $this->assertTrue($trash->review_data['requires_confirmation']);
        $this->assertTrue($draft->review_data['also_archive']);
        $this->assertFalse($trash->review_data['also_archive']);
        $this->assertNull($trash->review_data['draft']);
        $this->assertSame(PlanDecision::Pending, $trash->decision);
    }

    public function test_sync_done_clears_transient_data_and_keeps_permanent_columns(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));
        $this->item($batch, 'i_01')->update(['decision' => PlanDecision::Approve, 'edited_draft_body' => 'Isi baru']);

        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_done'));

        $this->assertSame(BatchStatus::Done, $batch->status);
        $this->assertNotNull($batch->finished_at);
        $this->assertSame(['approved' => 1, 'rejected' => 1, 'actions_ok' => 2, 'actions_failed' => 0], $batch->summary);

        foreach (BatchPlanItem::query()->where('batch_id', $batch->id)->get() as $item) {
            $this->assertNull($item->review_data);
            $this->assertNull($item->edited_draft_body);
        }

        $draft = $this->item($batch, 'i_01');
        $this->assertSame('Konfirmasi jadwal bimbingan', $draft->subject);
        $this->assertSame('Dosen Fiktif', $draft->from_name);
        $this->assertSame(PlanDecision::Approve, $draft->decision);
        $this->assertSame('ok', $draft->result_status);
        $this->assertSame(
            ['labels' => ['Kategori/Akademik', 'Prioritas/Mendesak'], 'archived' => true, 'draft_id' => 'r-fiktif-001'],
            $draft->applied,
        );

        $trash = $this->item($batch, 'i_02');
        $this->assertSame('skipped', $trash->result_status);
        $this->assertNull($trash->applied);
    }

    public function test_invalid_enum_throws_and_stores_nothing(): void
    {
        $payload = $this->fixture('batch_awaiting_review');
        $payload['plan']['items'][1]['category'] = 'Spam';   // huruf kapital: bukan nilai kabel

        try {
            $this->sync->sync($this->user->id, $payload);
            $this->fail('InvalidAgentPayload tidak dilempar');
        } catch (InvalidAgentPayload $e) {
            $this->assertStringContainsString('plan.items[1].category', $e->getMessage());
        }

        $this->assertDatabaseCount('batches', 0);
        $this->assertDatabaseCount('batch_plan_items', 0);
    }

    public function test_confidence_accepts_three_levels_and_null(): void
    {
        $payload = $this->fixture('batch_awaiting_review');
        $template = $payload['plan']['items'][1];   // trash, tanpa draf
        $payload['plan']['items'] = [];
        foreach (['tinggi', 'sedang', 'rendah', null] as $i => $level) {
            $payload['plan']['items'][] = ['item_id' => sprintf('i_%02d', $i + 1), 'confidence' => $level] + $template;
        }

        $batch = $this->sync->sync($this->user->id, $payload);

        $this->assertSame(
            ['i_01' => 'tinggi', 'i_02' => 'sedang', 'i_03' => 'rendah', 'i_04' => null],
            BatchPlanItem::query()->where('batch_id', $batch->id)->orderBy('item_id')->get()
                ->mapWithKeys(fn (BatchPlanItem $item) => [$item->item_id => $item->review_data['confidence']])
                ->all(),
        );
        // Bukan gerbang keamanan: level apa pun tetap pending dan trash tetap wajib konfirmasi.
        foreach (BatchPlanItem::query()->where('batch_id', $batch->id)->get() as $item) {
            $this->assertSame(PlanDecision::Pending, $item->decision);
            $this->assertTrue($item->review_data['requires_confirmation']);
        }
    }

    public function test_invalid_confidence_throws_and_stores_nothing(): void
    {
        foreach ([0.82, 'Tinggi', 'yakin', '', true, ['tinggi']] as $value) {
            $payload = $this->fixture('batch_awaiting_review');
            $payload['plan']['items'][1]['confidence'] = $value;

            try {
                $this->sync->sync($this->user->id, $payload);
                $this->fail('confidence tidak valid diterima: ' . json_encode($value));
            } catch (InvalidAgentPayload $e) {
                $this->assertStringContainsString('plan.items[1].confidence', $e->getMessage());
            }
        }

        $this->assertDatabaseCount('batches', 0);
        $this->assertDatabaseCount('batch_plan_items', 0);
    }

    public function test_confidence_is_cleared_with_review_data_after_done(): void
    {
        $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));
        $this->assertSame('tinggi', BatchPlanItem::query()->where('item_id', 'i_01')->first()->review_data['confidence']);

        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_done'));

        $this->assertSame(0, BatchPlanItem::query()->where('batch_id', $batch->id)->whereNotNull('review_data')->count());
    }

    public function test_also_archive_defaults_to_false_when_absent(): void
    {
        $payload = $this->fixture('batch_awaiting_review');
        unset($payload['plan']['items'][0]['also_archive']);

        $batch = $this->sync->sync($this->user->id, $payload);

        $this->assertFalse($this->item($batch, 'i_01')->review_data['also_archive']);
    }

    public function test_invalid_also_archive_throws_and_stores_nothing(): void
    {
        foreach ([[1, true], [0, 'ya']] as [$index, $value]) {   // trash + true; bukan boolean
            $payload = $this->fixture('batch_awaiting_review');
            $payload['plan']['items'][$index]['also_archive'] = $value;

            try {
                $this->sync->sync($this->user->id, $payload);
                $this->fail('also_archive tidak valid diterima');
            } catch (InvalidAgentPayload $e) {
                $this->assertStringContainsString("plan.items[{$index}].also_archive", $e->getMessage());
            }
        }

        $this->assertDatabaseCount('batches', 0);
        $this->assertDatabaseCount('batch_plan_items', 0);
    }

    public function test_invalid_status_throws_and_stores_nothing(): void
    {
        foreach (['expired', 'selesai'] as $status) {
            $payload = $this->fixture('batch_awaiting_review');
            $payload['status'] = $status;

            try {
                $this->sync->sync($this->user->id, $payload);
                $this->fail("status {$status} diterima");
            } catch (InvalidAgentPayload) {
            }
        }

        $this->assertDatabaseCount('batches', 0);
        $this->assertDatabaseCount('batch_plan_items', 0);
    }

    public function test_decision_and_edited_draft_body_survive_resync(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));
        $this->item($batch, 'i_01')->update(['decision' => PlanDecision::Approve, 'edited_draft_body' => 'Draft suntingan']);
        $this->item($batch, 'i_02')->update(['decision' => PlanDecision::Reject]);

        $payload = $this->fixture('batch_awaiting_review');
        $payload['plan']['items'][0]['reason'] = 'Alasan diperbarui agen.';
        $payload['plan']['items'][0]['decision'] = 'reject';             // tidak boleh dipakai
        $payload['plan']['items'][0]['edited_draft_body'] = 'dari agen'; // tidak boleh dipakai
        $batch = $this->sync->sync($this->user->id, $payload);

        $draft = $this->item($batch, 'i_01');
        $this->assertSame(PlanDecision::Approve, $draft->decision);
        $this->assertSame('Draft suntingan', $draft->edited_draft_body);
        $this->assertSame('Alasan diperbarui agen.', $draft->review_data['reason']);
        $this->assertSame(PlanDecision::Reject, $this->item($batch, 'i_02')->decision);
    }

    public function test_plan_version_change_resets_decisions(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));
        $this->item($batch, 'i_01')->update(['decision' => PlanDecision::Approve, 'edited_draft_body' => 'Draft suntingan']);
        $this->item($batch, 'i_02')->update(['decision' => PlanDecision::Reject]);

        $payload = $this->fixture('batch_awaiting_review');
        $payload['plan']['plan_version'] = 2;
        $batch = $this->sync->sync($this->user->id, $payload);

        $this->assertSame(2, $batch->plan_version);
        foreach (['i_01', 'i_02'] as $itemId) {
            $item = $this->item($batch, $itemId);
            $this->assertSame(PlanDecision::Pending, $item->decision);
            $this->assertNull($item->edited_draft_body);
            $this->assertNotNull($item->review_data);
        }
    }

    public function test_plan_version_change_drops_items_missing_from_new_plan(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));

        $payload = $this->fixture('batch_awaiting_review');
        $payload['plan']['plan_version'] = 2;
        array_pop($payload['plan']['items']);
        $batch = $this->sync->sync($this->user->id, $payload);

        $this->assertSame(['i_01'], BatchPlanItem::query()->where('batch_id', $batch->id)->pluck('item_id')->all());
    }

    public function test_subject_is_truncated_to_255_characters(): void
    {
        $payload = $this->fixture('batch_awaiting_review');
        $payload['plan']['items'][0]['thread']['subject'] = str_repeat('é', 300);

        $batch = $this->sync->sync($this->user->id, $payload);

        $this->assertSame(255, mb_strlen($this->item($batch, 'i_01')->subject));
    }

    public function test_batch_of_another_user_is_rejected(): void
    {
        $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));

        $this->expectException(InvalidAgentPayload::class);
        $this->sync->sync(User::factory()->create()->id, $this->fixture('batch_awaiting_review'));
    }

    public function test_expired_batch_is_not_refilled_by_review_sync(): void
    {
        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));
        $batch->update(['status' => BatchStatus::Expired]);
        BatchPlanItem::query()->where('batch_id', $batch->id)->update(['review_data' => null]);

        $batch = $this->sync->sync($this->user->id, $this->fixture('batch_awaiting_review'));

        $this->assertSame(BatchStatus::Expired, $batch->status);
        $this->assertNull($this->item($batch, 'i_01')->review_data);
    }
}
