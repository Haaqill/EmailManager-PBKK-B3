<?php

namespace App\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * Membungkus pesan assistant (ChatMessage) yang baru disimpan.
 *
 * @property-read \App\Models\ChatMessage $resource
 */
class ChatAiResource extends JsonResource
{
    public static $wrap = null;

    public function __construct($resource, private readonly string $prompt)
    {
        parent::__construct($resource);
    }

    /**
     * @return array<string, mixed>
     */
    public function toArray(Request $request): array
    {
        return [
            'status' => 'success',
            'data' => [
                'session_id' => $this->resource->chat_session_id,
                'model_used' => $this->resource->model,
                'prompt' => $this->prompt,
                'ai_response' => $this->resource->content,
                'timestamp' => $this->resource->created_at?->toIso8601String(),
            ],
        ];
    }

    /**
     * Pesan baru dibuat, tetapi kontrak API memakai 200 (bukan 201 bawaan).
     */
    public function withResponse(Request $request, $response): void
    {
        $response->setStatusCode(200);
    }
}
