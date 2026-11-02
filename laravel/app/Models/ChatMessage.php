<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\MorphMany;

class ChatMessage extends Model
{
    use HasFactory;

    protected $fillable = [
        'chat_session_id',
        'role',
        'content',
        'tool_call_id',
    ];

    protected static function booted(): void
    {
        // Kolom polymorphic tidak punya FK, jadi log ikut dihapus di level aplikasi
        // saat pesan dihapus satu per satu lewat Eloquent.
        static::deleting(function (ChatMessage $message) {
            $message->toolLogs()->delete();
        });
    }

    // ChatMessage belongsTo ChatSession (foreign key: chat_session_id)
    public function chatSession(): BelongsTo
    {
        return $this->belongsTo(ChatSession::class);
    }

    // ChatMessage memiliki banyak ToolExecutionLog (polymorphic, prefix 'loggable')
    public function toolLogs(): MorphMany
    {
        return $this->morphMany(ToolExecutionLog::class, 'loggable')->orderBy('id');
    }
}
