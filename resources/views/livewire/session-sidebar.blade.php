@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
@endphp

<nav aria-label="Daftar obrolan" class="flex min-w-0 flex-col">
    <a href="{{ route('chat') }}"
       class="flex min-h-10 items-center justify-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 {{ $focus }}">
        Obrolan baru
    </a>

    @if ($sessions->isEmpty())
        <p class="mt-4 px-1 text-sm text-slate-500">Belum ada obrolan.</p>
    @else
        <ul class="mt-4 space-y-1">
            @foreach ($sessions as $session)
                @php $active = $session->id === $activeId; @endphp
                <li wire:key="sesi-{{ $session->id }}" class="group flex items-center gap-1">
                    <a href="{{ route('chat.show', $session) }}"
                       @if ($active) aria-current="page" @endif
                       class="flex min-h-10 min-w-0 flex-1 items-center rounded-md px-3 text-sm {{ $focus }} {{ $active ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-700 hover:bg-slate-100' }}">
                        <span class="truncate">{{ $session->title ?: 'Tanpa judul' }}</span>
                    </a>
                    <button type="button"
                            wire:click="deleteSession({{ $session->id }})"
                            wire:confirm="Hapus obrolan ini? Semua pesannya ikut terhapus."
                            class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-red-50 hover:text-red-700 {{ $focus }}">
                        <span class="sr-only">Hapus obrolan “{{ $session->title ?: 'Tanpa judul' }}”</span>
                        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 7h12M9 7V4h6v3m-7 4v6m4-6v6m4-6v6M5 7l1 13h12l1-13" />
                        </svg>
                    </button>
                </li>
            @endforeach
        </ul>
    @endif
</nav>
