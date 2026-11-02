<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('chat_messages', function (Blueprint $table) {
            $table->id();
            // ChatSession memiliki banyak ChatMessage
            $table->foreignId('chat_session_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            $table->enum('role', ['user', 'assistant', 'tool', 'system']);
            // Hanya konten yang SUDAH diredaksi service Python (<PERSON_1>, <EMAIL_1>, ...).
            // Tabel pemetaan placeholder tidak pernah disimpan di database.
            $table->longText('content');
            // Diisi untuk pesan role=tool, mengacu ke tool_call_id dari LLM
            $table->string('tool_call_id')->nullable();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('chat_messages');
    }
};
