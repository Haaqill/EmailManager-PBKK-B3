<?php

namespace App\Livewire;

use App\Enums\BatchStatus;
use App\Jobs\SyncBatchStatusJob;
use App\Models\Batch;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\InvalidAgentPayload;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\RateLimiter;
use Livewire\Component;

/**
 * Halaman /batch: mulai batch baru dan daftar batch terakhir milik pengguna.
 */
class BatchIndex extends Component
{
    public const LIST_LIMIT = 20;

    public const RATE_LIMIT = 5;

    public const RATE_WINDOW_SECONDS = 60;

    public int $threadCount = 10;

    public ?string $errorMessage = null;

    public function start(AgentClient $agent): void
    {
        $max = (int) config('agent.max_threads', 10);
        $this->validate(
            ['threadCount' => ['required', 'integer', 'min:1', "max:{$max}"]],
            [
                'threadCount.required' => 'Jumlah email wajib diisi.',
                'threadCount.integer' => 'Jumlah email harus berupa angka.',
                'threadCount.min' => 'Jumlah email minimal 1.',
                'threadCount.max' => "Jumlah email maksimal {$max}.",
            ],
        );
        $this->errorMessage = null;

        $userId = (int) auth()->id();
        $key = 'batch-start:' . $userId;
        if (RateLimiter::tooManyAttempts($key, self::RATE_LIMIT)) {
            $this->errorMessage = 'Terlalu sering memulai batch. Coba lagi dalam ' . RateLimiter::availableIn($key) . ' detik.';

            return;
        }

        // Kunci per pengguna: dua klik cepat tidak boleh memulai dua batch.
        $batch = Cache::lock('batch-start-lock:' . $userId, 30)->get(function () use ($agent, $userId, $key) {
            if ($this->activeBatch() !== null) {
                $this->errorMessage = 'Masih ada batch yang berjalan. Selesaikan atau batalkan dulu.';

                return null;
            }
            RateLimiter::hit($key, self::RATE_WINDOW_SECONDS);

            $filters = ['max_results' => $this->threadCount];
            try {
                $id = $agent->startBatch($userId, $filters);
            } catch (AgentUnavailable|InvalidAgentPayload $exception) {
                $code = $exception instanceof AgentUnavailable ? $exception->safeCode() : 'invalid_agent_payload';
                $this->errorMessage = Batch::agentError($code)['message'];

                return null;
            }

            return auth()->user()->batches()->create([
                'agent_batch_id' => $id,
                'status' => BatchStatus::Queued,
                'filters' => $filters,
            ]);
        });

        if ($batch === false) {
            $this->errorMessage = 'Permintaan sebelumnya masih diproses.';
        } elseif ($batch instanceof Batch) {
            SyncBatchStatusJob::dispatch($batch->id);
            $this->redirectRoute('batch.show', $batch);
        }
    }

    public function render(): View
    {
        return view('livewire.batch-index', [
            'batches' => $this->batches(),
            'active' => $this->activeBatch(),
            'maxThreads' => (int) config('agent.max_threads', 10),
            'demo' => config('agent.driver') === 'fake',
        ]);
    }

    /**
     * @return Collection<int, Batch>
     */
    private function batches(): Collection
    {
        return auth()->user()->batches()
            ->withCount('items')
            ->latest('id')
            ->limit(self::LIST_LIMIT)
            ->get(['id', 'user_id', 'status', 'filters', 'summary', 'created_at', 'finished_at']);
    }

    private function activeBatch(): ?Batch
    {
        return auth()->user()->batches()
            ->whereNotIn('status', array_map(
                fn (BatchStatus $s) => $s->value,
                array_filter(BatchStatus::cases(), fn (BatchStatus $s) => $s->isFinished()),
            ))
            ->latest('id')
            ->first(['id', 'status']);
    }
}
