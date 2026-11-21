@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
@endphp

<div class="space-y-6">
    @include('batch.partials.demo-banner')

    <section aria-labelledby="judul-mulai" class="rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
        <h2 id="judul-mulai" class="font-semibold text-slate-900">Mulai proses email</h2>

        @if ($active)
            <p class="mt-2 text-sm text-slate-600">
                Batch #{{ $active->id }} masih {{ Str::lower($active->status->label()) }}. Selesaikan atau batalkan dulu sebelum memulai yang baru.
            </p>
            <a href="{{ route('batch.show', $active) }}"
               class="mt-4 inline-flex min-h-10 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 {{ $focus }}">
                Lanjutkan batch yang berjalan
            </a>
        @else
            <form wire:submit="start" class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
                <div>
                    <label for="jumlah-thread" class="block text-sm font-medium text-slate-700">Jumlah email</label>
                    <input id="jumlah-thread" type="number" wire:model="threadCount" min="1" max="{{ $maxThreads }}" required
                           aria-describedby="petunjuk-jumlah @error('threadCount') galat-jumlah @enderror"
                           @error('threadCount') aria-invalid="true" @enderror
                           class="mt-1 block w-32 rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500">
                </div>
                <button type="submit" wire:loading.attr="disabled" wire:target="start"
                        class="min-h-10 rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 {{ $focus }}">
                    <span wire:loading.remove wire:target="start">Mulai</span>
                    <span wire:loading wire:target="start">Memulai…</span>
                </button>
            </form>
            <p id="petunjuk-jumlah" class="mt-2 text-xs text-slate-500">1 sampai {{ $maxThreads }} email terbaru. Tidak ada aksi yang dijalankan sebelum Anda menyetujuinya.</p>
            @error('threadCount')
                <p id="galat-jumlah" class="mt-1 text-sm text-red-700">{{ $message }}</p>
            @enderror
        @endif

        @if ($errorMessage)
            <p role="alert" class="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{{ $errorMessage }}</p>
        @endif
    </section>

    <section aria-labelledby="judul-daftar">
        <h2 id="judul-daftar" class="font-semibold text-slate-900">Batch terakhir</h2>

        @if ($batches->isEmpty())
            <p class="mt-3 rounded-lg border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">
                Belum ada batch. Mulai proses email di atas.
            </p>
        @else
            <ul class="mt-3 divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
                @foreach ($batches as $batch)
                    @php $s = $batch->summary ?? []; @endphp
                    <li wire:key="batch-{{ $batch->id }}">
                        <a href="{{ route('batch.show', $batch) }}"
                           class="flex flex-col gap-1 px-4 py-3 hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between {{ $focus }}">
                            <span class="text-sm font-medium text-slate-900">
                                Batch #{{ $batch->id }}
                                <span class="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-700">{{ $batch->status->label() }}</span>
                            </span>
                            <span class="text-xs text-slate-500">
                                {{ $batch->items_count }} item
                                @if (isset($s['approved']))
                                    · {{ (int) $s['approved'] }} disetujui, {{ (int) ($s['rejected'] ?? 0) }} ditolak
                                @endif
                                · <time datetime="{{ $batch->created_at->toIso8601String() }}">{{ $batch->created_at->format('d M Y, H:i') }}</time>
                            </span>
                        </a>
                    </li>
                @endforeach
            </ul>
        @endif
    </section>
</div>
