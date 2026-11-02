<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('chat_sessions', function (Blueprint $table) {
            $table->id();
            // User (Breeze) memiliki banyak ChatSession
            $table->foreignId('user_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            $table->string('title');
            // chat = perintah bebas (loop ReAct), batch = workflow triase LangGraph
            $table->enum('mode', ['chat', 'batch'])->default('chat');
            $table->enum('status', ['active', 'awaiting_review', 'completed', 'failed'])
                ->default('active');
            // thread_id LangGraph di service Python, dipakai untuk resume setelah review
            $table->string('agent_thread_id')->nullable()->unique();
            $table->timestamps();

            $table->index(['user_id', 'updated_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('chat_sessions');
    }
};
