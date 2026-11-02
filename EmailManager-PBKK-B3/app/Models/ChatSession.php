<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class ChatSession extends Model
{
    use HasFactory;

    protected $fillable = [
        'title',
        'mode',
        'status',
        'agent_thread_id',
    ];

    // ChatSession belongsTo User
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    // ChatSession memiliki banyak ChatMessage (urut sesuai percakapan)
    public function messages(): HasMany
    {
        return $this->hasMany(ChatMessage::class)->orderBy('id');
    }

    // Item rencana batch (hanya terisi untuk mode = batch)
    public function planItems(): HasMany
    {
        return $this->hasMany(BatchPlanItem::class)->orderBy('id');
    }

    // Semua log tool dalam sesi ini, apa pun sumbernya
    public function toolLogs(): HasMany
    {
        return $this->hasMany(ToolExecutionLog::class);
    }
}
