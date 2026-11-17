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
 * Logika bersama POST /api/chat-ai, /api/chat-ai/stream, dan komponen Livewire
 * ChatAgent: sesi milik user, susunan pesan untuk LLM, dan penyimpanan pesan
 * beserta model/token/latensi.
 *
 * API memakai store() (pesan user dan jawaban disimpan bersama setelah LLM
 * berhasil). Halaman chat memakai startTurn() lalu storeReply(), supaya pesan
 * user tetap tersimpan bila LLM gagal dan bisa dicoba lagi.
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
     * Pesan untuk LLM: riwayat sesi lalu prompt baru (belum tersimpan).
     *
     * @return list<array{role: string, content: string}>
     */
    public function buildMessages(?ChatSession $session, string $prompt): array
    {
        return [
            ['role' => 'system', 'content' => LlmClient::SYSTEM_PROMPT],
            ...($session === null ? [] : $this->history($session)),
            ['role' => 'user', 'content' => $prompt],
        ];
    }

    /**
     * Pesan untuk LLM bila pesan user terakhir sudah tersimpan (lihat startTurn()).
     *
     * @return list<array{role: string, content: string}>
     */
    public function buildMessagesFromHistory(ChatSession $session): array
    {
        return [
            ['role' => 'system', 'content' => LlmClient::SYSTEM_PROMPT],
            ...$this->history($session),
        ];
    }

    /**
     * Pesan user terakhir yang belum dijawab, atau null.
     */
    public function pendingUserMessage(ChatSession $session): ?ChatMessage
    {
        $last = $session->messages()
            ->reorder('id', 'desc')
            ->whereIn('role', ['user', 'assistant'])
            ->first();

        return $last?->role === 'user' ? $last : null;
    }

    /**
     * Simpan pesan user dan jawaban assistant dalam satu transaksi.
     */
    public function store(User $user, ?ChatSession $session, string $prompt, LlmResult $result): ChatMessage
    {
        return DB::transaction(function () use ($user, $session, $prompt, $result) {
            $session = $this->startTurn($user, $session, $prompt);

            return $this->storeReply($session, $result);
        });
    }

    /**
     * Simpan pesan user; sesi baru dibuat bila belum ada (judul dari prompt).
     */
    public function startTurn(User $user, ?ChatSession $session, string $prompt): ChatSession
    {
        return DB::transaction(function () use ($user, $session, $prompt) {
            $session ??= $user->chatSessions()->create([
                'title' => Str::limit($prompt, 60, ''),
                'mode' => 'chat',
                'status' => 'active',
            ]);

            $session->messages()->create(['role' => 'user', 'content' => $prompt]);
            $session->touch();

            return $session;
        });
    }

    /**
     * Simpan jawaban assistant beserta model, token, dan latensi.
     */
    public function storeReply(ChatSession $session, LlmResult $result): ChatMessage
    {
        return DB::transaction(function () use ($session, $result) {
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

    /**
     * @return list<array{role: string, content: string}>
     */
    private function history(ChatSession $session): array
    {
        return $session->messages()
            ->reorder('id', 'desc')
            ->whereIn('role', ['user', 'assistant'])
            ->limit(self::HISTORY_LIMIT)
            ->get(['role', 'content'])
            ->reverse()
            ->map(fn (ChatMessage $message) => ['role' => $message->role, 'content' => $message->content])
            ->values()
            ->all();
    }
}
