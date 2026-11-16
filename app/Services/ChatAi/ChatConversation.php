<?php

namespace App\Services\ChatAi;

use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\User;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmResult;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

/**
 * Logika bersama POST /api/chat-ai dan /api/chat-ai/stream: sesi milik user,
 * susunan pesan untuk LLM, dan penyimpanan pasangan pesan setelah LLM berhasil.
 */
class ChatConversation
{
    private const HISTORY_LIMIT = 10;

    /**
     * Sesi milik user; sesi orang lain atau yang tidak ada -> 404.
     */
    public function findSession(User $user, ?int $sessionId): ?ChatSession
    {
        return $sessionId === null ? null : $user->chatSessions()->findOrFail($sessionId);
    }

    /**
     * @return list<array{role: string, content: string}>
     */
    public function buildMessages(?ChatSession $session, string $prompt): array
    {
        $history = $session === null ? [] : $session->messages()
            ->reorder('id', 'desc')
            ->whereIn('role', ['user', 'assistant'])
            ->limit(self::HISTORY_LIMIT)
            ->get(['role', 'content'])
            ->reverse()
            ->map(fn (ChatMessage $message) => ['role' => $message->role, 'content' => $message->content])
            ->values()
            ->all();

        return [
            ['role' => 'system', 'content' => LlmClient::SYSTEM_PROMPT],
            ...$history,
            ['role' => 'user', 'content' => $prompt],
        ];
    }

    /**
     * Simpan pesan user dan jawaban assistant dalam satu transaksi.
     */
    public function store(User $user, ?ChatSession $session, string $prompt, LlmResult $result): ChatMessage
    {
        return DB::transaction(function () use ($user, $session, $prompt, $result) {
            $session ??= $user->chatSessions()->create([
                'title' => Str::limit($prompt, 60, ''),
                'mode' => 'chat',
                'status' => 'active',
            ]);

            $session->messages()->create(['role' => 'user', 'content' => $prompt]);

            $reply = $session->messages()->create([
                'role' => 'assistant',
                'content' => $result->content,
                'model' => $result->model,
                'prompt_tokens' => $result->promptTokens,
                'completion_tokens' => $result->completionTokens,
                'latency_ms' => $result->latencyMs,
            ]);
            $session->touch();

            return $reply;
        });
    }
}
