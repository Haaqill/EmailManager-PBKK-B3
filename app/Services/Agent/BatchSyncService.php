<?php

namespace App\Services\Agent;

use App\Enums\BatchStatus;
use App\Enums\PlanDecision;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use Illuminate\Support\Facades\DB;

/**
 * Menyalin status batch dari agen (JSON GET /v1/batches/{id} yang sudah di-decode)
 * ke tabel batches dan batch_plan_items, dengan kebijakan penyimpanan minimal:
 *
 * - kolom kekal di-upsert dari payload;
 * - review_data (SEMENTARA) hanya terisi selama awaiting_review/executing;
 * - decision dan edited_draft_body adalah status lokal Laravel, tidak pernah ditimpa;
 * - saat batch berakhir, kolom sementara dikosongkan untuk semua item.
 */
class BatchSyncService
{
    /**
     * @param  array<string, mixed>  $payload
     *
     * @throws InvalidAgentPayload
     */
    public function sync(int $userId, array $payload): Batch
    {
        $agentBatchId = $payload['batch_id'] ?? null;
        if (! is_string($agentBatchId) || $agentBatchId === '') {
            throw InvalidAgentPayload::field('batch_id', 'wajib berupa string');
        }

        $status = BatchStatus::tryFrom((string) ($payload['status'] ?? ''));
        if ($status === null || $status === BatchStatus::Expired) {
            throw InvalidAgentPayload::field('status');
        }

        [$planVersion, $items] = $this->parsePlan($payload['plan'] ?? null);
        $results = $status->isFinished() ? $this->parseResults($payload['report'] ?? null) : [];

        return DB::transaction(function () use ($userId, $agentBatchId, $status, $planVersion, $items, $results, $payload) {
            $batch = Batch::query()->where('agent_batch_id', $agentBatchId)->lockForUpdate()->first();

            if ($batch !== null && $batch->user_id !== $userId) {
                throw InvalidAgentPayload::field('batch_id', 'milik pengguna lain');
            }
            // Batch yang sudah kedaluwarsa di Laravel tidak dihidupkan lagi oleh sync,
            // supaya data review yang sudah dibersihkan tidak terisi ulang.
            if ($batch !== null && $batch->status === BatchStatus::Expired && ! $status->isFinished()) {
                return $batch;
            }

            $batch ??= new Batch(['user_id' => $userId, 'agent_batch_id' => $agentBatchId]);
            $versionChanged = $batch->exists && $planVersion !== null && $planVersion !== $batch->plan_version;

            $batch->status = $status;
            if (array_key_exists('filters', $payload)) {
                $batch->filters = is_array($payload['filters']) ? $payload['filters'] : null;
            }
            if ($planVersion !== null) {
                $batch->plan_version = $planVersion;
            }
            if ($status->isFinished()) {
                $batch->summary = $this->numericSummary($payload['report']['summary'] ?? null);
                $batch->finished_at ??= now();
            }
            $batch->save();

            if ($status->inReview()) {
                $this->syncReviewItems($batch, $items, $versionChanged);
            } elseif ($status->isFinished()) {
                $this->finishItems($batch, $items, $results);
            }

            return $batch->refresh();
        });
    }

    /**
     * @param  list<PlanItemData>  $items
     */
    private function syncReviewItems(Batch $batch, array $items, bool $versionChanged): void
    {
        if ($versionChanged) {
            // Keputusan untuk plan lama tidak boleh terbawa ke plan baru.
            BatchPlanItem::query()->where('batch_id', $batch->id)->update([
                'decision' => PlanDecision::Pending,
                'edited_draft_body' => null,
            ]);
        }

        foreach ($items as $data) {
            $this->upsertItem($batch, $data, withReviewData: true);
        }

        // Item yang tidak ada lagi di plan terbaru dibuang (beserta log tool-nya).
        BatchPlanItem::query()
            ->where('batch_id', $batch->id)
            ->whereNotIn('item_id', array_map(fn (PlanItemData $d) => $d->itemId, $items))
            ->get()
            ->each->delete();
    }

