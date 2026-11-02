<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class () extends Migration {
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('tool_execution_logs', function (Blueprint $table) {
            $table->id();
            $table->foreignId('chat_session_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            $table->morphs('loggable');
            $table->string('tool_name', 64);
            $table->string('tool_call_id')->nullable();
            $table->json('arguments');
            $table->json('result')->nullable();
            $table->enum('status', ['pending', 'success', 'failed', 'rejected'])->default('pending');
            $table->unsignedInteger('duration_ms')->nullable();
            $table->text('error_message')->nullable();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('tool_execution_logs');
    }
};
