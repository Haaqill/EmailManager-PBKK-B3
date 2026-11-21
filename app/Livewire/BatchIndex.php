<?php

namespace App\Livewire;

use App\Enums\BatchStatus;
use App\Models\Batch;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\BatchSyncService;
use App\Services\Agent\InvalidAgentPayload;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\RateLimiter;
use Livewire\Component;

/**
 * Halaman /batch: mulai batch baru dan daftar batch terakhir milik pengguna.
 * Baris lokal Batch dibuat oleh BatchSyncService dari payload agen, bukan di sini.
 */
class BatchIndex extends Component
{
    public const LIST_LIMIT = 20;

    public const RATE_LIMIT = 5;

    public const RATE_WINDOW_SECONDS = 60;

    public const ERROR_UNAVAILABLE = 'Agen sedang tidak bisa dihubungi. Silakan coba lagi.';

    public int $threadCount = 10;

    public ?string $errorMessage = null;

    public function start(AgentClient $agent, BatchSyncService $sync): void
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
        $batch = Cache::lock('batch-start-lock:' . $userId, 10)->get(function () use ($agent, $sync, $userId, $key) {
            if ($this->activeBatch() !== null) {
                $this->errorMessage = 'Masih ada batch yang berjalan. Selesaikan atau batalkan dulu.';

                return null;
            }
            RateLimiter::hit($key, self::RATE_WINDOW_SECONDS);

            try {
                $id = $agent->startBatch($userId, ['max_results' => $this->threadCount]);

                return $sync->sync($userId, $agent->getBatch($userId, $id));
            } catch (AgentUnavailable|InvalidAgentPayload $e) {
                report($e);
                $this->errorMessage = self::ERROR_UNAVAILABLE;

                return null;
            }
        });

        if ($batch === false) {
            $this->errorMessage = 'Permintaan sebelumnya masih diproses.';
        } elseif ($batch instanceof Batch) {
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
