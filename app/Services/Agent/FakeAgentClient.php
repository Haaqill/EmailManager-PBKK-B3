<?php

namespace App\Services\Agent;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Str;

/**
 * Agen tiruan untuk mode demo (AGENT_DRIVER=fake). Tidak menghubungi Gmail maupun LLM.
 *
 * Status disimpan di Cache per agent_batch_id dan dihitung dari waktu berlalu:
 * queued → scanning → classifying → drafting → awaiting_review (tiap tahap
 * agent.fake.step_seconds). Setelah execute(): executing, lalu done setelah satu tahap,
 * dengan report yang dihitung dari keputusan. Item berasal dari
 * resources/demo/batch_awaiting_review.json.
 */
class FakeAgentClient implements AgentClient
{
    public const FIXTURE = 'demo/batch_awaiting_review.json';

    private const TTL_SECONDS = 86400;

    private const STAGES = [
        BatchStatus::Queued,
        BatchStatus::Scanning,
        BatchStatus::Classifying,
        BatchStatus::Drafting,
        BatchStatus::AwaitingReview,
    ];

    public function startBatch(int $userId, array $filters): string
    {
        $id = 'b_demo_' . Str::lower((string) Str::ulid());
        $this->put($id, [
            'user_id' => $userId,
            'filters' => $filters,
            'started_at' => now()->getTimestamp(),
            'plan_version' => 1,
            'cancelled' => false,
            'executed_at' => null,
            'decisions' => [],
            'executions' => 0,
        ]);

        return $id;
    }

    public function getBatch(int $userId, string $agentBatchId): array
    {
        $state = $this->state($userId, $agentBatchId);
        $status = $this->status($state);
        $hasPlan = $status === BatchStatus::AwaitingReview
            || $status === BatchStatus::Executing
            || $status === BatchStatus::Done
            || ($status === BatchStatus::Cancelled && ($state['reviewed'] ?? false));

        return [
            'batch_id' => $agentBatchId,
            'status' => $status->value,
            'filters' => $state['filters'],
            'plan' => $hasPlan ? ['plan_version' => $state['plan_version'], 'items' => $this->items($state)] : null,
            'report' => $status === BatchStatus::Done ? $this->report($state) : null,
        ];
    }

    public function execute(int $userId, string $agentBatchId, int $planVersion, array $decisions): void
    {
        $state = $this->state($userId, $agentBatchId);
        if ($state['executed_at'] !== null) {
            return; // idempoten: executing/done tidak dieksekusi ulang
        }
        if ($this->status($state) !== BatchStatus::AwaitingReview) {
            throw new AgentUnavailable("Batch {$agentBatchId} belum atau tidak lagi menunggu review.");
        }
        if ($planVersion !== $state['plan_version']) {
            throw PlanVersionMismatch::for($agentBatchId, $planVersion, $state['plan_version']);
        }

        $byId = [];
        foreach ($decisions as $d) {
            if (is_array($d) && is_string($d['item_id'] ?? null) && in_array($d['decision'] ?? null, ['approve', 'reject'], true)) {
                $byId[$d['item_id']] = [
                    'decision' => $d['decision'],
                    'confirmed_trash' => ($d['confirmed_trash'] ?? false) === true,
                ];
            }
        }

        $state['decisions'] = $byId;
        $state['executed_at'] = now()->getTimestamp();
        $state['executions']++;
        $this->put($agentBatchId, $state);
    }

    public function cancel(int $userId, string $agentBatchId): void
    {
        $state = $this->state($userId, $agentBatchId);
        if ($state['executed_at'] !== null || $state['cancelled']) {
            return;
        }
        $state['reviewed'] = $this->status($state) === BatchStatus::AwaitingReview;
        $state['cancelled'] = true;
        $this->put($agentBatchId, $state);
    }

    /**
     * Simulasi agen memperbarui rencana selama review (untuk tes dan demo).
     */
    public function revisePlan(int $userId, string $agentBatchId): int
    {
        $state = $this->state($userId, $agentBatchId);
        $state['plan_version']++;
        $this->put($agentBatchId, $state);

        return $state['plan_version'];
    }

