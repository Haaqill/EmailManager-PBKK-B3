<?php

namespace App\Livewire;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanConfidence;
use App\Enums\PlanDecision;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\InvalidAgentPayload;
use App\Services\Agent\PlanVersionMismatch;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Facades\Cache;
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

    public const ERROR_UNAVAILABLE = 'Agen sedang tidak bisa dihubungi. Silakan coba lagi.';

    public const NOTICE_PLAN_CHANGED = 'Rencana diperbarui; keputusan direset. Periksa ulang sebelum menjalankan.';

    #[Locked]
    public int $batchId;

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

    /**
     * Dipanggil wire:poll selama status aktif, dan oleh tombol "Coba lagi".
     */
    public function refreshStatus(AgentClient $agent, BatchSyncService $sync): void
    {
        $batch = $this->batch;
        $this->authorize('view', $batch);
        if ($batch->status->isFinished()) {
            return;
        }

        $wasReview = $batch->status === BatchStatus::AwaitingReview;
        if ($this->syncFromAgent($agent, $sync, $batch) !== null && ! $wasReview) {
            $this->loadDrafts();
        }
    }

    public function setDecision(string $itemId, string $decision): void
    {
        $decision = PlanDecision::tryFrom($decision);
        $item = $this->reviewItem($itemId);
        if ($item === null || $decision === null) {
            return;
        }
        if ($decision === PlanDecision::Approve && $this->needsConfirmation($item)) {
            $this->errorMessage = 'Item yang dipindahkan ke Sampah harus disetujui lewat dialog konfirmasi.';

            return;
        }

        $item->update(['decision' => $decision]);
        unset($this->batch);
    }

    public function confirmTrash(string $itemId): void
    {
        $item = $this->reviewItem($itemId);
        if ($item === null || ! $this->needsConfirmation($item)) {
            return;
        }

        $item->update(['decision' => PlanDecision::Approve]);
        unset($this->batch);
    }

    /**
     * "Setujui semua yang aman": bukan trash, tanpa peringatan, dan keyakinan bukan rendah.
     */
    public function approveSafe(): void
    {
        $batch = $this->reviewableBatch();
        if ($batch === null) {
            return;
        }

        $ids = $batch->items->filter(fn (BatchPlanItem $i) => $this->isSafe($i))->pluck('id');
        BatchPlanItem::query()->whereIn('id', $ids)->update(['decision' => PlanDecision::Approve]);
        unset($this->batch);
    }

    public function rejectAll(): void
    {
        $batch = $this->reviewableBatch();
        if ($batch === null) {
            return;
        }

        BatchPlanItem::query()->where('batch_id', $batch->id)->update(['decision' => PlanDecision::Reject]);
        unset($this->batch);
    }

    /**
     * wire:model.blur pada textarea draf.
     */
    public function updatedDrafts(mixed $value, string $itemId): void
    {
        $item = $this->reviewItem($itemId);
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

        $original = $this->originalDraft($item);
        $item->update(['edited_draft_body' => $value === $original ? null : $value]);
        unset($this->batch);
    }

    public function resetDraft(string $itemId): void
    {
        $item = $this->reviewItem($itemId);
        if ($item === null || $item->action !== PlanAction::DraftReply) {
            return;
        }

        $item->update(['edited_draft_body' => null]);
        $this->drafts[$itemId] = $this->originalDraft($item);
        $this->resetErrorBag("drafts.{$itemId}");
        unset($this->batch);
    }

    public function execute(AgentClient $agent, BatchSyncService $sync): void
    {
        $batch = $this->reviewableBatch();
        if ($batch === null) {
            return;
        }

        // Klik ganda: permintaan kedua tidak mendapat kunci, atau melihat status executing.
        $done = Cache::lock('batch-execute:' . $batch->id, 30)->get(fn () => $this->runExecute($agent, $sync, $batch));
        if ($done === false) {
            $this->errorMessage = 'Eksekusi sedang diproses.';
        }
        unset($this->batch);
    }

    public function cancel(AgentClient $agent, BatchSyncService $sync): void
    {
        $batch = $this->batch;
        $this->authorize('cancel', $batch);
        if ($batch->status->isFinished() || $batch->status === BatchStatus::Executing) {
            $this->errorMessage = 'Batch ini tidak bisa dibatalkan lagi.';

            return;
        }

        try {
            $agent->cancel($batch->user_id, $batch->agent_batch_id);
        } catch (AgentUnavailable $e) {
            report($e);
            $this->errorMessage = self::ERROR_UNAVAILABLE;

            return;
        }
        $this->syncFromAgent($agent, $sync, $batch);
        $this->drafts = [];
    }

    public function render(): View
    {
        $batch = $this->batch;
        $items = $batch->items;
        $approved = $items->where('decision', PlanDecision::Approve);

        return view('livewire.batch-run', [
            'batch' => $batch,
            'items' => $items,
            'polling' => in_array($batch->status, [
                BatchStatus::Queued, BatchStatus::Scanning, BatchStatus::Classifying,
                BatchStatus::Drafting, BatchStatus::Executing,
            ], true),
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

    private function runExecute(AgentClient $agent, BatchSyncService $sync, Batch $batch): bool
    {
        if ($batch->items->where('decision', PlanDecision::Approve)->isEmpty()) {
            $this->errorMessage = 'Belum ada item yang disetujui.';

            return true;
        }

        // (1) Status terbaru dari agen; (2) jangan eksekusi bila rencana berubah.
        $version = $batch->plan_version;
        $fresh = $this->syncFromAgent($agent, $sync, $batch);
        if ($fresh === null) {
            return true;
        }
        if ($fresh->plan_version !== $version || $fresh->status !== BatchStatus::AwaitingReview) {
            $this->planChanged();

            return true;
        }

        // (3) Hanya item yang diputuskan eksplisit yang dikirim.
        $decisions = $fresh->items
            ->reject(fn (BatchPlanItem $i) => $i->decision === PlanDecision::Pending)
            ->map(fn (BatchPlanItem $i) => $this->decisionPayload($i))
            ->values()
            ->all();

        try {
            $agent->execute($fresh->user_id, $fresh->agent_batch_id, $version, $decisions);
        } catch (PlanVersionMismatch) {
            $this->syncFromAgent($agent, $sync, $fresh);
            $this->planChanged();

            return true;
        } catch (AgentUnavailable $e) {
            report($e);
            $this->errorMessage = self::ERROR_UNAVAILABLE;

            return true;
        }

        $this->notice = null;
        $this->syncFromAgent($agent, $sync, $fresh);

        return true;
    }

    /**
     * @return array{item_id: string, decision: string, edited_draft_body?: string, confirmed_trash?: true}
     */
    private function decisionPayload(BatchPlanItem $item): array
    {
        $payload = ['item_id' => $item->item_id, 'decision' => $item->decision->value];
        if ($item->decision === PlanDecision::Approve) {
            if ($item->action === PlanAction::DraftReply && $item->edited_draft_body !== null) {
                $payload['edited_draft_body'] = $item->edited_draft_body;
            }
            if ($this->needsConfirmation($item)) {
                $payload['confirmed_trash'] = true;
            }
        }

        return $payload;
    }

    private function syncFromAgent(AgentClient $agent, BatchSyncService $sync, Batch $batch): ?Batch
    {
        try {
            $fresh = $sync->sync($batch->user_id, $agent->getBatch($batch->user_id, $batch->agent_batch_id));
        } catch (AgentUnavailable|InvalidAgentPayload $e) {
            report($e);
            $this->errorMessage = self::ERROR_UNAVAILABLE;

            return null;
        }
        $this->errorMessage = null;
        unset($this->batch);

        return $fresh->load('items');
    }

    private function planChanged(): void
    {
        $this->notice = self::NOTICE_PLAN_CHANGED;
        $this->loadDrafts();
    }

    private function reviewableBatch(): ?Batch
    {
        $batch = $this->batch;
        $this->authorize('execute', $batch);
        if ($batch->status !== BatchStatus::AwaitingReview) {
            $this->errorMessage = 'Batch ini tidak lagi menunggu review.';

            return null;
        }

        return $batch;
    }

    private function reviewItem(string $itemId): ?BatchPlanItem
    {
        $batch = $this->reviewableBatch();

        return $batch?->items->firstWhere('item_id', $itemId);
    }

    private function loadDrafts(): void
    {
        unset($this->batch);
        $this->drafts = $this->batch->items
            ->filter(fn (BatchPlanItem $i) => $i->action === PlanAction::DraftReply && $i->review_data !== null)
            ->mapWithKeys(fn (BatchPlanItem $i) => [$i->item_id => $i->edited_draft_body ?? $this->originalDraft($i)])
            ->all();
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
