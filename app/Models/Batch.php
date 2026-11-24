<?php

namespace App\Models;

use App\Enums\BatchStatus;
use Closure;
use Illuminate\Contracts\Cache\Lock;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Facades\Cache;

class Batch extends Model
{
    public const WORKER_TIMEOUT = 45;

    public const LOCK_SECONDS = 60;

    public const OPERATION_SECONDS = 120;

    public const MAX_HTTP_TIMEOUT = 20;

    protected $fillable = [
        'user_id',
        'agent_batch_id',
        'status',
        'plan_version',
        'filters',
        'summary',
        'finished_at',
        'pending_operation',
        'agent_error',
    ];

    protected function casts(): array
    {
        return [
            'status' => BatchStatus::class,
            'plan_version' => 'integer',
            'filters' => 'array',
            'summary' => 'array',
            'finished_at' => 'datetime',
            'pending_operation' => 'array',
            'agent_error' => 'array',
        ];
    }

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    /** Batch yang belum berakhir (memblokir mulai batch baru). */
    public function isActive(): bool
    {
        return ! $this->status->isFinished();
    }

    public static function operationLock(int $batchId): Lock
    {
        return Cache::lock('batch-operation:' . $batchId, self::LOCK_SECONDS);
    }

    public function isReconciling(): bool
    {
        return ($this->agent_error['code'] ?? null) === 'operation_outcome_unknown';
    }

    public static function operationWriteGuard(Lock $lock): Closure
    {
        $deadline = now()->addSeconds(self::WORKER_TIMEOUT);
        $monotonicDeadline = hrtime(true) + self::WORKER_TIMEOUT * 1_000_000_000;

        return fn (): bool => now()->lt($deadline) && hrtime(true) < $monotonicDeadline
            && (! method_exists($lock, 'isOwnedByCurrentProcess') || $lock->isOwnedByCurrentProcess());
    }

    /** @return array{code: string, message: string} */
    public static function agentError(string $code): array
    {
        return ['code' => $code, 'message' => match ($code) {
            'plan_changed' => 'Rencana diperbarui; keputusan direset. Periksa ulang sebelum menjalankan.',
            'cancel_invalid_state' => 'Batch ini tidak bisa dibatalkan lagi.',
            'gmail_not_connected' => 'Gmail belum terhubung. Hubungkan Gmail sebelum memulai batch.',
            'batch_not_found' => 'Batch ini tidak lagi tersedia di agen.',
            'invalid_agent_payload' => 'Respons agen tidak valid. Status akan diperiksa lagi.',
            'batch_failed' => 'Agen tidak bisa menyelesaikan batch ini.',
            'operation_unconfirmed' => 'Perintah belum dikonfirmasi oleh agen. Silakan coba lagi.',
            'operation_expired' => 'Waktu untuk mengirim perintah habis. Silakan coba lagi.',
            'operation_outcome_unknown' => 'Hasil pengiriman belum diketahui. Status batch sedang diperiksa.',
            default => 'Agen sedang tidak bisa dihubungi. Silakan coba lagi.',
        }];
    }

    public function items(): HasMany
    {
        return $this->hasMany(BatchPlanItem::class)->orderBy('item_id');
    }
}
