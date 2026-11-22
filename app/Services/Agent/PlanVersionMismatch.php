<?php

namespace App\Services\Agent;

use RuntimeException;

/**
 * Keputusan dikirim untuk plan_version yang sudah tidak berlaku.
 */
class PlanVersionMismatch extends RuntimeException
{
    public static function for(string $agentBatchId, int $sent, int $current): self
    {
        return new self("Batch {$agentBatchId}: plan_version {$sent} dikirim, versi berlaku {$current}.");
    }
}
