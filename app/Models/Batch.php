<?php

namespace App\Models;

use App\Enums\BatchStatus;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Batch extends Model
{
    protected $fillable = [
        'user_id',
        'agent_batch_id',
        'status',
        'plan_version',
        'filters',
        'summary',
        'finished_at',
    ];

    protected function casts(): array
    {
        return [
            'status' => BatchStatus::class,
            'plan_version' => 'integer',
            'filters' => 'array',
            'summary' => 'array',
            'finished_at' => 'datetime',
        ];
    }

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function items(): HasMany
    {
        return $this->hasMany(BatchPlanItem::class)->orderBy('item_id');
    }
}
