<?php

namespace App\Services\Llm;

use Generator;
use GuzzleHttp\Psr7\Utils;
use Psr\Http\Message\StreamInterface;
use RuntimeException;

/**
 * Pembaca stream SSE chat completions OpenAI-compatible.
 *
 * deltas() mengeluarkan potongan teks satu per satu. Setelah stream habis,
 * result() mengembalikan jawaban lengkap beserta model dan usage (bila
 * provider mengirimkannya lewat stream_options.include_usage).
 */
class LlmStream
{
    private string $content = '';

    private ?string $model = null;

    private ?int $promptTokens = null;

    private ?int $completionTokens = null;

    private bool $finished = false;

    public function __construct(
        private readonly StreamInterface $body,
        public readonly string $provider,
        private readonly string $configModel,
        private readonly int|float $startedAt,
    ) {
    }

    /**
     * @return Generator<int, string>
     *
     * @throws LlmUnavailableException bila stream terputus atau tanpa jawaban
     */
    public function deltas(): Generator
    {
        try {
            while (! $this->body->eof()) {
                $line = trim(Utils::readLine($this->body));
                if (! str_starts_with($line, 'data:')) {
                    continue;
                }

                $data = trim(substr($line, 5));
                if ($data === '[DONE]') {
                    break;
                }

                $chunk = json_decode($data, true);
                if (! is_array($chunk)) {
                    continue;
                }

                $this->absorbMetadata($chunk);

                $delta = $chunk['choices'][0]['delta']['content'] ?? null;
                if (is_string($delta) && $delta !== '') {
                    $this->content .= $delta;

                    yield $delta;
                }
            }
        } catch (RuntimeException $e) {
            throw new LlmUnavailableException('Stream LLM terputus.', previous: $e);
        }

        if (trim($this->content) === '') {
            throw new LlmUnavailableException('Stream LLM selesai tanpa jawaban.');
        }

        $this->finished = true;
    }

    public function result(): LlmResult
    {
        if (! $this->finished) {
            throw new LlmUnavailableException('Stream LLM belum selesai.');
        }

        return new LlmResult(
            content: $this->content,
            model: $this->model ?? $this->configModel,
            provider: $this->provider,
            promptTokens: $this->promptTokens,
            completionTokens: $this->completionTokens,
            latencyMs: (int) round((hrtime(true) - $this->startedAt) / 1_000_000),
        );
    }

    /**
     * @param  array<string, mixed>  $chunk
     */
    private function absorbMetadata(array $chunk): void
    {
        if (is_string($chunk['model'] ?? null) && $chunk['model'] !== '') {
            $this->model = $chunk['model'];
        }

        $usage = $chunk['usage'] ?? null;
        if (is_array($usage)) {
            $this->promptTokens = is_int($usage['prompt_tokens'] ?? null) ? $usage['prompt_tokens'] : null;
            $this->completionTokens = is_int($usage['completion_tokens'] ?? null) ? $usage['completion_tokens'] : null;
        }
    }
}
