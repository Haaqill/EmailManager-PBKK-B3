<div class="bg-white shadow-sm sm:rounded-lg">
    <div class="flex items-center justify-between border-b border-gray-200 px-6 py-3 text-sm text-gray-500">
        <span>
            @if ($modelUsed)
                Model: <span class="font-medium text-gray-700">{{ $modelUsed }}</span>
            @else
                Sesi baru
            @endif
        </span>
        <button type="button" wire:click="newChat" class="text-indigo-600 hover:underline">
            Chat baru
        </button>
    </div>

    <div class="max-h-[60vh] space-y-4 overflow-y-auto px-6 py-4">
        @foreach ($messages as $message)
            <div wire:key="message-{{ $loop->index }}"
                 class="{{ $message['role'] === 'user' ? 'ml-auto bg-indigo-600 text-white' : 'bg-gray-100 text-gray-800' }} max-w-[80%] whitespace-pre-wrap rounded-lg px-4 py-2">{{ $message['content'] }}</div>
        @endforeach

        <div wire:loading.block wire:target="sendMessage" class="max-w-[80%] rounded-lg bg-gray-100 px-4 py-2 text-gray-800">
            <div wire:stream="thinkingIndicator" class="animate-pulse text-sm italic text-gray-500"></div>
            <div wire:stream="streamedReply" class="whitespace-pre-wrap"></div>
        </div>

        @if ($errorMessage)
            <div class="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{{ $errorMessage }}</div>
        @endif

        @if (empty($messages))
            <p class="text-center text-sm text-gray-400">Tanyakan sesuatu tentang inbox Anda.</p>
        @endif
    </div>

    <form wire:submit="sendMessage" class="flex gap-2 border-t border-gray-200 px-6 py-4">
        <div class="flex-1">
            <textarea wire:model="prompt" rows="2" maxlength="1000"
                      class="w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                      placeholder="Contoh: Ringkas email dari dosen tentang Tugas 3."></textarea>
            @error('prompt')
                <p class="mt-1 text-sm text-red-600">{{ $message }}</p>
            @enderror
        </div>
        <button type="submit" wire:loading.attr="disabled" wire:target="sendMessage"
                class="self-start rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            Kirim
        </button>
    </form>
</div>
