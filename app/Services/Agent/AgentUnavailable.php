<?php

namespace App\Services\Agent;

use RuntimeException;
use Throwable;

/**
 * Agen tidak bisa dihubungi atau tidak mengenal batch yang diminta.
 * Pesan untuk log; UI menampilkan teks ramah sendiri.
 */
class AgentUnavailable extends RuntimeException
{
    public function __construct(string $message = '', int $code = 0, ?Throwable $previous = null, public readonly ?string $agentCode = null)
    {
        parent::__construct($message, $code, $previous);
    }

    public function safeCode(): string
    {
        return match ($this->agentCode) {
            'unauthorized', 'batch_not_found', 'invalid_state', 'gmail_not_connected',
            'invalid_request', 'llm_unavailable', 'gmail_unavailable' => $this->agentCode,
            default => 'agent_unavailable',
        };
    }
}
