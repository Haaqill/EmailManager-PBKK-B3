<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\MorphMany;

class BatchPlanItem extends Model
{
    use HasFactory;

    protected $fillable = [
        'chat_session_id',
        'gmail_thread_id',
        'subject',
        'category',
        'priority',
        'action',
        'draft_body',
        'reason',
        'decision',
    ];

    protected static function booted(): void
    {
        static::deleting(function (BatchPlanItem $item) {
            $item->toolLogs()->delete();
        });
    }

    public function chatSession(): BelongsTo
    {
        return $this->belongsTo(ChatSession::class);
    }

    public function toolLogs(): MorphMany
    {
        return $this->morphMany(ToolExecutionLog::class, 'loggable')->orderBy('id');
    }
}
