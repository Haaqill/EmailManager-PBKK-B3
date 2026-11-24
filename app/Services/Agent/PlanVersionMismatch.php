<?php

namespace App\Services\Agent;

use RuntimeException;
use Throwable;

/**
 * Keputusan dikirim untuk plan_version yang sudah tidak berlaku.
 */
class PlanVersionMismatch extends RuntimeException
{
    public function __construct(string $message = '', int $code = 0, ?Throwable $previous = null, public readonly ?string $agentCode = null)
    {
        parent::__construct($message, $code, $previous);
    }

    public static function for(string $agentBatchId, int $sent, int $current): self
    {
        return new self("Batch {$agentBatchId}: plan_version {$sent} dikirim, versi berlaku {$current}.");
    }
}
