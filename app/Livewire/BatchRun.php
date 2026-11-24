<?php

namespace App\Livewire;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanConfidence;
use App\Enums\PlanDecision;
use App\Jobs\RunBatchOperationJob;
use App\Jobs\SyncBatchStatusJob;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use Closure;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Str;
use Livewire\Attributes\Computed;
use Livewire\Attributes\Locked;
use Livewire\Component;

/**
 * Halaman /batch/{batch}: tahap berjalan, review, eksekusi, laporan, dan status akhir.
 *
 * Keputusan dan edited_draft_body adalah status lokal (lihat BatchSyncService). Item yang
 * tidak diputuskan tidak dikirim ke agen, jadi tidak dijalankan (default-deny). Trash
 * hanya bisa disetujui lewat confirmTrash().
 */
class BatchRun extends Component
{
    public const DRAFT_MAX = 10000;

    #[Locked]
    public int $batchId;

    #[Locked]
    public ?int $reviewedPlanVersion = null;

    #[Locked]
    public ?string $localReviewRevision = null;

    /** @var array<string, string> item_id => badan draf yang sedang diedit */
    public array $drafts = [];

    public ?string $errorMessage = null;

    public ?string $notice = null;

    public function mount(int $batchId): void
    {
        $this->authorize('view', Batch::query()->findOrFail($batchId));
        $this->batchId = $batchId;
        $this->loadDrafts();
    }

    #[Computed]
    public function batch(): Batch
    {
        return Batch::query()->with('items')->findOrFail($this->batchId);
    }

    public function refreshStatus(): void
    {
        unset($this->batch);
        $batch = $this->batch;
        $this->authorize('view', $batch);
        $this->errorMessage = null;
        $this->loadDrafts();
    }

    public function retrySync(): void
    {
        $batch = $this->batch;
        $this->authorize('view', $batch);
        if ($batch->pending_operation !== null) {
            RunBatchOperationJob::dispatch($batch->id, $batch->pending_operation['id']);
        } elseif ($batch->isReconciling() || in_array($batch->status, BatchStatus::POLLABLE, true)) {
            SyncBatchStatusJob::dispatch($batch->id);
        }
    }

    public function setDecision(string $itemId, string $decision): void
    {
        $this->withReviewBatch(function (Batch $batch) use ($itemId, $decision): void {
            $decision = PlanDecision::tryFrom($decision);
            $item = $batch->items->firstWhere('item_id', $itemId);
            if ($item === null || $decision === null) {
                return;
            }
            if ($decision === PlanDecision::Approve && $this->needsConfirmation($item)) {
                $this->errorMessage = 'Item yang dipindahkan ke Sampah harus disetujui lewat dialog konfirmasi.';

                return;
            }
            $item->update(['decision' => $decision]);
        });
    }

    public function confirmTrash(string $itemId): void
    {
        $this->withReviewBatch(function (Batch $batch) use ($itemId): void {
            $item = $batch->items->firstWhere('item_id', $itemId);
            if ($item !== null && $this->needsConfirmation($item)) {
                $item->update(['decision' => PlanDecision::Approve]);
            }
        });
    }

    /**
     * "Setujui semua yang aman": bukan trash, tanpa peringatan, dan keyakinan bukan rendah.
     */
    public function approveSafe(): void
    {
        $this->withReviewBatch(function (Batch $batch): void {
            $ids = $batch->items->filter(fn (BatchPlanItem $i) => $this->isSafe($i))->pluck('id');
            BatchPlanItem::query()->whereIn('id', $ids)->update(['decision' => PlanDecision::Approve]);
        });
    }

    public function rejectAll(): void
    {
        $this->withReviewBatch(fn (Batch $batch) => $batch->items()->update(['decision' => PlanDecision::Reject]));
    }

