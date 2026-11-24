<?php

use App\Enums\BatchStatus;
use App\Jobs\RunBatchOperationJob;
use App\Jobs\SyncBatchStatusJob;
use App\Models\Batch;
use Illuminate\Foundation\DevCommands;
use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Schedule;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

Schedule::call(function (): void {
    Batch::query()
        ->where(fn ($query) => $query->whereIn('status', BatchStatus::POLLABLE)
            ->orWhereNotNull('pending_operation')->orWhere('agent_error->code', 'operation_outcome_unknown'))
        ->select(['id', 'pending_operation'])
        ->eachById(function (Batch $batch): void {
            if ($batch->pending_operation === null) {
                SyncBatchStatusJob::dispatch($batch->id);
            } else {
                RunBatchOperationJob::dispatch($batch->id, $batch->pending_operation['id']);
            }
        });
})->name('batch:queue-operations')->everyTwoSeconds();

Schedule::command('batches:prune-review-data')->hourly();

DevCommands::artisan('queue:work --sleep=1 --timeout=' . Batch::WORKER_TIMEOUT . ' --tries=1', 'queue');
DevCommands::artisan('schedule:work', 'scheduler');
