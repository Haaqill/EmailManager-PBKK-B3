<x-app-layout>
    <div class="mx-auto max-w-4xl p-4 pb-32 sm:p-6 sm:pb-32 lg:p-8 lg:pb-32">
        <a href="{{ route('batch') }}"
           class="inline-flex min-h-10 items-center rounded-md text-sm font-medium text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
            ← Semua batch
        </a>
        <h1 class="mt-2 text-xl font-semibold text-slate-900">Batch #{{ $batch->id }}</h1>
        <div class="mt-4">
            <livewire:batch-run :batch-id="$batch->id" />
        </div>
    </div>
</x-app-layout>
