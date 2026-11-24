<?php

namespace App\Jobs;

use App\Enums\BatchStatus;
use App\Models\Batch;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\InvalidAgentPayload;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;

class SyncBatchStatusJob implements ShouldQueue, ShouldBeUnique
{
    use Queueable;

    public int $uniqueFor = Batch::LOCK_SECONDS;

    public int $timeout = Batch::WORKER_TIMEOUT;

    public function __construct(public readonly int $batchId)
    {
    }

    public function uniqueId(): string
    {
        return (string) $this->batchId;
    }

    public function handle(AgentClient $agent, BatchSyncService $sync): void
    {
        $lock = Batch::operationLock($this->batchId);
        $lock->get(function () use ($agent, $sync, $lock): void {
            $canWrite = Batch::operationWriteGuard($lock);
            $batch = Batch::query()->find($this->batchId);
            if ($batch === null || $batch->pending_operation !== null
                || (! $batch->isReconciling() && ! in_array($batch->status, BatchStatus::POLLABLE, true))) {
                return;
            }

            try {
                $fresh = $sync->pull($agent, $batch, $canWrite);
                if ($fresh === null || ! $canWrite() || ($fresh->isReconciling() && $fresh->isActive())) {
                    return;
                }
                if ($fresh->status === BatchStatus::Failed) {
                    $fresh->update(['agent_error' => Batch::agentError('batch_failed')]);
                } elseif (! in_array($fresh->agent_error['code'] ?? null, ['plan_changed', 'cancel_invalid_state', 'operation_unconfirmed', 'operation_expired'], true)) {
                    $fresh->update(['agent_error' => null]);
                }
            } catch (AgentUnavailable|InvalidAgentPayload $exception) {
                if ($canWrite()) {
                    $sync->persistAgentError($batch, $exception);
                }
            }
        });
    }
}
