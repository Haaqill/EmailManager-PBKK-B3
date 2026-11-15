<?php

namespace App\Services\Llm;

final readonly class LlmResult
{
    public function __construct(
        public string $content,
        public string $model,
        public string $provider,
        public ?int $promptTokens,
        public ?int $completionTokens,
        public int $latencyMs,
    ) {
    }
}