    /**
     * @param  list<PlanItemData>  $items
     * @param  array<string, array{status: string, applied: array<string, mixed>|null}>  $results
     */
    private function finishItems(Batch $batch, array $items, array $results): void
    {
        foreach ($items as $data) {
            $this->upsertItem($batch, $data, withReviewData: false);
        }

        BatchPlanItem::query()
            ->where('batch_id', $batch->id)
            ->update(array_fill_keys(BatchPlanItem::TRANSIENT_COLUMNS, null));

        foreach ($results as $itemId => $result) {
            $updated = BatchPlanItem::query()
                ->where('batch_id', $batch->id)
                ->where('item_id', $itemId)
                ->update([
                    'result_status' => $result['status'],
                    'applied' => $result['applied'] === null ? null : json_encode($result['applied']),
                ]);
            if ($updated === 0) {
                throw InvalidAgentPayload::field("report.results[{$itemId}]", 'merujuk item yang tidak ada');
            }
        }
    }

    private function upsertItem(Batch $batch, PlanItemData $data, bool $withReviewData): void
    {
        $row = BatchPlanItem::query()->firstOrNew([
            'batch_id' => $batch->id,
            'item_id' => $data->itemId,
        ]);
        // decision dan edited_draft_body sengaja tidak disentuh.
        $row->fill($data->permanentColumns());
        if ($withReviewData) {
            $row->review_data = $data->reviewData;
        }
        if (! $row->exists) {
            $row->decision = PlanDecision::Pending;
        }
        $row->save();
    }

    /**
     * @return array{0: int|null, 1: list<PlanItemData>}
     */
    private function parsePlan(mixed $plan): array
    {
        if ($plan === null) {
            return [null, []];
        }
        if (! is_array($plan)) {
            throw InvalidAgentPayload::field('plan');
        }

        $version = $plan['plan_version'] ?? null;
        if (! is_int($version) || $version < 1) {
            throw InvalidAgentPayload::field('plan.plan_version');
        }
        if (! is_array($plan['items'] ?? null) || ! array_is_list($plan['items'])) {
            throw InvalidAgentPayload::field('plan.items');
        }

        $items = [];
        foreach ($plan['items'] as $index => $item) {
            if (! is_array($item)) {
                throw InvalidAgentPayload::field("plan.items[{$index}]");
            }
            $data = PlanItemData::fromArray($item, $index);
            if (isset($items[$data->itemId])) {
                throw InvalidAgentPayload::field("plan.items[{$index}].item_id", 'duplikat');
            }
            $items[$data->itemId] = $data;
        }

        return [$version, array_values($items)];
    }

    /**
     * @return array<string, array{status: string, applied: array<string, mixed>|null}>
     */
    private function parseResults(mixed $report): array
    {
        $results = is_array($report) ? ($report['results'] ?? []) : [];
        if (! is_array($results)) {
            throw InvalidAgentPayload::field('report.results');
        }

        $out = [];
        foreach ($results as $index => $result) {
            $itemId = $result['item_id'] ?? null;
            $status = $result['status'] ?? null;
            if (! is_string($itemId) || $itemId === '' || ! is_string($status) || strlen($status) > 32) {
                throw InvalidAgentPayload::field("report.results[{$index}]");
            }
            $out[$itemId] = ['status' => $status, 'applied' => $this->applied($result['applied'] ?? null)];
        }

        return $out;
    }

    /**
     * Hanya nama label, flag arsip, dan draft_id yang disimpan.
     *
     * @return array{labels: list<string>, archived: bool, draft_id: string|null}|null
     */
    private function applied(mixed $applied): ?array
    {
        if (! is_array($applied)) {
            return null;
        }

        return [
            'labels' => array_values(array_filter((array) ($applied['labels'] ?? []), 'is_string')),
            'archived' => (bool) ($applied['archived'] ?? false),
            'draft_id' => is_string($applied['draft_id'] ?? null) ? $applied['draft_id'] : null,
        ];
    }

    /**
     * @return array<string, int|float>|null
     */
    private function numericSummary(mixed $summary): ?array
    {
        if (! is_array($summary)) {
            return null;
        }

        return array_filter($summary, fn ($v, $k) => is_string($k) && (is_int($v) || is_float($v)), ARRAY_FILTER_USE_BOTH);
    }
}
