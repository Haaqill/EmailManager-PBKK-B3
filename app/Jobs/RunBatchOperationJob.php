<?php

namespace App\Jobs;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanDecision;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\InvalidAgentPayload;
use App\Services\Agent\PlanVersionMismatch;
use Closure;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Illuminate\Support\Facades\DB;

class RunBatchOperationJob implements ShouldQueue, ShouldBeUnique
{
    use Queueable;

    public const EXECUTE = 'execute';

    public const CANCEL = 'cancel';

    private const MAX_SUBMISSIONS = 3;

    public int $uniqueFor = Batch::LOCK_SECONDS;

    public int $timeout = Batch::WORKER_TIMEOUT;

    public function __construct(public readonly int $batchId, public readonly string $operationId)
    {
    }

    public function uniqueId(): string
    {
        return $this->batchId . ':' . $this->operationId;
    }

    public function handle(AgentClient $agent, BatchSyncService $sync): void
    {
        $lock = Batch::operationLock($this->batchId);
        $lock->get(function () use ($agent, $sync, $lock): void {
            $canWrite = Batch::operationWriteGuard($lock);
            $batch = Batch::query()->find($this->batchId);
            $operation = $batch?->pending_operation;
            if (($operation['id'] ?? null) !== $this->operationId) {
                return;
            }
            if (! isset($operation['expires_at'])) {
                $operation['expires_at'] = $batch->updated_at->timestamp + Batch::OPERATION_SECONDS;
                $batch->update(['pending_operation' => $operation]);
            }
            if ($this->expireIfDue($batch, $operation)) {
                return;
            }

            try {
                if ($batch->isActive()) {
                    $fresh = $sync->pull($agent, $batch, $canWrite);
                    if ($fresh === null || ! $canWrite()) {
                        return;
                    }
                    $batch = $fresh;
                }

                if ($this->expireIfDue($batch, $operation)) {
                    return;
                }
                if ($operation['type'] === self::EXECUTE) {
                    $this->execute($agent, $batch, $operation, $canWrite);
                } else {
                    $this->cancel($agent, $sync, $batch, $operation, $canWrite);
                }
            } catch (AgentUnavailable|InvalidAgentPayload $exception) {
                if ($canWrite() && ! $this->expireIfDue($batch, $batch->pending_operation ?? $operation)) {
                    $sync->persistAgentError($batch, $exception);
                }
            }
        });
    }

    private function execute(AgentClient $agent, Batch $batch, array $operation, Closure $canWrite): void
    {
        if ($operation['attempts'] > 0 && ! isset($operation['rejection'])
            && in_array($batch->status, [BatchStatus::Executing, BatchStatus::Done, BatchStatus::Failed], true)) {
            $this->finish($batch, $batch->status === BatchStatus::Failed ? 'batch_failed' : null);

            return;
        }

        $version = $operation['plan_version'];
        if (isset($operation['rejection']) || $batch->status !== BatchStatus::AwaitingReview || $batch->plan_version !== $version) {
            $batch->items()->update(['decision' => PlanDecision::Pending, 'edited_draft_body' => null]);
            $this->finish($batch, 'plan_changed');

            return;
        }

        $decisions = $batch->items()->get()
            ->reject(fn (BatchPlanItem $item) => $item->decision === PlanDecision::Pending)
            ->map($this->decisionPayload(...))
            ->values()
            ->all();
        if (! $canWrite() || $this->expireIfDue($batch, $operation) || ! $this->recordSubmission($batch, $operation)) {
            return;
        }

        try {
            $agent->execute($batch->user_id, $batch->agent_batch_id, $version, $decisions);
        } catch (PlanVersionMismatch) {
            if ($canWrite()) {
                $batch->update(['pending_operation' => [...$batch->pending_operation, 'rejection' => 'plan_changed']]);
            }

            return;
        }

        if ($canWrite() && ! $this->expireIfDue($batch, $batch->pending_operation)) {
            $this->finish($batch, status: BatchStatus::Executing);
        }
    }

    private function cancel(AgentClient $agent, BatchSyncService $sync, Batch $batch, array $operation, Closure $canWrite): void
    {
        if ($batch->status === BatchStatus::Cancelled) {
            $this->finish($batch);

            return;
        }
        if (isset($operation['rejection']) || ! $batch->isActive() || $batch->status === BatchStatus::Executing) {
            $this->finish($batch, 'cancel_invalid_state');

            return;
        }
        if (! $canWrite() || $this->expireIfDue($batch, $operation) || ! $this->recordSubmission($batch, $operation)) {
            return;
        }

        try {
            $agent->cancel($batch->user_id, $batch->agent_batch_id);
        } catch (AgentUnavailable $exception) {
            if ($exception->safeCode() !== 'invalid_state') {
                throw $exception;
            }
            if ($canWrite()) {
                $batch->update(['pending_operation' => [...$batch->pending_operation, 'rejection' => 'cancel_invalid_state']]);
            }

            return;
        }

        if (! $canWrite() || $this->expireIfDue($batch, $batch->pending_operation)) {
            return;
        }
        $cancelled = $sync->sync($batch->user_id, [
            'batch_id' => $batch->agent_batch_id,
            'status' => BatchStatus::Cancelled->value,
        ]);
        $this->finish($cancelled);
    }

    private function expireIfDue(Batch $batch, array $operation): bool
    {
        if (now()->timestamp < $operation['expires_at']) {
            return false;
        }

        if ($batch->isActive() && $operation['attempts'] > 0 && ! isset($operation['rejection'])) {
            DB::transaction(function () use ($batch): void {
                if ($this->finish($batch, 'operation_outcome_unknown')) {
                    $batch->items()->update(array_fill_keys(BatchPlanItem::TRANSIENT_COLUMNS, null));
                }
            });
        } else {
            if (($operation['rejection'] ?? null) === 'plan_changed') {
                $batch->items()->update(['decision' => PlanDecision::Pending, 'edited_draft_body' => null]);
            }
            $this->finish($batch, $operation['rejection'] ?? ($batch->isActive() ? 'operation_expired' : null));
        }

        return true;
    }

    private function recordSubmission(Batch $batch, array $operation): bool
    {
        if ($operation['attempts'] >= self::MAX_SUBMISSIONS) {
            $this->finish($batch, 'operation_unconfirmed');

            return false;
        }

        // Rekonsiliasi berikutnya harus tahu bila perintah mungkin sudah diterima agen.
        $operation['attempts']++;
        $batch->update(['pending_operation' => $operation]);

        return true;
    }

    private function finish(Batch $batch, ?string $error = null, ?BatchStatus $status = null): bool
    {
        return Batch::query()->whereKey($batch->id)
            ->where('status', $batch->status)
            ->where('pending_operation->id', $this->operationId)
            ->update([
                'status' => $status ?? $batch->status,
                'pending_operation' => null,
                'agent_error' => $error === null ? null : json_encode(Batch::agentError($error), JSON_THROW_ON_ERROR),
            ]) === 1;
    }

    private function decisionPayload(BatchPlanItem $item): array
    {
        $payload = ['item_id' => $item->item_id, 'decision' => $item->decision->value];
        if ($item->decision === PlanDecision::Approve) {
            if ($item->action === PlanAction::DraftReply && $item->edited_draft_body !== null) {
                $payload['edited_draft_body'] = $item->edited_draft_body;
            }
            if ($item->action === PlanAction::Trash || ($item->review_data['requires_confirmation'] ?? false)) {
                $payload['confirmed_trash'] = true;
            }
        }

        return $payload;
    }
}
