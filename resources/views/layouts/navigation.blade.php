{{-- Sidebar (lg ke atas) dan drawer (di bawah lg). State `drawer` ada di layouts/app. --}}

{{-- Bilah atas mobile --}}
<div class="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 lg:hidden">
    <a href="{{ route('chat') }}"
       class="flex min-h-10 items-center gap-2 rounded-md font-semibold text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
        <x-application-logo class="h-7 w-7 fill-current text-indigo-600" />
        <span>{{ config('app.name') }}</span>
    </a>
    <button type="button" @click="drawer = true"
            aria-controls="navigasi-mobile" :aria-expanded="drawer.toString()" aria-expanded="false"
            class="inline-flex h-10 w-10 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600">
        <span class="sr-only">Buka menu</span>
        <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
    </button>
</div>

{{-- Drawer mobile --}}
<div x-cloak x-show="drawer" class="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu navigasi">
    <div x-show="drawer" x-transition.opacity @click="drawer = false" class="fixed inset-0 bg-slate-900/40" aria-hidden="true"></div>
    <div id="navigasi-mobile" x-show="drawer" x-trap.noscroll="drawer"
         x-transition:enter="transition ease-out duration-150" x-transition:enter-start="translate-x-full" x-transition:enter-end="translate-x-0"
         x-transition:leave="transition ease-in duration-100" x-transition:leave-start="translate-x-0" x-transition:leave-end="translate-x-full"
         class="fixed inset-y-0 right-0 flex w-72 max-w-[85vw] flex-col bg-white">
        <div class="flex h-14 items-center justify-between border-b border-slate-200 px-4">
            <span class="font-semibold">{{ config('app.name') }}</span>
            <button type="button" @click="drawer = false"
                    class="inline-flex h-10 w-10 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600">
                <span class="sr-only">Tutup menu</span>
                <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
        @include('layouts.partials.nav-menu', ['label' => 'Navigasi utama (mobile)'])
    </div>
</div>

{{-- Sidebar desktop --}}
<aside class="hidden lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-64 lg:shrink-0 lg:flex-col lg:border-r lg:border-slate-200 lg:bg-white">
    <div class="flex h-16 items-center px-5">
        <a href="{{ route('chat') }}"
           class="flex min-h-10 items-center gap-2 rounded-md font-semibold text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
            <x-application-logo class="h-8 w-8 fill-current text-indigo-600" />
            <span>{{ config('app.name') }}</span>
        </a>
    </div>
    @include('layouts.partials.nav-menu', ['label' => 'Navigasi utama'])
</aside>
