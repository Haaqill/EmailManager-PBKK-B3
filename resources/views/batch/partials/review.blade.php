@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
    $btn = 'min-h-10 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ' . $focus;
@endphp

<section aria-labelledby="judul-ringkasan" class="rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
    <h2 id="judul-ringkasan" class="font-semibold text-slate-900">Tinjau rencana</h2>
    <p class="mt-1 text-sm text-slate-600">
        {{ $items->count() }} item.
        @foreach ($actionCounts as $label => $count)
            {{ $label }}: {{ $count }}@if (! $loop->last),@else.@endif
        @endforeach
        @if ($attention > 0)
            <strong class="font-semibold text-amber-800">{{ $attention }} butuh perhatian</strong> (berperingatan atau dipindahkan ke Sampah).
        @endif
    </p>
    <ul class="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-500">
        <li>Belum ada yang dijalankan. Item yang tidak Anda setujui tidak akan dijalankan.</li>
        <li>Draf balasan hanya dibuat di Gmail, tidak dikirim. Menyetujui item berarti menyetujui seluruh aksinya.</li>
        <li>Tingkat keyakinan adalah perkiraan model yang belum terkalibrasi; model cenderung terlalu yakin, jadi "tinggi" belum tentu benar. Tidak menentukan apa pun.</li>
    </ul>

    <div class="mt-4 flex flex-wrap gap-2">
        <button type="button" wire:click="approveSafe" wire:loading.attr="disabled" @disabled($safeCount === 0)
                aria-describedby="petunjuk-aman"
                class="{{ $btn }} bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
            Setujui semua yang aman ({{ $safeCount }})
        </button>
        <button type="button" wire:click="rejectAll" wire:loading.attr="disabled"
                class="{{ $btn }} bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
            Tolak semua
        </button>
    </div>
    <p id="petunjuk-aman" class="mt-2 text-xs text-slate-500">
        "Aman" berarti bukan Sampah, tanpa peringatan, dan keyakinan model bukan rendah.
    </p>
</section>

<ul class="space-y-4" aria-label="Item rencana">
    @foreach ($items as $item)
        @include('batch.partials.review-item', ['item' => $item])
    @endforeach
</ul>

{{-- Footer lengket: ringkasan keputusan dan tombol Jalankan --}}
<div x-data="{ open: false }" class="sticky bottom-0 z-10 -mx-4 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-lg sm:border">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-sm text-slate-700" aria-live="polite">
            {{ $decisionCounts['approve'] }} disetujui, {{ $decisionCounts['reject'] }} ditolak, {{ $decisionCounts['pending'] }} belum diputuskan (tidak akan dijalankan)
        </p>
        <button type="button" x-ref="jalankan" @click="open = true" @disabled($decisionCounts['approve'] === 0)
                wire:loading.attr="disabled" wire:target="execute"
                class="{{ $btn }} bg-indigo-600 px-4 font-semibold text-white hover:bg-indigo-500">
            Jalankan
        </button>
    </div>

    <div x-cloak x-show="open" class="fixed inset-0 z-50 flex items-center justify-center p-4"
         role="dialog" aria-modal="true" aria-labelledby="judul-jalankan"
         @keydown.escape="open = false; $nextTick(() => $refs.jalankan.focus())">
        <div class="fixed inset-0 bg-slate-900/40" aria-hidden="true" @click="open = false; $nextTick(() => $refs.jalankan.focus())"></div>
        <div x-trap.noscroll="open" class="relative w-full max-w-md rounded-lg bg-white p-5 shadow-lg">
            <h2 id="judul-jalankan" class="font-semibold text-slate-900">Jalankan {{ $decisionCounts['approve'] }} item yang disetujui?</h2>
            <ul class="mt-3 space-y-1 text-sm text-slate-700">
                @foreach ($plannedActions as $label => $count)
                    <li>{{ $label }}: {{ $count }}</li>
                @endforeach
            </ul>
            <p class="mt-3 text-xs text-slate-500">{{ $decisionCounts['pending'] }} item yang belum diputuskan tidak akan dijalankan.</p>
            <div class="mt-5 flex justify-end gap-2">
                <button type="button" @click="open = false; $nextTick(() => $refs.jalankan.focus())"
                        class="{{ $btn }} bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
                    Kembali
                </button>
                <button type="button" wire:click="execute" @click="open = false" wire:loading.attr="disabled" wire:target="execute"
                        class="{{ $btn }} bg-indigo-600 px-4 font-semibold text-white hover:bg-indigo-500">
                    <span wire:loading.remove wire:target="execute">Ya, jalankan</span>
                    <span wire:loading wire:target="execute" class="hidden">Menjalankan…</span>
                </button>
            </div>
        </div>
    </div>
</div>
