@use('App\Enums\PlanAction')
@use('App\Enums\PlanConfidence')
@use('App\Enums\PlanDecision')
@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
    $btn = 'min-h-10 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ' . $focus;
    $review = $item->review_data ?? [];
    $warnings = $review['warnings'] ?? [];
    $isTrash = $item->action === PlanAction::Trash || ($review['requires_confirmation'] ?? false);
    $alsoArchive = (bool) ($review['also_archive'] ?? false);
    $confidence = PlanConfidence::tryFrom((string) ($review['confidence'] ?? ''));
    $draft = $review['draft'] ?? null;
    $key = 'item-' . $item->item_id;
    $idJs = Js::from($item->item_id);
@endphp

<li wire:key="{{ $key }}" aria-labelledby="{{ $key }}-judul"
    class="rounded-lg border bg-white p-4 sm:p-5 {{ $warnings || $isTrash ? 'border-amber-300' : 'border-slate-200' }}">
    <div class="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div class="min-w-0">
            <h3 id="{{ $key }}-judul" class="break-words font-medium text-slate-900">{{ $item->subject ?: '(tanpa subjek)' }}</h3>
            <p class="break-words text-sm text-slate-600">{{ $item->from_name ?: 'Pengirim tidak diketahui' }}</p>
        </div>
        <div class="flex shrink-0 flex-wrap gap-1">
            <span class="rounded bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">{{ $item->category->label() }}</span>
            <span class="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{{ $item->priority->label() }}</span>
        </div>
    </div>

    <p class="mt-3 text-sm text-slate-800">
        <span class="font-medium">Aksi usulan:</span>
        @if ($item->action === PlanAction::DraftReply && $alsoArchive)
            draf balasan, lalu arsipkan thread
        @else
            {{ Str::lower($item->action->label()) }}
        @endif
    </p>
    @if (($review['reason'] ?? '') !== '')
        <p class="mt-1 break-words text-sm text-slate-600"><span class="font-medium text-slate-700">Alasan:</span> {{ $review['reason'] }}</p>
    @endif
    @if ($confidence)
        <p class="mt-1 text-xs text-slate-400" title="Perkiraan model, belum dievaluasi">{{ $confidence->label() }} <span class="sr-only">(perkiraan model, belum dievaluasi)</span></p>
    @endif

    @if ($warnings)
        <ul class="mt-3 space-y-2">
            @foreach ($warnings as $w)
                <li class="flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    <svg class="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
                    </svg>
                    <span><span class="font-semibold">Peringatan:</span> {{ $w['message'] ?: $w['code'] }}</span>
                </li>
            @endforeach
        </ul>
    @endif
    @if ($isTrash)
        <p class="mt-3 text-sm text-amber-900">Item ini akan dipindahkan ke Sampah. Menyetujuinya butuh konfirmasi.</p>
    @endif

    @if ($item->action === PlanAction::DraftReply && $draft)
        <div class="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
            <p class="text-xs text-slate-500">Draf hanya dibuat di Gmail, tidak dikirim.</p>
            <dl class="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-sm">
                <dt class="font-medium text-slate-700">Kepada</dt>
                <dd class="break-words text-slate-800">{{ $draft['to'] ?? '' }}</dd>
                <dt class="font-medium text-slate-700">Subjek</dt>
                <dd class="break-words text-slate-800">{{ $draft['subject'] ?? '' }}</dd>
            </dl>
            <label for="{{ $key }}-draf" class="mt-3 block text-sm font-medium text-slate-700">Isi draf</label>
            <textarea id="{{ $key }}-draf" rows="5" maxlength="{{ \App\Livewire\BatchRun::DRAFT_MAX }}"
                      wire:model.blur="drafts.{{ $item->item_id }}"
                      @error('drafts.' . $item->item_id) aria-invalid="true" aria-describedby="{{ $key }}-galat" @enderror
                      class="mt-1 block w-full whitespace-pre-wrap rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"></textarea>
            @error('drafts.' . $item->item_id)
                <p id="{{ $key }}-galat" class="mt-1 text-sm text-red-700">{{ $message }}</p>
            @enderror
            @if ($item->edited_draft_body !== null)
                <div class="mt-2 flex flex-wrap items-center gap-2">
                    <span class="text-xs text-slate-500">Draf sudah Anda ubah.</span>
                    <button type="button" wire:click="resetDraft({{ $idJs }})"
                            class="{{ $btn }} bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-100">
                        Kembalikan ke draf asli
                    </button>
                </div>
            @endif
        </div>
    @endif

    <div class="mt-4 flex flex-wrap items-center gap-2" x-data="{ open: false }">
        <span class="mr-auto text-sm text-slate-600">Keputusan: <span class="font-medium text-slate-900">{{ $item->decision === PlanDecision::Pending ? 'Belum diputuskan' : $item->decision->label() }}</span></span>

        @if ($isTrash)
            <button type="button" x-ref="pemicu" @click="open = true" aria-pressed="{{ $item->decision === PlanDecision::Approve ? 'true' : 'false' }}"
                    class="{{ $btn }} {{ $item->decision === PlanDecision::Approve ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50' }}">
                Setujui…
            </button>
            <div x-cloak x-show="open" class="fixed inset-0 z-50 flex items-center justify-center p-4"
                 role="dialog" aria-modal="true" aria-labelledby="{{ $key }}-dialog"
                 @keydown.escape="open = false; $nextTick(() => $refs.pemicu.focus())">
                <div class="fixed inset-0 bg-slate-900/40" aria-hidden="true" @click="open = false; $nextTick(() => $refs.pemicu.focus())"></div>
                <div x-trap.noscroll="open" class="relative w-full max-w-md rounded-lg bg-white p-5 shadow-lg">
                    <h4 id="{{ $key }}-dialog" class="font-semibold text-slate-900">Pindahkan ke Sampah?</h4>
                    <p class="mt-2 break-words text-sm text-slate-700">“{{ $item->subject ?: '(tanpa subjek)' }}” akan dipindahkan ke Sampah Gmail saat batch dijalankan.</p>
                    <div class="mt-5 flex justify-end gap-2">
                        <button type="button" @click="open = false; $nextTick(() => $refs.pemicu.focus())"
                                class="{{ $btn }} bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
                            Batal
                        </button>
                        <button type="button" wire:click="confirmTrash({{ $idJs }})" @click="open = false; $nextTick(() => $refs.pemicu.focus())"
                                class="{{ $btn }} bg-red-600 text-white hover:bg-red-500">
                            Ya, setujui
                        </button>
                    </div>
                </div>
            </div>
        @else
            <button type="button" wire:click="setDecision({{ $idJs }}, 'approve')" aria-pressed="{{ $item->decision === PlanDecision::Approve ? 'true' : 'false' }}"
                    class="{{ $btn }} {{ $item->decision === PlanDecision::Approve ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50' }}">
                Setujui
            </button>
        @endif
        <button type="button" wire:click="setDecision({{ $idJs }}, 'reject')" aria-pressed="{{ $item->decision === PlanDecision::Reject ? 'true' : 'false' }}"
                class="{{ $btn }} {{ $item->decision === PlanDecision::Reject ? 'bg-slate-700 text-white' : 'bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50' }}">
            Tolak
        </button>
    </div>
</li>
