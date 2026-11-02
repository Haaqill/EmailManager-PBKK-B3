<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('tool_execution_logs', function (Blueprint $table) {
            $table->id();
            // FK nyata ke sesi: menjamin cascade di level database, karena kolom
            // polymorphic (loggable_*) tidak bisa diberi foreign key constraint.
            $table->foreignId('chat_session_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            // Challenge A+: loggable_type + loggable_id (keduanya ter-index).
            // Sumber log: 'chat_message' (loop ReAct) atau 'batch_plan_item' (workflow batch).
            $table->morphs('loggable');
            $table->string('tool_name', 64); // scan_emails, fetch_thread, label_thread, ...
            $table->string('tool_call_id')->nullable();
            $table->json('arguments');
            $table->json('result')->nullable();
            $table->enum('status', ['pending', 'success', 'failed', 'rejected'])->default('pending');
            $table->unsignedInteger('duration_ms')->nullable();
            $table->text('error_message')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('tool_execution_logs');
    }
};
