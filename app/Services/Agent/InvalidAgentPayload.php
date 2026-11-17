<?php

namespace App\Services\Agent;

use RuntimeException;

/**
 * Payload dari agen tidak sesuai kontrak (docs/contract-laravel-python.md).
 * Pesan hanya menyebut field, bukan isinya.
 */
class InvalidAgentPayload extends RuntimeException
{
    public static function field(string $field, string $problem = 'tidak valid'): self
    {
        return new self("Payload agen: {$field} {$problem}.");
    }
}
