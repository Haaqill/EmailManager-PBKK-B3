<?php

namespace Database\Factories;

use App\Models\ChatSession;
use App\Models\ToolExecutionLog;
use Illuminate\Database\Eloquent\Factories\Factory;
use Illuminate\Database\Eloquent\Model;

/**
 * @extends Factory<ToolExecutionLog>
 */
class ToolExecutionLogFactory extends Factory
{
    protected $model = ToolExecutionLog::class;

    public function definition(): array
    {
        return [
            'chat_session_id' => ChatSession::factory(),
            'tool_name' => fake()->randomElement(['scan_emails', 'fetch_thread', 'label_thread', 'archive_thread']),
            'tool_call_id' => fake()->optional()->uuid(),
            'arguments' => [
                'thread_id' => fake()->uuid(),
                'action' => 'review',
            ],
            'result' => [
                'status' => 'ok',
            ],
            'status' => fake()->randomElement(['pending', 'success', 'failed', 'rejected']),
            'duration_ms' => fake()->numberBetween(50, 3000),
            'error_message' => null,
        ];
    }

    public function forLoggable(Model $model): static
    {
        return $this->state(fn (array $attributes) => [
            'chat_session_id' => $model->chat_session_id ?? $model->chatSession?->id ?? $model->getAttribute('chat_session_id'),
            'loggable_type' => $model->getMorphClass(),
            'loggable_id' => $model->getKey(),
        ]);
    }
}
