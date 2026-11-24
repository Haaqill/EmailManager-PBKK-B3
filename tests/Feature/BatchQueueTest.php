<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Enums\PlanDecision;
use App\Jobs\RunBatchOperationJob;
use App\Jobs\SyncBatchStatusJob;
use App\Models\Batch;
use App\Models\User;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\FakeAgentClient;
use App\Services\Agent\PlanVersionMismatch;
use Illuminate\Console\Scheduling\Schedule;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Queue;
use Mockery;
use Tests\TestCase;

class BatchQueueTest extends TestCase
{
    use RefreshDatabase;

    private FakeAgentClient $agent;

    private BatchSyncService $sync;

    protected function setUp(): void
    {
        parent::setUp();
        $this->agent = new FakeAgentClient();
        $this->sync = new BatchSyncService();
        $this->freezeSecond();
    }

    private function batch(bool $inReview): Batch
    {
        $userId = User::factory()->create()->id;
        $id = $this->agent->startBatch($userId, ['max_results' => 2]);
        if ($inReview) {
            $this->travel(8)->seconds();
        }

        return $this->sync->sync($userId, $this->agent->getBatch($userId, $id));
    }

    private function queueOperation(Batch $batch, string $type): RunBatchOperationJob
    {
        $batch->update(['pending_operation' => [
            'id' => 'operation-1',
            'type' => $type,
            'plan_version' => $batch->plan_version,
            'attempts' => 0,
        ]]);

        return new RunBatchOperationJob($batch->id, 'operation-1');
    }

    private function approveFirstItem(Batch $batch): void
    {
        $batch->items()->where('item_id', 'i_02')->update(['decision' => PlanDecision::Approve]);
    }

    public function test_gangguan_panjang_sebelum_submit_mengakhiri_intent_tanpa_mengirim(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->andThrow(new AgentUnavailable('offline'));
        $agent->shouldNotReceive('execute');

        $job->handle($agent, $this->sync);
        $this->travel(Batch::OPERATION_SECONDS)->seconds();
        $job->handle($agent, $this->sync);

        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame('operation_expired', $batch->fresh()->agent_error['code']);
        $this->assertSame(BatchStatus::AwaitingReview, $batch->fresh()->status);
    }

    public function test_gangguan_panjang_setelah_submit_hanya_direkonsiliasi_tanpa_mengisi_ulang_draf(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $batch->items()->where('item_id', 'i_01')->update(['edited_draft_body' => 'Draf lokal sementara']);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->andThrow(new AgentUnavailable('hasil belum diketahui'));
        $job->handle($agent, $this->sync);
        $this->travel(Batch::OPERATION_SECONDS)->seconds();
        $job->handle($agent, $this->sync);

        $batch->refresh();
        $this->assertNull($batch->pending_operation);
        $this->assertTrue($batch->isReconciling());
        $this->assertSame(0, $batch->items()->whereNotNull('edited_draft_body')->count());

        Queue::fake();
        collect(app(Schedule::class)->events())->firstWhere('description', 'batch:queue-operations')->run($this->app);
        Queue::assertPushed(SyncBatchStatusJob::class, fn (SyncBatchStatusJob $job) => $job->batchId === $batch->id);
        Queue::assertNotPushed(RunBatchOperationJob::class);

        $sync = new SyncBatchStatusJob($batch->id);
        $sync->handle($this->agent, $this->sync);
        $this->assertTrue($batch->fresh()->isReconciling());
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());

