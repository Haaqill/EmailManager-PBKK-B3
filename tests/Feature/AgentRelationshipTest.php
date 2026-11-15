<?php

namespace Tests\Feature;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\ToolExecutionLog;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class AgentRelationshipTest extends TestCase
{
    use RefreshDatabase;

    public function test_user_session_message_and_tool_log_relationships_use_morph_aliases(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create();
        $message = ChatMessage::factory()->for($session)->create();
        $messageLog = ToolExecutionLog::factory()->forLoggable($message)->create();
        $item = BatchPlanItem::factory()->for($session)->create();
        $itemLog = ToolExecutionLog::factory()->forLoggable($item)->create();
        $loadedMessageLog = ToolExecutionLog::with('loggable')->findOrFail($messageLog->id);
        $loadedItemLog = ToolExecutionLog::with('loggable')->findOrFail($itemLog->id);

        $this->assertTrue($user->chatSessions()->whereKey($session->id)->exists());
        $this->assertSame($user->id, $session->user()->firstOrFail()->id);
        $this->assertSame($session->id, $message->chatSession()->firstOrFail()->id);
        $this->assertSame($message->id, $loadedMessageLog->loggable->id);
        $this->assertSame($item->id, $loadedItemLog->loggable->id);
        $this->assertSame('chat_message', $messageLog->loggable_type);
        $this->assertSame('batch_plan_item', $itemLog->loggable_type);
        $this->assertIsArray($messageLog->arguments);
    }
}
