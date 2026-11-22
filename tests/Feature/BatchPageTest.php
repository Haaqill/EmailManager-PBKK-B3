<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Enums\PlanDecision;
use App\Livewire\BatchIndex;
use App\Livewire\BatchRun;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use App\Models\User;
use App\Services\Agent\AgentClient;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\FakeAgentClient;
use Database\Seeders\DemoSeeder;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Livewire\Livewire;
use RuntimeException;
use Tests\TestCase;

/** FakeAgentClient yang mencatat keputusan yang dikirim Laravel. */
class RecordingAgentClient extends FakeAgentClient
{
    /** @var list<list<array<string, mixed>>> */
    public array $sent = [];

    public function execute(int $userId, string $agentBatchId, int $planVersion, array $decisions): void
    {
        $this->sent[] = $decisions;
        parent::execute($userId, $agentBatchId, $planVersion, $decisions);
    }
}

class BatchPageTest extends TestCase
{
    use RefreshDatabase;

    private RecordingAgentClient $agent;

    protected function setUp(): void
    {
        parent::setUp();
        config(['agent.driver' => 'fake', 'agent.fake.step_seconds' => 2, 'agent.max_threads' => 10]);
        $this->agent = new RecordingAgentClient();
        $this->app->instance(AgentClient::class, $this->agent);
    }

    /** Batch milik $user yang sudah sampai awaiting_review. */
    private function reviewBatch(User $user): Batch
    {
        $id = $this->agent->startBatch($user->id, ['max_results' => 10]);
        $this->travel(10)->seconds();

        return app(BatchSyncService::class)->sync($user->id, $this->agent->getBatch($user->id, $id));
    }

    private function item(Batch $batch, string $itemId): BatchPlanItem
    {
        return BatchPlanItem::query()->where('batch_id', $batch->id)->where('item_id', $itemId)->firstOrFail();
    }

    // ------------------------------------------------------------- akses

    public function test_tamu_diarahkan_ke_login(): void
    {
        $batch = $this->reviewBatch(User::factory()->create());

        $this->get('/batch')->assertRedirect('/login');
        $this->get("/batch/{$batch->id}")->assertRedirect('/login');
    }

    public function test_batch_orang_lain_403_dan_aksinya_ditolak(): void
    {
        $batch = $this->reviewBatch(User::factory()->create());
        $intruder = User::factory()->create();

        $this->actingAs($intruder)->get(route('batch.show', $batch))->assertForbidden();
        Livewire::actingAs($intruder)->test(BatchRun::class, ['batchId' => $batch->id])->assertForbidden();
    }

    // ------------------------------------------------------------- mulai batch

    public function test_mulai_batch_membuat_baris_lewat_sync_dan_mengalihkan(): void
    {
        $user = User::factory()->create();

        $component = Livewire::actingAs($user)->test(BatchIndex::class)
            ->set('threadCount', 5)
            ->call('start');

        $batch = Batch::query()->sole();
        $component->assertRedirect(route('batch.show', $batch));
        $this->assertSame($user->id, $batch->user_id);
        $this->assertSame(BatchStatus::Queued, $batch->status);
        $this->assertSame(['max_results' => 5], $batch->filters);
        $this->assertStringStartsWith('b_demo_', $batch->agent_batch_id);
    }

    public function test_mulai_kedua_saat_ada_batch_aktif_ditolak(): void
    {
        $user = User::factory()->create();
        $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchIndex::class)
            ->assertSee('Lanjutkan batch yang berjalan')
            ->call('start')
            ->assertSet('errorMessage', 'Masih ada batch yang berjalan. Selesaikan atau batalkan dulu.')
            ->assertNoRedirect();

