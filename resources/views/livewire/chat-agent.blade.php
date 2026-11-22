@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
    $latency = fn (?int $ms) => $ms === null ? null
        : ($ms < 1000 ? $ms . ' ms' : number_format($ms / 1000, 1, ',', '.') . ' dtk');
@endphp

<section x-data="{ sent: '' }" aria-labelledby="judul-obrolan"
         class="flex min-h-[calc(100vh-9rem)] min-w-0 flex-col rounded-lg border border-slate-200 bg-white lg:min-h-[calc(100vh-5rem)]">
    <h2 id="judul-obrolan" class="sr-only">Percakapan</h2>

    <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
        <div aria-live="polite" class="space-y-4">
            @forelse ($messages as $message)
                @if ($message->role === 'user')
                    <div wire:key="pesan-{{ $message->id }}" class="flex justify-end">
                        <p class="max-w-[85%] whitespace-pre-wrap break-words rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white [overflow-wrap:anywhere]">{{ $message->content }}</p>
                    </div>
                @else
                    <div wire:key="pesan-{{ $message->id }}" class="max-w-[85%]">
                        <div class="chat-markdown rounded-lg bg-slate-100 px-4 py-2 [overflow-wrap:anywhere]">
                            {!! Str::markdown($message->content, ['html_input' => 'strip', 'allow_unsafe_links' => false]) !!}
                        </div>
                        @if ($message->model)
                            <p class="mt-1 text-xs text-slate-500">
                                {{ $message->model }}@if ($latency($message->latency_ms)) · {{ $latency($message->latency_ms) }}@endif
                            </p>
                        @endif
                    </div>
                @endif
            @empty
                <div wire:loading.remove wire:target="sendMessage" class="mx-auto max-w-md py-10 text-center">
                    <p class="font-medium text-slate-800">Mulai obrolan baru</p>
                    <p class="mt-1 text-sm text-slate-500">
                        Asisten belum bisa membaca inbox Anda. Tempel teks email bila ingin dibantu merangkum,
                        mengategorikan, atau menyusun draf balasan.
                    </p>
                </div>
            @endforelse
        </div>

        {{-- Selama memproses: pesan yang baru dikirim (optimistis) dan jawaban yang mengalir. --}}
        <div wire:loading.flex wire:target="sendMessage" class="hidden justify-end" aria-hidden="true">
            <p x-text="sent" class="max-w-[85%] whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-lg bg-indigo-600/80 px-4 py-2 text-sm text-white"></p>
        </div>
        <div wire:loading.block wire:target="sendMessage, retry" class="hidden max-w-[85%]">
            <p role="status" class="sr-only">Asisten sedang menjawab…</p>
            <div aria-hidden="true" class="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-800">
                <div wire:stream="thinkingIndicator" class="animate-pulse text-xs italic text-slate-500">Sedang menjawab…</div>
                <div wire:stream="streamedReply" class="whitespace-pre-wrap break-words"></div>
            </div>
        </div>

        @if ($errorMessage || $canRetry)
            <div wire:loading.remove wire:target="sendMessage, retry" role="alert"
                 class="flex flex-wrap items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                <span class="flex-1">{{ $errorMessage ?? 'Pesan terakhir belum dijawab.' }}</span>
                @if ($canRetry)
                    <button type="button" wire:click="retry" wire:loading.attr="disabled"
                            class="min-h-10 rounded-md bg-white px-3 text-sm font-medium text-red-800 ring-1 ring-inset ring-red-300 hover:bg-red-100 disabled:opacity-50 {{ $focus }}">
                        Coba lagi
                    </button>
                @endif
            </div>
        @endif
    </div>

    <form wire:submit="sendMessage" @submit="sent = $wire.prompt" class="border-t border-slate-200 px-4 py-3 sm:px-6">
        <label for="prompt-obrolan" class="sr-only">Pesan</label>
        <div class="flex items-start gap-2">
            <textarea id="prompt-obrolan" wire:model="prompt" rows="2" maxlength="1000"
                      wire:loading.attr="disabled" wire:target="sendMessage, retry"
                      @keydown.enter="if (! $event.shiftKey) { $event.preventDefault(); $el.form.requestSubmit(); }"
                      aria-describedby="petunjuk-prompt catatan-ai @error('prompt') galat-prompt @enderror"
                      @error('prompt') aria-invalid="true" @enderror
                      class="min-w-0 flex-1 resize-y rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
                      placeholder="Tulis pesan…"></textarea>
            <button type="submit" wire:loading.attr="disabled" wire:target="sendMessage, retry"
                    class="min-h-10 shrink-0 rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 {{ $focus }}">
                Kirim
            </button>
        </div>
        @error('prompt')
            <p id="galat-prompt" class="mt-1 text-sm text-red-700">{{ $message }}</p>
        @enderror
        <p id="petunjuk-prompt" class="mt-1 text-xs text-slate-500">Enter untuk kirim, Shift+Enter untuk baris baru. Maksimal 1000 karakter.</p>
        <p id="catatan-ai" class="mt-1 text-xs text-slate-500">
            AI dapat membuat kesalahan. Jawaban obrolan belum disertai tingkat keyakinan; periksa kembali informasi penting.
        </p>
    </form>
</section>
