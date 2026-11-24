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

        $cutoff = now()->subDays($days);
        $batchIds = Batch::query()
            ->where('status', BatchStatus::AwaitingReview)
            ->whereNull('pending_operation')
            ->where(fn ($query) => $query->whereNull('agent_error')->orWhere('agent_error->code', '!=', 'operation_outcome_unknown'))
            ->where('updated_at', '<', $cutoff)
            ->pluck('id');

        if ($batchIds->isEmpty()) {
            $this->info('Tidak ada batch yang kedaluwarsa.');

            return self::SUCCESS;
        }

        $pruned = 0;
        foreach ($batchIds as $batchId) {
            $expired = Batch::operationLock($batchId)->get(fn () => DB::transaction(function () use ($batchId, $cutoff): bool {
                $updated = Batch::query()->whereKey($batchId)
                    ->where('status', BatchStatus::AwaitingReview)
                    ->whereNull('pending_operation')
                    ->where(fn ($query) => $query->whereNull('agent_error')->orWhere('agent_error->code', '!=', 'operation_outcome_unknown'))
                    ->where('updated_at', '<', $cutoff)
                    ->update(['status' => BatchStatus::Expired, 'finished_at' => now(), 'agent_error' => null]);
                if ($updated === 0) {
                    return false;
                }

                BatchPlanItem::query()->where('batch_id', $batchId)
                    ->update(array_fill_keys(BatchPlanItem::TRANSIENT_COLUMNS, null));

                return true;
            }));
            $pruned += (int) $expired;
        }

        // TODO: setelah AgentClient ada, batalkan juga batch ini di agen
        // (agen masih memegang state dan pii_map batch sampai dibatalkan).

        $this->info("{$pruned} batch ditandai expired dan data review sementaranya dikosongkan.");

        return self::SUCCESS;
    }
}
