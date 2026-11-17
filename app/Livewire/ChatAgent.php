<?php

namespace App\Livewire;

use App\Http\Requests\ChatAiRequest;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Services\ChatAi\ChatConversation;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmUnavailableException;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Arr;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\RateLimiter;
use Livewire\Attributes\Computed;
use Livewire\Attributes\Locked;
use Livewire\Component;

/**
 * Chat dengan LLM lewat wire:stream. Pemanggilan LLM (termasuk fallback
 * Senopati -> Ollama) ada di LlmClient; penyimpanan pesan dan metadata
 * (model/token/latensi) di ChatConversation, jalur yang sama dengan /api/chat-ai.
 *
 * Pesan user disimpan sebelum LLM dipanggil, supaya tetap ada bila LLM gagal
 * dan bisa diproses ulang lewat retry() tanpa digandakan. Sesi baru dibuat
 * saat pesan pertama dikirim.
 */
class ChatAgent extends Component
{
    public const MESSAGE_LIMIT = 100;

    public const RATE_LIMIT = 10;

    public const RATE_WINDOW_SECONDS = 60;

    public const ERROR_UNAVAILABLE = 'Layanan AI sedang tidak tersedia. Pesan Anda sudah tersimpan; silakan coba lagi.';

    #[Locked]
    public ?int $sessionId = null;

    public string $prompt = '';

    public ?string $errorMessage = null;

    public function mount(?int $sessionId = null): void
    {
        if ($sessionId !== null) {
            $this->authorize('view', ChatSession::query()->findOrFail($sessionId));
            $this->sessionId = $sessionId;
        }
    }

    public function sendMessage(LlmClient $llm, ChatConversation $conversation): void
    {
        $session = $this->authorizedSession();

        $this->prompt = trim($this->prompt);
        $request = new ChatAiRequest();
        $this->validate(
            ['prompt' => $request->rules()['prompt']],
            Arr::only($request->messages(), ['prompt.required', 'prompt.string', 'prompt.max']),
        );

        if (! $this->hitRateLimit()) {
            return;
        }

        $isNew = $session === null;
        $session = $conversation->startTurn(auth()->user(), $session, $this->prompt);
        $this->sessionId = $session->id;
        $this->prompt = '';

        if ($isNew) {
            $this->js('history.replaceState(null, "", ' . json_encode(route('chat.show', $session)) . ')');
        }

        $this->respond($llm, $conversation, $session);
    }

    /**
     * Proses ulang pesan user terakhir yang belum dijawab (tidak membuat pesan baru).
     */
    public function retry(LlmClient $llm, ChatConversation $conversation): void
    {
        $session = $this->authorizedSession();
        if ($session === null || $conversation->pendingUserMessage($session) === null) {
            return;
        }

        if (! $this->hitRateLimit()) {
            return;
        }

        $this->respond($llm, $conversation, $session);
    }

    /**
     * @return Collection<int, ChatMessage>
     */
    #[Computed]
    public function messages(): Collection
    {
        if ($this->sessionId === null) {
            return collect();
        }

        return ChatMessage::query()
            ->where('chat_session_id', $this->sessionId)
            ->whereIn('role', ['user', 'assistant'])
            ->orderByDesc('id')
            ->limit(self::MESSAGE_LIMIT)
            ->get(['id', 'role', 'content', 'model', 'latency_ms'])
            ->reverse()
            ->values();
    }

    public function render(): View
    {
        $messages = $this->messages;

        return view('livewire.chat-agent', [
            'messages' => $messages,
            'canRetry' => $messages->last()?->role === 'user',
        ]);
    }

    private function respond(LlmClient $llm, ChatConversation $conversation, ChatSession $session): void
    {
        $this->errorMessage = null;

        try {
            $stream = $llm->stream($conversation->buildMessagesFromHistory($session));

            // LlmStream hanya memberi tanda mulai/selesai berpikir, bukan teks reasoning.
            $onReasoning = function (bool $thinking): void {
                $this->stream(
                    content: $thinking ? 'Sedang berpikir…' : '',
                    replace: true,
                    name: 'thinkingIndicator',
                );
            };
            foreach ($stream->deltas($onReasoning) as $chunk) {
                // wire:stream menyisipkan HTML; keluaran model wajib di-escape.
                $this->stream(content: e($chunk), name: 'streamedReply');
            }

            $result = $stream->result();
        } catch (LlmUnavailableException) {
            $this->errorMessage = self::ERROR_UNAVAILABLE;
            $this->dispatch('chat-session-updated', id: $session->id);

            return;
        }

        $conversation->storeReply($session, $result);
        unset($this->messages);
        $this->dispatch('chat-session-updated', id: $session->id);
    }

    private function authorizedSession(): ?ChatSession
    {
        if ($this->sessionId === null) {
            return null;
        }

        $session = ChatSession::query()->findOrFail($this->sessionId);
        $this->authorize('view', $session);

        return $session;
    }

    private function hitRateLimit(): bool
    {
        $key = 'chat-agent:' . auth()->id();
        if (RateLimiter::tooManyAttempts($key, self::RATE_LIMIT)) {
            $this->addError('prompt', 'Terlalu banyak pesan. Coba lagi dalam ' . RateLimiter::availableIn($key) . ' detik.');

            return false;
        }
        RateLimiter::hit($key, self::RATE_WINDOW_SECONDS);

        return true;
    }
}
