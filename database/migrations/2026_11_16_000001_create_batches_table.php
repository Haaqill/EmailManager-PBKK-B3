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
        Schema::create('batches', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')
                ->index()
                ->constrained()
                ->onDelete('cascade');
            $table->string('agent_batch_id')->unique();
            $table->enum('status', [
                'queued', 'scanning', 'classifying', 'drafting', 'awaiting_review',
                'executing', 'done', 'failed', 'cancelled', 'expired',
            ]);
            $table->unsignedInteger('plan_version')->default(1);
            $table->json('filters')->nullable();
            // Hanya angka ringkasan dari report.summary; tidak ada teks email.
            $table->json('summary')->nullable();
            $table->timestamp('finished_at')->nullable();
            $table->timestamps();

            $table->index(['status', 'updated_at']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('batches');
    }
};
