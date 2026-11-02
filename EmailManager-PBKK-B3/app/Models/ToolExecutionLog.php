<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\MorphTo;

class ToolExecutionLog extends Model
{
    use HasFactory;

    protected $fillable = [
        'tool_name',
        'tool_call_id',
        'arguments',
        'result',
        'status',
        'duration_ms',
        'error_message',
    ];

    protected static function booted(): void
    {
        // chat_session_id tidak ada di $fillable: selalu diturunkan dari sumber log,
        // sehingga $message->toolLogs()->create([...]) tetap valid dan konsisten.
        static::creating(function (ToolExecutionLog $log) {
            $log->chat_session_id ??= $log->loggable?->chat_session_id;
        });
    }

    protected function casts(): array
    {
        return [
            'arguments' => 'array',
            'result' => 'array',
        ];
    }

    // Sumber log: ChatMessage atau BatchPlanItem
    public function loggable(): MorphTo
    {
        return $this->morphTo();
    }

    public function chatSession(): BelongsTo
    {
        return $this->belongsTo(ChatSession::class);
    }
}