    /**
     * Berapa kali execute() benar-benar mengeksekusi (untuk tes idempotensi).
     */
    public function executions(int $userId, string $agentBatchId): int
    {
        return $this->state($userId, $agentBatchId)['executions'];
    }

    /**
     * @param  array<string, mixed>  $state
     */
    private function status(array $state): BatchStatus
    {
        if ($state['cancelled']) {
            return BatchStatus::Cancelled;
        }
        $step = max(1, (int) config('agent.fake.step_seconds', 2));
        if ($state['executed_at'] !== null) {
            return now()->getTimestamp() - $state['executed_at'] < $step ? BatchStatus::Executing : BatchStatus::Done;
        }
        $index = intdiv(max(0, now()->getTimestamp() - $state['started_at']), $step);

        return self::STAGES[min($index, count(self::STAGES) - 1)];
    }

    /**
     * @param  array<string, mixed>  $state
     * @return list<array<string, mixed>>
     */
    private function items(array $state): array
    {
        $fixture = json_decode((string) file_get_contents(resource_path(self::FIXTURE)), true, flags: JSON_THROW_ON_ERROR);
        $limit = min(
            (int) config('agent.max_threads', 10),
            max(1, (int) ($state['filters']['max_results'] ?? PHP_INT_MAX)),
        );

        return array_slice($fixture['plan']['items'], 0, $limit);
    }

    /**
     * Report berbentuk sama dengan tests/Fixtures/agent/batch_done.json.
     *
     * @param  array<string, mixed>  $state
     * @return array<string, mixed>
     */
    private function report(array $state): array
    {
        $counts = ['approved' => 0, 'rejected' => 0, 'skipped' => 0, 'actions_ok' => 0, 'actions_failed' => 0];
        $results = [];
        foreach ($this->items($state) as $item) {
            $decision = $state['decisions'][$item['item_id']] ?? null;
            $action = PlanAction::from($item['action']);
            $confirmed = ! $item['requires_confirmation'] || ($decision['confirmed_trash'] ?? false);

            if ($decision === null || ($decision['decision'] === 'approve' && ! $confirmed)) {
                // Tidak diputuskan, atau trash tanpa konfirmasi: tidak dijalankan.
                $counts['skipped']++;
                $results[] = ['item_id' => $item['item_id'], 'status' => 'skipped', 'applied' => null];
            } elseif ($decision['decision'] === 'reject') {
                $counts['rejected']++;
                $results[] = ['item_id' => $item['item_id'], 'status' => 'rejected', 'applied' => null];
            } else {
                $counts['approved']++;
                $counts['actions_ok']++;
                $results[] = ['item_id' => $item['item_id'], 'status' => 'ok', 'applied' => [
                    'labels' => $action === PlanAction::Trash ? [] : [
                        'Kategori/' . Str::ucfirst($item['category']),
                        'Prioritas/' . Str::ucfirst($item['priority']),
                    ],
                    'archived' => $action === PlanAction::Archive || $item['also_archive'],
                    'draft_id' => $action === PlanAction::DraftReply ? 'r-demo-' . $item['item_id'] : null,
                ]];
            }
        }

        return ['summary' => $counts, 'results' => $results];
    }

    /**
     * @return array<string, mixed>
     */
    private function state(int $userId, string $agentBatchId): array
    {
        $state = Cache::get($this->key($agentBatchId));
        if (! is_array($state) || $state['user_id'] !== $userId) {
            throw new AgentUnavailable("Batch {$agentBatchId} tidak dikenal agen tiruan.");
        }

        return $state;
    }

    /**
     * @param  array<string, mixed>  $state
     */
    private function put(string $agentBatchId, array $state): void
    {
        Cache::put($this->key($agentBatchId), $state, self::TTL_SECONDS);
    }

    private function key(string $agentBatchId): string
    {
        return 'agent-fake:' . $agentBatchId;
    }
}
