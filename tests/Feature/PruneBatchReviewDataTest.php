<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanDecision;
use App\Models\Batch;
use App\Models\BatchPlanItem;
use App\Models\User;
use App\Services\Agent\BatchSyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class PruneBatchReviewDataTest extends TestCase
{
    use RefreshDatabase;

    private function syncedBatch(string $agentBatchId, int $ageDays): Batch
    {
        $payload = json_decode(
            file_get_contents(base_path('tests/Fixtures/agent/batch_awaiting_review.json')),
            true,
            flags: JSON_THROW_ON_ERROR,
        );
        $payload['batch_id'] = $agentBatchId;

        $batch = (new BatchSyncService())->sync(User::factory()->create()->id, $payload);
        BatchPlanItem::query()->where('batch_id', $batch->id)->update(['edited_draft_body' => 'Draft suntingan']);
        Batch::query()->whereKey($batch->id)->update(['updated_at' => now()->subDays($ageDays)]);

        return $batch;
    }

    public function test_prune_clears_transient_data_and_marks_expired(): void
    {
        $stale = $this->syncedBatch('b_lama', ageDays: 8);
        $fresh = $this->syncedBatch('b_baru', ageDays: 2);

        $this->artisan('batches:prune-review-data')->assertSuccessful();

        $stale->refresh();
        $this->assertSame(BatchStatus::Expired, $stale->status);
        $this->assertNotNull($stale->finished_at);

        $items = BatchPlanItem::query()->where('batch_id', $stale->id)->orderBy('item_id')->get();
        $this->assertCount(2, $items);
        foreach ($items as $item) {
            $this->assertNull($item->review_data);
            $this->assertNull($item->edited_draft_body);
            $this->assertSame(PlanDecision::Pending, $item->decision);
        }
        $this->assertSame('Konfirmasi jadwal bimbingan', $items[0]->subject);
        $this->assertSame('Dosen Fiktif', $items[0]->from_name);
        $this->assertSame('18c0fiktif01', $items[0]->thread_id);
        $this->assertSame(PlanAction::DraftReply, $items[0]->action);

        $this->assertSame(BatchStatus::AwaitingReview, $fresh->refresh()->status);
        $this->assertNotNull(BatchPlanItem::query()->where('batch_id', $fresh->id)->first()->review_data);
    }

    public function test_days_option_is_respected(): void
    {
        $batch = $this->syncedBatch('b_tiga_hari', ageDays: 3);

        $this->artisan('batches:prune-review-data', ['--days' => 5])->assertSuccessful();
        $this->assertSame(BatchStatus::AwaitingReview, $batch->refresh()->status);

        $this->artisan('batches:prune-review-data', ['--days' => 2])->assertSuccessful();
        $this->assertSame(BatchStatus::Expired, $batch->refresh()->status);
    }

    public function test_only_awaiting_review_batches_are_pruned(): void
    {
        $batch = $this->syncedBatch('b_eksekusi', ageDays: 30);
        Batch::query()->whereKey($batch->id)->update(['status' => BatchStatus::Executing, 'updated_at' => now()->subDays(30)]);

        $this->artisan('batches:prune-review-data')->assertSuccessful();

        $this->assertSame(BatchStatus::Executing, $batch->refresh()->status);
    }

    public function test_invalid_days_option_fails(): void
    {
        $this->artisan('batches:prune-review-data', ['--days' => 'abc'])->assertExitCode(2);
    }
}
