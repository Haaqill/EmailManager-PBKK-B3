<!DOCTYPE html>
<html lang="id">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="csrf-token" content="{{ csrf_token() }}">

        <title>{{ config('app.name', 'Gmail Inbox Manager') }}</title>

        <!-- Fonts -->
        <link rel="preconnect" href="https://fonts.bunny.net">
        <link href="https://fonts.bunny.net/css?family=figtree:400,500,600&display=swap" rel="stylesheet" />

        <!-- Scripts: Alpine berasal dari bundel Livewire (lihat resources/js/app.js) -->
        @vite(['resources/css/app.css', 'resources/js/app.js'])
        @livewireStyles
    </head>
    <body class="bg-slate-50 font-sans text-slate-900 antialiased">
        <a href="#konten"
           class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-indigo-700 focus:outline focus:outline-2 focus:outline-indigo-600">
            Lompat ke konten
        </a>

        <div x-data="{ drawer: false }" @keydown.escape.window="drawer = false" class="min-h-screen lg:flex">
            @include('layouts.navigation')

            <main id="konten" tabindex="-1" class="min-w-0 flex-1 focus:outline-none">
                @isset($header)
                    <header class="border-b border-slate-200 bg-white">
                        <div class="px-4 py-4 sm:px-6 lg:px-8">
                            {{ $header }}
                        </div>
                    </header>
                @endisset

                {{ $slot }}
            </main>
        </div>
        @livewireScriptConfig
    </body>
</html>
