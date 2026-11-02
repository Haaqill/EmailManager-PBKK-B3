<?php

namespace Database\Seeders;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\ToolExecutionLog;
use App\Models\User;
use Illuminate\Database\Seeder;

class AgentDemoSeeder extends Seeder
{
    public function run(): void
    {
        $user = User::firstOrCreate(
            ['email' => 'demo@inbox-manager.test'],
            ['name' => 'Akun Demo', 'password' => 'password'],
        );

        ChatSession::factory()->count(3)->for($user)->create()->each(function (ChatSession $session) {
            foreach (range(1, 3) as $turn) {
                ChatMessage::factory()->for($session)->create(['role' => 'user']);

                $reply = ChatMessage::factory()->assistant()->for($session)->create();

                ToolExecutionLog::factory()
                    ->count(fake()->numberBetween(1, 3))
                    ->forLoggable($reply)
                    ->create();
            }
        });

        $batch = ChatSession::factory()->batch()->for($user)->create();

        ChatMessage::factory()->for($batch)->create([
            'role' => 'user',
            'content' => 'Jalankan triase pagi untuk 10 email terbaru.',
        ]);

        BatchPlanItem::factory()->count(10)->for($batch)->create()->each(function (BatchPlanItem $item) {
            ToolExecutionLog::factory()->forLoggable($item)->create([
                'tool_name' => 'label_thread',
                'arguments' => [
                    'thread_id' => $item->gmail_thread_id,
                    'category' => $item->category,
                    'priority' => $item->priority,
                ],
                'status' => 'pending',
            ]);
        });
    }
}
