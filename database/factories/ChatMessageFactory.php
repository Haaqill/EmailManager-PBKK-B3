<?php

namespace Database\Factories;

use App\Models\ChatMessage;
use App\Models\ChatSession;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends Factory<ChatMessage>
 */
class ChatMessageFactory extends Factory
{
    protected $model = ChatMessage::class;

    public function definition(): array
    {
        return [
            'chat_session_id' => ChatSession::factory(),
            'role' => fake()->randomElement(['user', 'assistant', 'tool', 'system']),
            'content' => fake()->randomElement([
                'Email dari <PERSON_1> (<EMAIL_1>) membahas revisi laporan.',
                'Terdapat pengumuman dari <PERSON_2> mengenai jadwal ujian.',
                'Saya sudah menyiapkan ringkasan email prioritas tinggi.',
                'Thread ini berisi permintaan revisi pada dokumen tugas.',
                'Ada notifikasi terkait pengumpulan tugas minggu depan.',
            ]),
            'tool_call_id' => fake()->optional()->uuid(),
        ];
    }

    public function assistant(): static
    {
        return $this->state(fn (array $attributes) => [
            'role' => 'assistant',
        ]);
    }
}
