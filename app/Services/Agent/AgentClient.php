<?php

namespace App\Services\Agent;

/**
 * Perintah Laravel ke agen batch (lihat docs/contract-laravel-python.md, bagian
 * "Perintah Laravel → agen"). Implementasi dipilih lewat config('agent.driver').
 */
interface AgentClient
{
    /**
     * Mulai batch baru. Mengembalikan agent_batch_id.
     *
     * @param  array<string, mixed>  $filters
     *
     * @throws AgentUnavailable
     */
    public function startBatch(int $userId, array $filters): string;

    /**
     * Status batch saat ini, dalam bentuk yang diterima BatchSyncService::sync().
     *
     * @return array<string, mixed>
     *
     * @throws AgentUnavailable
     */
    public function getBatch(int $userId, string $agentBatchId): array;

    /**
     * Jalankan item yang diputuskan eksplisit. Item yang tidak ada di $decisions tidak
     * dijalankan (default-deny). Idempoten: panggilan ulang pada batch executing/done
     * tidak mengeksekusi ulang.
     *
     * @param  list<array{item_id: string, decision: 'approve'|'reject', edited_draft_body?: string, confirmed_trash?: true}>  $decisions
     *
     * @throws PlanVersionMismatch
     * @throws AgentUnavailable
     */
    public function execute(int $userId, string $agentBatchId, int $planVersion, array $decisions): void;

    /**
     * @throws AgentUnavailable
     */
    public function cancel(int $userId, string $agentBatchId): void;
}
