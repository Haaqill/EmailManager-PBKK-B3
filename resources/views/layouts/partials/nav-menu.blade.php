@php
    // route null = halaman belum ada: ditampilkan nonaktif, bukan tautan.
    $items = [
        ['label' => 'Obrolan', 'route' => 'chat', 'active' => request()->routeIs('chat', 'chat.show')],
        ['label' => 'Batch', 'route' => null, 'active' => false],
        ['label' => 'Riwayat', 'route' => 'riwayat.index', 'active' => request()->routeIs('riwayat.*')],
        ['label' => 'Pengaturan', 'route' => null, 'active' => false],
    ];
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
@endphp

<nav aria-label="{{ $label }}" class="flex-1 overflow-y-auto px-3 py-4">
    <ul class="space-y-1">
        @foreach ($items as $item)
            <li>
                @if ($item['route'])
                    <a href="{{ route($item['route']) }}"
                       @if ($item['active']) aria-current="page" @endif
                       class="flex min-h-10 items-center rounded-md px-3 text-sm font-medium {{ $focus }} {{ $item['active'] ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900' }}">
                        {{ $item['label'] }}
                    </a>
                @else
                    <span aria-disabled="true" data-nav-soon
                          class="flex min-h-10 cursor-not-allowed items-center justify-between rounded-md px-3 text-sm font-medium text-slate-400">
                        {{ $item['label'] }}
                        <span class="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-500">Segera</span>
                    </span>
                @endif
            </li>
        @endforeach
    </ul>
</nav>

<div class="border-t border-slate-200 px-3 py-4">
    <div class="px-3 pb-2">
        <p class="truncate text-sm font-medium text-slate-900">{{ Auth::user()->name }}</p>
        <p class="truncate text-xs text-slate-500">{{ Auth::user()->email }}</p>
    </div>
    <a href="{{ route('profile.edit') }}"
       @if (request()->routeIs('profile.*')) aria-current="page" @endif
       class="flex min-h-10 items-center rounded-md px-3 text-sm text-slate-700 hover:bg-slate-100 {{ $focus }}">
        Profil
    </a>
    <form method="POST" action="{{ route('logout') }}">
        @csrf
        <button type="submit"
                class="flex min-h-10 w-full items-center rounded-md px-3 text-left text-sm text-slate-700 hover:bg-slate-100 {{ $focus }}">
            Keluar
        </button>
    </form>
</div>
