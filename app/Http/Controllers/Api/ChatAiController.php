<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\ChatAiRequest;
use App\Http\Resources\ChatAiResource;
use App\Services\ChatAi\ChatConversation;
use App\Services\Llm\LlmClient;
use App\Services\Llm\LlmUnavailableException;
use Illuminate\Http\JsonResponse;

class ChatAiController extends Controller
{
    public function __invoke(
        ChatAiRequest $request,
        LlmClient $llm,
        ChatConversation $conversation,
    ): ChatAiResource|JsonResponse {
        $user = $request->user();
        $prompt = $request->validated('prompt');
        $session = $conversation->findSession($user, $request->validated('session_id'));

        try {
            $result = $llm->chat($conversation->buildMessages($session, $prompt));
        } catch (LlmUnavailableException) {
            return self::unavailable();
        }

        $reply = $conversation->store($user, $session, $prompt, $result);

        return new ChatAiResource($reply, $prompt);
    }

    public static function unavailable(): JsonResponse
    {
        return response()->json([
            'status' => 'error',
            'message' => 'Layanan LLM sedang tidak tersedia.',
        ], 503);
    }
}
