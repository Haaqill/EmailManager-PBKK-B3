<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\ChatAiRequest;
use App\Http\Resources\ChatAiResource;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmUnavailableException;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class ChatAiController extends Controller
{
    private const HISTORY_LIMIT = 10;

    public function __invoke(ChatAiRequest $request, LlmClient $llm): ChatAiResource|JsonResponse
    {
        $prompt = $request->validated('prompt');
        $sessionId = $request->validated('session_id');

        $session = $sessionId !== null
            ? $request->user()->chatSessions()->findOrFail($sessionId)
            : null;

        $history = $session === null ? [] : $session->messages()
            ->reorder('id', 'desc')
            ->whereIn('role', ['user', 'assistant'])
            ->limit(self::HISTORY_LIMIT)
            ->get(['role', 'content'])
            ->reverse()
            ->map(fn ($message) => ['role' => $message->role, 'content' => $message->content])
            ->values()
            ->all();

        $messages = [
            ['role' => 'system', 'content' => LlmClient::SYSTEM_PROMPT],
            ...$history,
            ['role' => 'user', 'content' => $prompt],
        ];

        try {
            $result = $llm->chat($messages);
        } catch (LlmUnavailableException) {
            return response()->json([
                'status' => 'error',
                'message' => 'Layanan LLM sedang tidak tersedia.',
            ], 503);
        }

        $reply = DB::transaction(function () use ($request, $session, $prompt, $result) {
            $session ??= $request->user()->chatSessions()->create([
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

        return new ChatAiResource($reply, $prompt);
    }
}
