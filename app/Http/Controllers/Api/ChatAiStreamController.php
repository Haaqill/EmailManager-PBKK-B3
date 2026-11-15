<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\ChatAiRequest;
use App\Http\Resources\ChatAiResource;
use App\Services\ChatAi\ChatConversation;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmUnavailableException;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\StreamedResponse;

/**
 * POST /api/chat-ai/stream: jawaban LLM dikirim bertahap sebagai Server-Sent Events.
 *
 * Event: `delta` {"content": "..."}, lalu `done` (bentuk sama dengan respons
 * POST /api/chat-ai), atau `error` bila stream terputus. Pesan disimpan hanya
 * setelah stream selesai.
 */
class ChatAiStreamController extends Controller
{
    public function __invoke(
        ChatAiRequest $request,
        LlmClient $llm,
        ChatConversation $conversation,
    ): StreamedResponse|JsonResponse {
        $user = $request->user();
        $prompt = $request->validated('prompt');
        $session = $conversation->findSession($user, $request->validated('session_id'));

        try {
            $stream = $llm->stream($conversation->buildMessages($session, $prompt));
        } catch (LlmUnavailableException) {
            return ChatAiController::unavailable();
        }

        return response()->stream(function () use ($stream, $conversation, $user, $session, $prompt, $request) {
            try {
                foreach ($stream->deltas() as $delta) {
                    self::send('delta', ['content' => $delta]);
                }
            } catch (LlmUnavailableException) {
                self::send('error', ['status' => 'error', 'message' => 'Layanan LLM terputus saat menjawab.']);

                return;
            }

            $reply = $conversation->store($user, $session, $prompt, $stream->result());
            self::send('done', (new ChatAiResource($reply, $prompt))->toArray($request));
        }, 200, [
            'Content-Type' => 'text/event-stream',
            'Cache-Control' => 'no-cache',
            'X-Accel-Buffering' => 'no',
        ]);
    }

    /**
     * @param  array<string, mixed>  $data
     */
    private static function send(string $event, array $data): void
    {
        echo "event: {$event}\n";
        echo 'data: ' . json_encode($data, JSON_UNESCAPED_UNICODE) . "\n\n";

        if (ob_get_level() > 0) {
            ob_flush();
        }
        flush();
    }
}
