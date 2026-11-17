<?php

namespace App\Models;

use App\Enums\PlanAction;
use App\Enums\PlanCategory;
use App\Enums\PlanDecision;
use App\Enums\PlanPriority;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\MorphMany;

/**
 * Kolom kekal: item_id, thread_id, subject, from_name, category, priority, action,
 * decision, result_status, applied. Kolom SEMENTARA: review_data dan
 * edited_draft_body (dikosongkan saat batch berakhir).
 *
 * chat_session_id, gmail_thread_id, draft_body, dan reason adalah kolom skema lama;
 * baris dari kontrak agen (batch_id terisi) tidak mengisinya.
 */
class BatchPlanItem extends Model
{
    use HasFactory;

    /** Kolom yang wajib null setelah batch berakhir. */
    public const TRANSIENT_COLUMNS = ['review_data', 'edited_draft_body'];

    protected $fillable = [
        'batch_id',
        'item_id',
        'thread_id',
        'from_name',
        'result_status',
        'applied',
        'review_data',
        'edited_draft_body',
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

    protected function casts(): array
    {
        return [
            'category' => PlanCategory::class,
            'priority' => PlanPriority::class,
            'action' => PlanAction::class,
            'decision' => PlanDecision::class,
            'applied' => 'array',
            'review_data' => 'array',
        ];
    }

    protected static function booted(): void
    {
        static::deleting(function (BatchPlanItem $item) {
            $item->toolLogs()->delete();
        });
    }

    public function batch(): BelongsTo
    {
        return $this->belongsTo(Batch::class);
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
