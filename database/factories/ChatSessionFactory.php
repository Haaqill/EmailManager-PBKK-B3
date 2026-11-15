<?php

namespace Database\Factories;

use App\Models\ChatSession;
use App\Models\User;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends Factory<ChatSession>
 */
class ChatSessionFactory extends Factory
{
    protected $model = ChatSession::class;

    public function definition(): array
    {
        return [
            'user_id' => User::factory(),
            'title' => fake()->randomElement([
                'Rangkum email belum dibaca',
                'Review email penting hari ini',
                'Siapkan respons untuk thread akademik',
                'Tinjau prioritas surat masuk',
                'Buat ringkasan agenda email',
            ]),
            'mode' => 'chat',
            'status' => 'active',
            'agent_thread_id' => fake()->optional()->uuid(),
        ];
    }

    public function batch(): static
    {
        return $this->state(fn (array $attributes) => [
            'mode' => 'batch',
            'status' => 'awaiting_review',
        ]);
    }
}