    /**
     * wire:model.blur pada textarea draf.
     */
    public function updatedDrafts(mixed $value, string $itemId): void
    {
        $this->withReviewBatch(function (Batch $batch) use ($value, $itemId): void {
            $item = $batch->items->firstWhere('item_id', $itemId);
            if ($item === null || $item->action !== PlanAction::DraftReply) {
                unset($this->drafts[$itemId]);

                return;
            }

            $value = is_string($value) ? $value : '';
            if (mb_strlen($value) > self::DRAFT_MAX) {
                $this->addError("drafts.{$itemId}", 'Draf maksimal ' . number_format(self::DRAFT_MAX, 0, ',', '.') . ' karakter.');

                return;
            }
            $this->resetErrorBag("drafts.{$itemId}");
            $this->saveDraft($item, $value === $this->originalDraft($item) ? null : $value);
        });
    }

    public function resetDraft(string $itemId): void
    {
        $this->withReviewBatch(function (Batch $batch) use ($itemId): void {
            $item = $batch->items->firstWhere('item_id', $itemId);
            if ($item === null || $item->action !== PlanAction::DraftReply) {
                return;
            }

            $this->saveDraft($item, null);
            $this->drafts[$itemId] = $this->originalDraft($item);
            $this->resetErrorBag("drafts.{$itemId}");
        });
    }

    public function execute(): void
    {
        $this->withReviewBatch(function (Batch $batch): void {
            if ($this->localReviewRevision !== $this->reviewRevision($batch)) {
                $this->errorMessage = 'Keputusan atau draf berubah. Tinjau ulang sebelum menjalankan.';
                $this->loadDrafts();

                return;
            }
            if ($batch->items->where('decision', PlanDecision::Approve)->isEmpty()) {
                $this->errorMessage = 'Belum ada item yang disetujui.';

                return;
            }

            $this->queueOperation($batch, RunBatchOperationJob::EXECUTE);
        });
    }

    public function cancel(): void
    {
        $this->withOperationLock('cancel', function (Batch $batch): void {
            if ($batch->status->isFinished() || $batch->status === BatchStatus::Executing) {
                $this->errorMessage = 'Batch ini tidak bisa dibatalkan lagi.';

                return;
            }
            $this->queueOperation($batch, RunBatchOperationJob::CANCEL);
        });
    }

    public function render(): View
    {
        $batch = $this->batch;
        $items = $batch->items;
        $approved = $items->where('decision', PlanDecision::Approve);
        $this->localReviewRevision = $batch->status === BatchStatus::AwaitingReview
            && $batch->pending_operation === null && ! $batch->isReconciling() ? $this->reviewRevision($batch) : null;

        return view('livewire.batch-run', [
            'batch' => $batch,
            'items' => $items,
            'polling' => $batch->isReconciling() || $batch->pending_operation !== null
                || in_array($batch->status, BatchStatus::POLLABLE, true),
            'actionCounts' => collect(PlanAction::cases())
                ->mapWithKeys(fn (PlanAction $a) => [$a->label() => $items->where('action', $a)->count()])
                ->filter(),
            'attention' => $items->filter(fn (BatchPlanItem $i) => $this->needsAttention($i))->count(),
            'decisionCounts' => [
                'approve' => $approved->count(),
                'reject' => $items->where('decision', PlanDecision::Reject)->count(),
                'pending' => $items->where('decision', PlanDecision::Pending)->count(),
            ],
            'plannedActions' => array_filter([
                'Beri label' => $approved->where('action', PlanAction::LabelOnly)->count(),
                'Draf balasan dibuat (tidak dikirim)' => $approved->where('action', PlanAction::DraftReply)->count(),
                'Thread diarsipkan' => $approved->filter(fn (BatchPlanItem $i) => $i->action === PlanAction::Archive
                    || ($i->action === PlanAction::DraftReply && ($i->review_data['also_archive'] ?? false)))->count(),
                'Dipindahkan ke Sampah' => $approved->where('action', PlanAction::Trash)->count(),
            ]),
            'safeCount' => $items->filter(fn (BatchPlanItem $i) => $this->isSafe($i))->count(),
            'resultCounts' => [
                'Berhasil' => $items->where('result_status', 'ok')->count(),
                'Gagal' => $items->where('result_status', 'failed')->count(),
                'Dilewati' => $items->where('result_status', 'skipped')->count(),
                'Ditolak' => $items->where('result_status', 'rejected')->count(),
            ],
            'demo' => config('agent.driver') === 'fake',
        ]);
    }

