<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Kontrak Laravel <-> Python tahap 1 (docs/contract-laravel-python.md).
 *
 * Tabel lama (chat_session_id, gmail_thread_id, draft_body, reason) dipertahankan
 * agar riwayat dan relasi lama tetap jalan; kolom lama dijadikan nullable dan
 * tidak diisi oleh baris baru. Penghapusan kolom lama dilakukan di PR terpisah.
 */
return new class () extends Migration {
    /** Nilai decision lama -> baru. 'edited' berarti disetujui dengan perubahan. */
    private const DECISION_UP = ['approved' => 'approve', 'edited' => 'approve', 'rejected' => 'reject'];

    private const DECISION_DOWN = ['approve' => 'approved', 'reject' => 'rejected'];

    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->foreignId('batch_id')
                ->nullable()
                ->after('id')
                ->constrained()
                ->onDelete('cascade');
            $table->string('item_id')->nullable()->after('batch_id');
            $table->string('thread_id')->nullable()->after('item_id');
            $table->string('from_name')->nullable()->after('subject');
            $table->string('result_status', 32)->nullable();
            // Hanya nama label, flag arsip, dan draft_id.
            $table->json('applied')->nullable();

            // SEMENTARA: wajib dikosongkan (null) saat batch berakhir
            // (done/failed/cancelled/expired). Lihat BatchSyncService dan
            // command batches:prune-review-data.
            $table->json('review_data')->nullable();
            $table->text('edited_draft_body')->nullable();

            $table->unique(['batch_id', 'item_id']);
        });

        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->foreignId('chat_session_id')->nullable()->change();
            $table->string('gmail_thread_id')->nullable()->change();
            $table->string('subject', 255)->nullable()->change();
            $table->text('reason')->nullable()->change();
            // Sementara string agar nilai lama bisa dipetakan sebelum enum baru dipasang.
            $table->string('decision', 16)->default('pending')->change();
        });

        foreach (self::DECISION_UP as $old => $new) {
            DB::table('batch_plan_items')->where('decision', $old)->update(['decision' => $new]);
        }

        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->enum('decision', ['pending', 'approve', 'reject'])->default('pending')->change();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->string('decision', 16)->default('pending')->change();
        });

        foreach (self::DECISION_DOWN as $new => $old) {
            DB::table('batch_plan_items')->where('decision', $new)->update(['decision' => $old]);
        }

        // Baris baru (tanpa chat_session_id) tidak punya tempat di skema lama.
        DB::table('batch_plan_items')->whereNull('chat_session_id')->delete();

        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->enum('decision', ['pending', 'approved', 'edited', 'rejected'])->default('pending')->change();
            $table->foreignId('chat_session_id')->nullable(false)->change();
            $table->string('gmail_thread_id')->nullable(false)->change();
            $table->string('subject')->nullable(false)->change();
            $table->text('reason')->nullable(false)->change();
        });

        Schema::table('batch_plan_items', function (Blueprint $table) {
            $table->dropUnique(['batch_id', 'item_id']);
            $table->dropConstrainedForeignId('batch_id');
            $table->dropColumn([
                'item_id', 'thread_id', 'from_name', 'result_status', 'applied',
                'review_data', 'edited_draft_body',
            ]);
        });
    }
};
