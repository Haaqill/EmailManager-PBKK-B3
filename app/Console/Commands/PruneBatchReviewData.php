<?php

namespace App\Console\Commands;

use App\Enums\BatchStatus;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class PruneBatchReviewData extends Command
{
    protected $signature = 'batches:prune-review-data {--days=7 : Umur minimum (hari) sejak updated_at}';

    protected $description = 'Kosongkan data review sementara pada batch awaiting_review yang terbengkalai dan tandai expired';

    public function handle(): int
    {
        $days = filter_var($this->option('days'), FILTER_VALIDATE_INT);
        if ($days === false || $days < 0) {
            $this->error('--days harus bilangan bulat >= 0.');

            return self::INVALID;
        }

        $batchIds = Batch::query()
            ->where('status', BatchStatus::AwaitingReview)
            ->where('updated_at', '<', now()->subDays($days))
            ->pluck('id');

        if ($batchIds->isEmpty()) {
            $this->info('Tidak ada batch yang kedaluwarsa.');

            return self::SUCCESS;
        }

        DB::transaction(function () use ($batchIds) {
            BatchPlanItem::query()
                ->whereIn('batch_id', $batchIds)
                ->update(array_fill_keys(BatchPlanItem::TRANSIENT_COLUMNS, null));

            Batch::query()->whereIn('id', $batchIds)->update([
                'status' => BatchStatus::Expired,
                'finished_at' => now(),
                'updated_at' => now(),
            ]);
        });

        // TODO: setelah AgentClient ada, batalkan juga batch ini di agen
        // (agen masih memegang state dan pii_map batch sampai dibatalkan).

        $this->info("{$batchIds->count()} batch ditandai expired dan data review sementaranya dikosongkan.");

        return self::SUCCESS;
    }
}