    private function queueOperation(Batch $batch, string $type): void
    {
        $id = (string) Str::uuid();
        $batch->update([
            'pending_operation' => [
                'id' => $id,
                'type' => $type,
                'plan_version' => $batch->plan_version,
                'attempts' => 0,
                'expires_at' => now()->timestamp + Batch::OPERATION_SECONDS,
            ],
            'agent_error' => null,
        ]);
        $this->errorMessage = null;
        $this->notice = null;
        $this->drafts = [];

        RunBatchOperationJob::dispatch($batch->id, $id);
    }

    private function withReviewBatch(Closure $action): void
    {
        $this->withOperationLock('execute', function (Batch $batch) use ($action): void {
            if ($batch->status !== BatchStatus::AwaitingReview) {
                $this->errorMessage = 'Batch ini tidak lagi menunggu review.';

                return;
            }
            if ($batch->plan_version !== $this->reviewedPlanVersion) {
                $this->notice = Batch::agentError('plan_changed')['message'];
                $this->loadDrafts();

                return;
            }
            $action($batch);
        });
    }

    private function withOperationLock(string $ability, Closure $action): void
    {
        $this->authorize($ability, $this->batch);
        $locked = Batch::operationLock($this->batchId)->get(function () use ($action): void {
            unset($this->batch);
            $batch = $this->batch;
            if ($batch->pending_operation !== null || $batch->isReconciling()) {
                $this->errorMessage = 'Perintah batch masih diproses.';

                return;
            }
            $action($batch);
        });
        if ($locked === false) {
            $this->errorMessage = 'Perintah batch masih diproses.';
        }
        unset($this->batch);
    }

    private function loadDrafts(): void
    {
        $batch = $this->batch;
        if ($batch->status !== BatchStatus::AwaitingReview || $batch->pending_operation !== null || $batch->isReconciling()) {
            $this->reviewedPlanVersion = null;
            $this->drafts = [];

            return;
        }

        $this->reviewedPlanVersion = $batch->plan_version;
        $this->drafts = $batch->items
            ->filter(fn (BatchPlanItem $i) => $i->action === PlanAction::DraftReply && $i->review_data !== null)
            ->mapWithKeys(fn (BatchPlanItem $i) => [$i->item_id => $i->edited_draft_body ?? $this->originalDraft($i)])
            ->all();
    }

    private function saveDraft(BatchPlanItem $item, ?string $body): void
    {
        if ($item->edited_draft_body !== $body) {
            $item->update([
                'edited_draft_body' => $body,
                'decision' => $item->decision === PlanDecision::Approve ? PlanDecision::Pending : $item->decision,
            ]);
        }
    }

    private function reviewRevision(Batch $batch): string
    {
        return hash_hmac('sha256', serialize($batch->items->map(fn (BatchPlanItem $item) => [
            $item->item_id, $item->decision->value, $item->edited_draft_body,
        ])->all()), (string) config('app.key'));
    }

    private function originalDraft(BatchPlanItem $item): string
    {
        return (string) ($item->review_data['draft']['body'] ?? '');
    }

    private function needsConfirmation(BatchPlanItem $item): bool
    {
        return $item->action === PlanAction::Trash || ($item->review_data['requires_confirmation'] ?? false);
    }

    private function needsAttention(BatchPlanItem $item): bool
    {
        return $this->needsConfirmation($item) || ! empty($item->review_data['warnings'] ?? []);
    }

    private function isSafe(BatchPlanItem $item): bool
    {
        return ! $this->needsAttention($item)
            && ($item->review_data['confidence'] ?? null) !== PlanConfidence::Rendah->value;
    }
}
