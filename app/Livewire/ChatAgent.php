<?php

namespace App\Livewire;

use App\Services\ChatAi\ChatConversation;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmUnavailableException;
use Illuminate\Contracts\View\View;
use Livewire\Attributes\Locked;
use Livewire\Component;

/**
 * Chat dengan LLM lewat wire:stream. Pemanggilan LLM (termasuk fallback
 * Senopati -> Ollama) ada di LlmClient; penyimpanan riwayat di ChatConversation,
 * sama dengan endpoint /api/chat-ai.
 */
class ChatAgent extends Component
{
    /** @var list<array{role: string, content: string}> */
    public array $messages = [];

    public string $prompt = '';

    #[Locked]
    public ?int $sessionId = null;

    #[Locked]
    public ?string $modelUsed = null;

    public ?string $errorMessage = null;

    public function sendMessage(LlmClient $llm, ChatConversation $conversation): void
    {
        $this->validate(
            ['prompt' => 'required|string|max:1000'],
            [
                'prompt.required' => 'Prompt wajib diisi.',
                'prompt.max' => 'Prompt maksimal 1000 karakter.',
            ],
        );

        $user = auth()->user();
        $prompt = $this->prompt;
        $session = $conversation->findSession($user, $this->sessionId);

        $this->errorMessage = null;
        $this->messages[] = ['role' => 'user', 'content' => $prompt];
        $this->prompt = '';

        try {
            $stream = $llm->stream($conversation->buildMessages($session, $prompt));

            $onReasoning = function (bool $thinking): void {
                $this->stream(
                    content: $thinking ? 'Sedang berpikir...' : '',
                    replace: true,
                    name: 'thinkingIndicator',
                );
            };
            foreach ($stream->deltas($onReasoning) as $chunk) {
                $this->stream(content: $chunk, name: 'streamedReply');
            }

            $result = $stream->result();
        } catch (LlmUnavailableException) {
            $this->errorMessage = 'Layanan LLM sedang tidak tersedia. Coba lagi nanti.';

            return;
        }

        $reply = $conversation->store($user, $session, $prompt, $result);
        $this->sessionId = $reply->chat_session_id;
        $this->modelUsed = $result->model;
        $this->messages[] = ['role' => 'assistant', 'content' => $result->content];
    }

    public function newChat(): void
    {
        $this->reset(['messages', 'prompt', 'sessionId', 'modelUsed', 'errorMessage']);
    }

    public function render(): View
    {
        return view('livewire.chat-agent');
    }
}
