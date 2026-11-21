@use('App\Enums\BatchStatus')
@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
    $status = $batch->status;
    $ended = in_array($status, [BatchStatus::Failed, BatchStatus::Cancelled, BatchStatus::Expired], true);
@endphp

<div @if ($polling) wire:poll.2s="refreshStatus" @endif class="space-y-6">
    @include('batch.partials.demo-banner')

    @include('batch.partials.stepper', ['status' => $status])

    <p aria-live="polite" class="text-sm text-slate-700">
        Status: <span class="font-medium">{{ $status->label() }}</span>
        <span wire:loading wire:target="refreshStatus" class="text-slate-500">· memperbarui…</span>
    </p>

    @if ($errorMessage)
        <div role="alert" class="flex flex-wrap items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <span class="flex-1">{{ $errorMessage }}</span>
            @if ($errorMessage === \App\Livewire\BatchRun::ERROR_UNAVAILABLE)
                <button type="button" wire:click="refreshStatus" wire:loading.attr="disabled"
                        class="min-h-10 rounded-md bg-white px-3 text-sm font-medium text-red-800 ring-1 ring-inset ring-red-300 hover:bg-red-100 disabled:opacity-50 {{ $focus }}">
                    Coba lagi
                </button>
            @endif
        </div>
    @endif

    @if ($notice)
        <p role="status" class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{{ $notice }}</p>
    @endif

    @if ($polling)
        {{-- Berjalan / mengeksekusi --}}
        <section class="rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
            <p class="text-sm text-slate-600">
                @if ($status === BatchStatus::Executing)
                    Menjalankan aksi yang Anda setujui…
                @else
                    Agen sedang memproses email. Halaman ini diperbarui otomatis.
                @endif
            </p>
            @if ($status !== BatchStatus::Executing)
                <button type="button" wire:click="cancel" wire:confirm="Batalkan batch ini?" wire:loading.attr="disabled"
                        class="mt-4 min-h-10 rounded-md bg-white px-4 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:opacity-50 {{ $focus }}">
                    Batalkan
                </button>
            @endif
        </section>
    @elseif ($status === BatchStatus::AwaitingReview)
        @include('batch.partials.review')
    @elseif ($status === BatchStatus::Done)
        @include('batch.partials.report')
    @elseif ($ended)
        <section class="rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
            <h2 class="font-semibold text-slate-900">
                @switch($status)
                    @case(BatchStatus::Failed) Batch gagal @break
                    @case(BatchStatus::Cancelled) Batch dibatalkan @break
                    @default Batch kedaluwarsa
                @endswitch
            </h2>
            <p class="mt-1 text-sm text-slate-600">
                @switch($status)
                    @case(BatchStatus::Failed) Agen tidak bisa menyelesaikan batch ini. Tidak ada aksi yang dijalankan. @break
                    @case(BatchStatus::Cancelled) Batch dibatalkan sebelum ada aksi yang dijalankan. @break
                    @default Batch tidak ditinjau terlalu lama, jadi rencananya dihapus. Tidak ada aksi yang dijalankan.
                @endswitch
            </p>
            <a href="{{ route('batch') }}"
               class="mt-4 inline-flex min-h-10 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 {{ $focus }}">
                Mulai ulang
            </a>
        </section>
    @endif
</div>
