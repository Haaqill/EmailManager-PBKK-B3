<x-app-layout>
    <div class="flex min-w-0 flex-col gap-4 p-4 sm:p-6 lg:flex-row lg:p-8">
        <div x-data="{ daftar: false }" class="lg:w-64 lg:shrink-0">
            <button type="button" @click="daftar = ! daftar"
                    aria-controls="daftar-obrolan" :aria-expanded="daftar.toString()" aria-expanded="false"
                    class="flex min-h-10 w-full items-center justify-between rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 lg:hidden">
                Daftar obrolan
                <svg class="h-4 w-4 transition" :class="daftar && 'rotate-180'" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
            </button>
            <div id="daftar-obrolan" :class="daftar ? 'block' : 'hidden'" class="mt-2 hidden lg:mt-0 lg:block">
                <livewire:session-sidebar :active-id="$session?->id" />
            </div>
        </div>

        <div class="min-w-0 flex-1">
            <h1 class="sr-only">Obrolan</h1>
            <livewire:chat-agent :session-id="$session?->id" :key="'chat-' . ($session?->id ?? 'baru')" />
        </div>
    </div>
</x-app-layout>
