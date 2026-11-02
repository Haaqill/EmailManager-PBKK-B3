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
        Schema::create('batch_plan_items', function (Blueprint $table) {
            $table->id();
            $table->foreignId('chat_session_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            $table->string('gmail_thread_id');
            $table->string('subject');
            $table->enum('category', ['akademik', 'tugas', 'pengumuman', 'pribadi', 'promosi', 'spam']);
            $table->enum('priority', ['mendesak', 'normal', 'nanti']);
            $table->enum('action', ['label_only', 'archive', 'draft_reply', 'trash']);
            $table->text('draft_body')->nullable();
            $table->text('reason');
            $table->enum('decision', ['pending', 'approved', 'edited', 'rejected'])->default('pending');
            $table->timestamps();

            $table->unique(['chat_session_id', 'gmail_thread_id']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('batch_plan_items');
    }
};