        $this->agent->execute($batch->user_id, $batch->agent_batch_id, $batch->plan_version, [
            ['item_id' => 'i_02', 'decision' => 'approve', 'confirmed_trash' => true],
        ]);
        $this->travel(2)->seconds();
        $sync->handle($this->agent, $this->sync);
        $this->assertSame(BatchStatus::Done, $batch->fresh()->status);
        $this->assertFalse($batch->fresh()->isReconciling());
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }

    public function test_respons_worker_lama_setelah_lease_habis_tidak_menimpa_status_baru(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->andReturnUsing(function (...$args) use ($batch): void {
            $this->agent->execute(...$args);
            $this->travel(Batch::LOCK_SECONDS + 1)->seconds();
            $this->assertNotFalse(Batch::operationLock($batch->id)->get(fn () => $this->sync->pull($this->agent, $batch)));
        });

        $job->handle($agent, $this->sync);

        $this->assertSame(BatchStatus::Done, $batch->fresh()->status);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }

    public function test_done_tanpa_report_lengkap_tetap_bisa_disinkronkan_ulang(): void
    {
        $batch = $this->batch(inReview: true);
        $this->agent->execute($batch->user_id, $batch->agent_batch_id, $batch->plan_version, []);
        $batch->update(['status' => BatchStatus::Executing]);
        $this->travel(2)->seconds();
        $done = $this->agent->getBatch($batch->user_id, $batch->agent_batch_id);
        $incomplete = $done;
        $incomplete['report']['results'] = [];
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->times(3)->andReturn([...$done, 'report' => null], $incomplete, $done);
        $job = new SyncBatchStatusJob($batch->id);

        for ($attempt = 0; $attempt < 2; $attempt++) {
            $job->handle($agent, $this->sync);
            $this->assertSame(BatchStatus::Executing, $batch->fresh()->status);
            $this->assertSame('invalid_agent_payload', $batch->fresh()->agent_error['code']);
        }
        $job->handle($agent, $this->sync);
        $this->assertSame(BatchStatus::Done, $batch->fresh()->status);
        $this->assertSame($done['report']['summary'], $batch->fresh()->summary);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }

    public function test_scheduler_menjadwalkan_sync_dan_perintah_tanpa_duplikasi(): void
    {
        config(['queue.default' => 'database', 'cache.default' => 'database']);
        $active = $this->batch(inReview: false);
        $review = $this->batch(inReview: true);
        $pending = $this->batch(inReview: true);
        $this->queueOperation($pending, RunBatchOperationJob::CANCEL);

        $event = collect(app(Schedule::class)->events())->firstWhere('description', 'batch:queue-operations');
        $this->assertSame(2, $event->repeatSeconds);
        $event->run($this->app);
        $event->run($this->app);

        $queue = app('queue')->connection('database');
        $first = $queue->pop();
        $second = $queue->pop();
        $this->assertSame(SyncBatchStatusJob::class, $first->resolveName());
        $this->assertSame(RunBatchOperationJob::class, $second->resolveName());
        $this->assertNull($queue->pop());

        $first->fire();
        $second->fire();
        $this->assertSame(BatchStatus::AwaitingReview, $active->fresh()->status);
        $this->assertSame(BatchStatus::AwaitingReview, $review->fresh()->status);
        $this->assertNull($review->fresh()->agent_error);
        $this->assertSame(BatchStatus::Cancelled, $pending->fresh()->status);
        $this->assertNull($pending->fresh()->pending_operation);
    }

    public function test_lock_batch_mencegah_sync_dan_eksekusi_berjalan_bersamaan(): void
    {
        $batch = $this->batch(inReview: false);
        $syncJob = new SyncBatchStatusJob($batch->id);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldNotReceive('getBatch');
        $agent->shouldNotReceive('execute');
        $lock = Batch::operationLock($batch->id);

        $this->assertTrue($lock->get());
        try {
            $syncJob->handle($agent, $this->sync);
            $operation = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
            $operation->handle($agent, $this->sync);
            $this->assertSame(0, $batch->fresh()->pending_operation['attempts']);
        } finally {
            $lock->release();
        }
    }

    public function test_sync_menyimpan_kode_galat_aman_dan_pulih_pada_tick_berikutnya(): void
    {
        $batch = $this->batch(inReview: false);
        $job = new SyncBatchStatusJob($batch->id);
        $failing = Mockery::mock(AgentClient::class);
        $failing->shouldReceive('getBatch')->once()->with($batch->user_id, $batch->agent_batch_id)
            ->andThrow(new AgentUnavailable('Pesan upstream sensitif', agentCode: 'gmail_unavailable'));

        $job->handle($failing, $this->sync);

        $this->assertSame(BatchStatus::Queued, $batch->fresh()->status);
        $this->assertSame([
            'code' => 'gmail_unavailable',
            'message' => 'Agen sedang tidak bisa dihubungi. Silakan coba lagi.',
        ], $batch->fresh()->agent_error);

        $this->travel(8)->seconds();
        $job->handle($this->agent, $this->sync);

        $this->assertSame(BatchStatus::AwaitingReview, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->agent_error);
    }

    public function test_respons_dengan_id_batch_berbeda_ditolak(): void
    {
        $batch = $this->batch(inReview: false);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->andReturn(['batch_id' => 'b_lain', 'status' => 'queued']);

        (new SyncBatchStatusJob($batch->id))->handle($agent, $this->sync);

        $this->assertDatabaseCount('batches', 1);
        $this->assertSame('invalid_agent_payload', $batch->fresh()->agent_error['code']);
    }

    public function test_batch_yang_hilang_ditutup_dan_data_review_dibersihkan(): void
    {
        $batch = $this->batch(inReview: true);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()
            ->andThrow(new AgentUnavailable('Rincian privat', agentCode: 'batch_not_found'));
        $agent->shouldNotReceive('execute');

        $job->handle($agent, $this->sync);

        $this->assertSame(BatchStatus::Failed, $batch->fresh()->status);
        $this->assertSame('batch_not_found', $batch->fresh()->agent_error['code']);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }

    public function test_eksekusi_yang_diterima_sebelum_timeout_direkonsiliasi_tanpa_submit_ulang(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);

        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->twice()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->andReturnUsing(function (...$arguments): never {
            $this->agent->execute(...$arguments);

            throw new AgentUnavailable('Timeout setelah perintah diterima');
        });

        $job->handle($agent, $this->sync);
        $this->assertSame(1, $batch->fresh()->pending_operation['attempts']);
        $this->assertSame('agent_unavailable', $batch->fresh()->agent_error['code']);
        $this->travel(2)->seconds();
        $job->handle($agent, $this->sync);
        $job->handle($agent, $this->sync);

        $batch->refresh();
        $this->assertSame(BatchStatus::Done, $batch->status);
        $this->assertNull($batch->pending_operation);
        $this->assertNull($batch->agent_error);
        $this->assertSame('ok', $batch->items()->where('item_id', 'i_02')->firstOrFail()->result_status);
        $this->assertSame(PlanDecision::Approve, $batch->items()->where('item_id', 'i_02')->firstOrFail()->decision);
        $this->assertSame(1, $this->agent->executions($batch->user_id, $batch->agent_batch_id));
    }

    public function test_eksekusi_dicoba_ulang_setelah_status_dan_versi_dikonfirmasi(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->ordered()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->ordered()->andThrow(new AgentUnavailable('Timeout'));
        $agent->shouldReceive('getBatch')->once()->ordered()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->ordered()->andReturnUsing($this->agent->execute(...));

        $job->handle($agent, $this->sync);
        $job->handle($agent, $this->sync);

        $this->assertSame(BatchStatus::Executing, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertNull($batch->fresh()->agent_error);
    }

    public function test_percobaan_eksekusi_berhenti_setelah_tiga_submit_dan_rekonsiliasi(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->times(4)->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->times(3)->andThrow(new AgentUnavailable('Timeout'));

        foreach (range(1, 4) as $_) {
            $job->handle($agent, $this->sync);
        }

        $this->assertSame(BatchStatus::AwaitingReview, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame('operation_unconfirmed', $batch->fresh()->agent_error['code']);
    }

    public function test_konflik_saat_submit_memaksa_review_ulang_tanpa_submit_ulang(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->twice()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('execute')->once()->andThrow(new PlanVersionMismatch('invalid_state'));

        $job->handle($agent, $this->sync);
        $job->handle($agent, $this->sync);

        $this->assertSame('plan_changed', $batch->fresh()->agent_error['code']);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame(0, $batch->items()->where('decision', PlanDecision::Approve)->count());
    }

    public function test_pembatalan_ditolak_jika_agen_sudah_mengeksekusi(): void
    {
        $batch = $this->batch(inReview: true);
        $this->approveFirstItem($batch);
        $job = $this->queueOperation($batch, RunBatchOperationJob::CANCEL);
        $this->agent->execute($batch->user_id, $batch->agent_batch_id, $batch->plan_version, [
            ['item_id' => 'i_02', 'decision' => 'approve'],
        ]);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->once()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldNotReceive('cancel');

        $job->handle($agent, $this->sync);

        $this->assertSame(BatchStatus::Executing, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame('cancel_invalid_state', $batch->fresh()->agent_error['code']);
    }

    public function test_pembatalan_yang_diterima_sebelum_timeout_direkonsiliasi(): void
    {
        $batch = $this->batch(inReview: true);
        $job = $this->queueOperation($batch, RunBatchOperationJob::CANCEL);
        $agent = Mockery::mock(AgentClient::class);
        $agent->shouldReceive('getBatch')->twice()->andReturnUsing($this->agent->getBatch(...));
        $agent->shouldReceive('cancel')->once()->andReturnUsing(function (...$arguments): never {
            $this->agent->cancel(...$arguments);

            throw new AgentUnavailable('Timeout');
        });

        $job->handle($agent, $this->sync);
        $job->handle($agent, $this->sync);

        $this->assertSame(BatchStatus::Cancelled, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->pending_operation);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }

    public function test_snapshot_lama_tidak_menimpa_status_terminal(): void
    {
        $batch = $this->batch(inReview: true);
        $snapshot = $this->agent->getBatch($batch->user_id, $batch->agent_batch_id);
        $this->agent->cancel($batch->user_id, $batch->agent_batch_id);
        $this->sync->pull($this->agent, $batch);

        $this->sync->sync($batch->user_id, $snapshot);

        $this->assertSame(BatchStatus::Cancelled, $batch->fresh()->status);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
    }
}
