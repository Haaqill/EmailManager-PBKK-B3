<?php

namespace Tests\Feature;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\ToolExecutionLog;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class AgentCascadeTest extends TestCase
{
    use RefreshDatabase;

    public function test_deleting_user_cascades_through_sessions_messages_items_and_logs(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create();
        $message = ChatMessage::factory()->for($session)->create();
        $item = BatchPlanItem::factory()->for($session)->create();
        ToolExecutionLog::factory()->forLoggable($message)->create();
        ToolExecutionLog::factory()->forLoggable($item)->create();

        $user->delete();

        $this->assertDatabaseMissing('chat_sessions', ['id' => $session->id]);
        $this->assertDatabaseMissing('chat_messages', ['id' => $message->id]);
        $this->assertDatabaseMissing('batch_plan_items', ['id' => $item->id]);
        $this->assertDatabaseCount('tool_execution_logs', 0);
    }

    public function test_deleting_a_polymorphic_source_removes_its_tool_logs(): void
    {
        $session = ChatSession::factory()->create();
        $message = ChatMessage::factory()->for($session)->create();
        $item = BatchPlanItem::factory()->for($session)->create();
        $messageLog = ToolExecutionLog::factory()->forLoggable($message)->create();
        $itemLog = ToolExecutionLog::factory()->forLoggable($item)->create();

        $message->delete();

        $this->assertDatabaseMissing('tool_execution_logs', ['id' => $messageLog->id]);
        $this->assertDatabaseHas('tool_execution_logs', ['id' => $itemLog->id]);

        $item->delete();

        $this->assertDatabaseMissing('tool_execution_logs', ['id' => $itemLog->id]);
    }
}
