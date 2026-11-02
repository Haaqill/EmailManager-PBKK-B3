<?php

namespace Database\Factories;

use App\Models\BatchPlanItem;
use App\Models\ChatSession;
use Illuminate\Database\Eloquent\Factories\Factory;

/**
 * @extends Factory<BatchPlanItem>
 */
class BatchPlanItemFactory extends Factory
{
    protected $model = BatchPlanItem::class;

    public function definition(): array
    {
        $category = fake()->randomElement(['akademik', 'tugas', 'pengumuman', 'pribadi', 'promosi', 'spam']);
        $priority = in_array($category, ['promosi', 'spam'], true) ? 'nanti' : fake()->randomElement(['mendesak', 'normal', 'nanti']);

        return [
            'chat_session_id' => ChatSession::factory(),
            'gmail_thread_id' => fake()->uuid(),
            'subject' => fake()->sentence(4),
            'category' => $category,
            'priority' => $priority,
            'action' => fake()->randomElement(['label_only', 'archive', 'draft_reply', 'trash']),
            'draft_body' => fake()->optional()->paragraph(),
            'reason' => fake()->sentence(),
            'decision' => 'pending',
        ];
    }
}