        $this->assertSame(1, Batch::query()->count());
    }

    public function test_jumlah_thread_di_luar_1_sampai_10_ditolak(): void
    {
        $user = User::factory()->create();

        foreach ([0, 11, -3] as $count) {
            Livewire::actingAs($user)->test(BatchIndex::class)
                ->set('threadCount', $count)
                ->call('start')
                ->assertHasErrors('threadCount');
        }
        $this->assertSame(0, Batch::query()->count());
    }

    public function test_daftar_batch_dan_keadaan_kosong(): void
    {
        $user = User::factory()->create();
        $other = User::factory()->create();

        Livewire::actingAs($user)->test(BatchIndex::class)->assertSee('Belum ada batch.');

        $mine = $this->reviewBatch($user);
        $theirs = $this->reviewBatch($other);
        Livewire::actingAs($user)->test(BatchIndex::class)
            ->assertSee("Batch #{$mine->id}")
            ->assertDontSee("Batch #{$theirs->id}")
            ->assertSee('Menunggu review');
    }

    // ------------------------------------------------------------- berjalan

    public function test_polling_memajukan_status_dan_berhenti_saat_review(): void
    {
        $user = User::factory()->create();
        $id = $this->agent->startBatch($user->id, ['max_results' => 10]);
        $batch = app(BatchSyncService::class)->sync($user->id, $this->agent->getBatch($user->id, $id));

        $component = Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->assertSeeHtml('wire:poll.2s="refreshStatus"')
            ->assertSeeHtml('aria-current="step"')
            ->assertSee('Batalkan');

        $this->travel(10)->seconds();
        $component->call('refreshStatus')
            ->assertDontSeeHtml('wire:poll.2s')
            ->assertSee('Tinjau rencana');
        $this->assertSame(BatchStatus::AwaitingReview, $batch->fresh()->status);
        $this->assertSame('Halo, aku bisa ikut kerja kelompok hari Kamis setelah kelas siang. Sampai ketemu di perpustakaan.', $component->get('drafts')['i_04']);
    }

    // ------------------------------------------------------------- review

    public function test_review_default_pending_dan_keputusan_tersimpan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);
        $this->assertSame(8, BatchPlanItem::query()->where('decision', PlanDecision::Pending)->count());

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->assertSee('0 disetujui, 0 ditolak, 8 belum diputuskan (tidak akan dijalankan)')
            ->call('setDecision', 'i_02', 'approve')
            ->call('setDecision', 'i_03', 'reject')
            ->assertSee('1 disetujui, 1 ditolak, 6 belum diputuskan');

        $this->assertSame(PlanDecision::Approve, $this->item($batch, 'i_02')->decision);
        $this->assertSame(PlanDecision::Reject, $this->item($batch, 'i_03')->decision);
    }

    public function test_draf_diedit_tersimpan_dan_bisa_dikembalikan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        $component = Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->set('drafts.i_04', 'Draf versi saya.')
            ->assertSee('Kembalikan ke draf asli');
        $this->assertSame('Draf versi saya.', $this->item($batch, 'i_04')->edited_draft_body);

        $component->set('drafts.i_04', str_repeat('a', BatchRun::DRAFT_MAX + 1))
            ->assertHasErrors('drafts.i_04');
        $this->assertSame('Draf versi saya.', $this->item($batch, 'i_04')->edited_draft_body);

        $component->call('resetDraft', 'i_04');
        $this->assertNull($this->item($batch, 'i_04')->edited_draft_body);
        $this->assertStringStartsWith('Halo, aku bisa ikut', $component->get('drafts')['i_04']);
    }

    public function test_draf_untuk_item_bukan_draft_reply_diabaikan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->set('drafts.i_02', 'sisipan');
        $this->assertNull($this->item($batch, 'i_02')->edited_draft_body);
    }

    public function test_approve_langsung_untuk_trash_tidak_mengubah_keputusan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        $component = Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_07', 'approve');
        $this->assertSame(PlanDecision::Pending, $this->item($batch, 'i_07')->decision);

        $component->call('confirmTrash', 'i_07');
        $this->assertSame(PlanDecision::Approve, $this->item($batch, 'i_07')->decision);
    }

    public function test_confirm_trash_tidak_berlaku_untuk_item_lain(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])->call('confirmTrash', 'i_02');
        $this->assertSame(PlanDecision::Pending, $this->item($batch, 'i_02')->decision);
    }

    public function test_setujui_semua_yang_aman_mengecualikan_trash_peringatan_dan_rendah(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->assertSee('Setujui semua yang aman (4)')
            ->call('approveSafe');

        $approved = BatchPlanItem::query()->where('decision', PlanDecision::Approve)->orderBy('item_id')->pluck('item_id')->all();
        // i_01 & i_05 berperingatan, i_07 trash, i_05 & i_08 keyakinan rendah.
        $this->assertSame(['i_02', 'i_03', 'i_04', 'i_06'], $approved);
    }

    public function test_tolak_semua(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])->call('rejectAll');
        $this->assertSame(8, BatchPlanItem::query()->where('decision', PlanDecision::Reject)->count());
    }

    public function test_tampilan_review_menampilkan_also_archive_peringatan_dan_keyakinan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        $this->actingAs($user)->get(route('batch.show', $batch))
            ->assertOk()
            ->assertSee('draf balasan, lalu arsipkan thread')
            ->assertSee('Draf masih memuat placeholder PERSON yang tidak bisa dipulihkan.')
            ->assertSee('Keyakinan rendah')
            ->assertSee('perkiraan model, belum terkalibrasi')
            ->assertSee('Sekretariat Prodi (contoh) &lt;sekretariat@prodi-lain.example&gt;', false)
            ->assertSee('Draf hanya dibuat di Gmail, tidak dikirim.')
            ->assertSeeHtml('x-trap.noscroll="open"');
    }

    public function test_aksi_review_ditolak_setelah_batch_tidak_lagi_review(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);
        $this->agent->cancel($user->id, $batch->agent_batch_id);
        app(BatchSyncService::class)->sync($user->id, $this->agent->getBatch($user->id, $batch->agent_batch_id));

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_02', 'approve')
            ->assertSet('errorMessage', 'Batch ini tidak lagi menunggu review.');
        $this->assertSame(PlanDecision::Pending, $this->item($batch, 'i_02')->decision);
    }

    // ------------------------------------------------------------- eksekusi

    public function test_eksekusi_hanya_mengirim_keputusan_eksplisit(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_02', 'approve')
            ->call('setDecision', 'i_03', 'reject')
            ->set('drafts.i_04', 'Draf versi saya.')
            ->call('setDecision', 'i_04', 'approve')
            ->call('confirmTrash', 'i_07')
            ->call('execute')
            ->assertSee('Menjalankan aksi yang Anda setujui');

        $this->assertCount(1, $this->agent->sent);
        $sent = collect($this->agent->sent[0])->keyBy('item_id');
        $this->assertEqualsCanonicalizing(['i_02', 'i_03', 'i_04', 'i_07'], $sent->keys()->all());
        $this->assertSame(['item_id' => 'i_02', 'decision' => 'approve'], $sent['i_02']);
        $this->assertSame(['item_id' => 'i_03', 'decision' => 'reject'], $sent['i_03']);
        $this->assertSame('Draf versi saya.', $sent['i_04']['edited_draft_body']);
        $this->assertTrue($sent['i_07']['confirmed_trash']);
        $this->assertSame(BatchStatus::Executing, $batch->fresh()->status);
    }

    public function test_eksekusi_tanpa_item_disetujui_ditolak(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_02', 'reject')
            ->call('execute')
            ->assertSet('errorMessage', 'Belum ada item yang disetujui.');
        $this->assertSame([], $this->agent->sent);
    }

    public function test_klik_ganda_tidak_mengeksekusi_ulang(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_02', 'approve')
            ->call('execute')
            ->call('execute')
            ->assertSet('errorMessage', 'Batch ini tidak lagi menunggu review.');

        $this->assertCount(1, $this->agent->sent);
        $this->assertSame(1, $this->agent->executions($user->id, $batch->agent_batch_id));
    }

    public function test_plan_version_berubah_tidak_mengeksekusi_dan_mereset_keputusan(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        $component = Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('setDecision', 'i_02', 'approve')
            ->set('drafts.i_04', 'Draf versi saya.');
        $this->agent->revisePlan($user->id, $batch->agent_batch_id);

        $component->call('execute')
            ->assertSet('notice', BatchRun::NOTICE_PLAN_CHANGED)
            ->assertSee('Rencana diperbarui; keputusan direset.');

        $this->assertSame([], $this->agent->sent);
        $this->assertSame(2, $batch->fresh()->plan_version);
        $this->assertSame(8, BatchPlanItem::query()->where('decision', PlanDecision::Pending)->count());
        $this->assertNull($this->item($batch, 'i_04')->edited_draft_body);
        $this->assertStringStartsWith('Halo, aku bisa ikut', $component->get('drafts')['i_04']);
    }

    // ------------------------------------------------------------- laporan

    public function test_setelah_done_data_sementara_kosong_dan_laporan_dari_kolom_permanen(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);

        $component = Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->set('drafts.i_04', 'Draf versi saya.')
            ->call('setDecision', 'i_04', 'approve')
            ->call('setDecision', 'i_03', 'reject')
            ->call('execute');
        $this->travel(2)->seconds();
        $component->call('refreshStatus')
            ->assertSee('Laporan batch')
            ->assertSee('Isi email dan draf sudah dihapus dari aplikasi setelah batch selesai.');

        $this->assertSame(BatchStatus::Done, $batch->fresh()->status);
        foreach (BatchPlanItem::TRANSIENT_COLUMNS as $column) {
            $this->assertSame(0, BatchPlanItem::query()->whereNotNull($column)->count(), $column);
        }
        $this->assertSame('ok', $this->item($batch, 'i_04')->result_status);
        $this->assertTrue($this->item($batch, 'i_04')->applied['archived']);

        $html = $this->actingAs($user)->get(route('batch.show', $batch))->assertOk()
            ->assertSee('Ajak kerja kelompok PBKK hari Kamis')
            ->assertSee('Diarsipkan.')
            ->getContent();
        foreach (['Draf versi saya.', 'Halo, aku bisa ikut', 'Petugas meminta data tambahan', 'sekretariat@prodi-lain.example'] as $gone) {
            $this->assertStringNotContainsString($gone, $html);
        }
    }

    // ------------------------------------------------------------- escape

    public function test_teks_email_dan_llm_di_escape(): void
    {
        $user = User::factory()->create();
        $payload = json_decode((string) file_get_contents(resource_path(FakeAgentClient::FIXTURE)), true);
        $payload['batch_id'] = 'b_xss';
        $item = &$payload['plan']['items'][0];      // draft_reply berperingatan
        $item['thread']['subject'] = '<script>alert("subjek")</script>';
        $item['thread']['from_name'] = '<img src=x onerror=alert(1)>';
        $item['reason'] = '<script>alert("alasan")</script>';
        $item['draft']['to'] = '<script>alert("kepada")</script>';
        $item['draft']['subject'] = '<script>alert("subjekdraf")</script>';
        $item['draft']['body'] = '</textarea><script>alert("draf")</script>';
        $item['warnings'][0]['message'] = '<script>alert("peringatan")</script>';
        unset($item);
        $batch = app(BatchSyncService::class)->sync($user->id, $payload);

        $html = $this->actingAs($user)->get(route('batch.show', $batch))->assertOk()->getContent();

        foreach (['subjek', 'alasan', 'kepada', 'subjekdraf', 'peringatan'] as $marker) {
            $this->assertStringNotContainsString("<script>alert(\"{$marker}\")</script>", $html, $marker);
            $this->assertStringContainsString("&lt;script&gt;alert(&quot;{$marker}&quot;)&lt;/script&gt;", $html, $marker);
        }
        $this->assertStringNotContainsString('<img src=x', $html);
        $this->assertStringNotContainsString('</textarea><script>', $html);
    }

    // ------------------------------------------------------------- batal

    public function test_pembatalan_mengubah_status_dan_membersihkan_data_sementara(): void
    {
        $user = User::factory()->create();
        $batch = $this->reviewBatch($user);
        $this->item($batch, 'i_04')->update(['edited_draft_body' => 'Draf versi saya.']);

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('cancel')
            ->assertSee('Batch dibatalkan')
            ->assertSee('Mulai ulang');

        $this->assertSame(BatchStatus::Cancelled, $batch->fresh()->status);
        $this->assertSame(0, BatchPlanItem::query()->whereNotNull('review_data')->count());
        $this->assertSame(0, BatchPlanItem::query()->whereNotNull('edited_draft_body')->count());
    }

    public function test_batal_sebelum_review(): void
    {
        $user = User::factory()->create();
        $id = $this->agent->startBatch($user->id, ['max_results' => 10]);
        $batch = app(BatchSyncService::class)->sync($user->id, $this->agent->getBatch($user->id, $id));

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])->call('cancel');
        $this->assertSame(BatchStatus::Cancelled, $batch->fresh()->status);
    }

    // ------------------------------------------------------------- agen tidak tersedia

    public function test_agen_tidak_tersedia_menampilkan_pesan_ramah(): void
    {
        $user = User::factory()->create();
        $id = $this->agent->startBatch($user->id, ['max_results' => 10]);
        $batch = app(BatchSyncService::class)->sync($user->id, $this->agent->getBatch($user->id, $id));
        cache()->flush();   // agen "lupa" batch ini

        Livewire::actingAs($user)->test(BatchRun::class, ['batchId' => $batch->id])
            ->call('refreshStatus')
            ->assertSet('errorMessage', BatchRun::ERROR_UNAVAILABLE)
            ->assertSee('Coba lagi')
            ->assertDontSee('tidak dikenal agen tiruan');
    }

    // ------------------------------------------------------------- mode demo & navigasi

    public function test_spanduk_mode_demo_hanya_untuk_driver_fake(): void
    {
        $user = User::factory()->create();

        $this->actingAs($user)->get(route('batch'))->assertOk()
            ->assertSee('Mode demo:')
            ->assertSee('data contoh, tidak terhubung ke Gmail.');

        config(['agent.driver' => 'http']);
        $this->actingAs($user)->get(route('batch'))->assertOk()->assertDontSee('Mode demo:');
    }

    public function test_nav_batch_tautan_dan_pengaturan_tetap_segera(): void
    {
        $html = $this->actingAs(User::factory()->create())->get(route('batch'))->assertOk()->getContent();

        $this->assertMatchesRegularExpression('/<a\b[^>]*aria-current="page"[^>]*>\s*Batch\s*<\/a>/', $html);
        $this->assertSame(2, substr_count($html, 'aria-disabled="true" data-nav-soon'));
        $this->assertDoesNotMatchRegularExpression('/<a\b[^>]*>\s*Pengaturan\s*<\/a>/', $html);
    }

    // ------------------------------------------------------------- seeder

    public function test_demo_seeder_menolak_environment_non_lokal(): void
    {
        $this->assertFalse(app()->environment('local'));

        $this->expectException(RuntimeException::class);
        $this->seed(DemoSeeder::class);
    }

    public function test_demo_seeder_membuat_akun_di_local(): void
    {
        $this->app['env'] = 'local';
        $this->seed(DemoSeeder::class);
        $this->seed(DemoSeeder::class);   // idempoten

        $user = User::query()->where('email', DemoSeeder::EMAIL)->sole();
        $this->assertNotNull($user->email_verified_at);
        $this->assertSame(0, $user->batches()->count());
    }
}
