@use('App\Enums\BatchStatus')
@php
    $steps = [
        ['Scan', [BatchStatus::Queued, BatchStatus::Scanning]],
        ['Klasifikasi', [BatchStatus::Classifying]],
        ['Draf', [BatchStatus::Drafting]],
        ['Review', [BatchStatus::AwaitingReview]],
        ['Eksekusi', [BatchStatus::Executing]],
        ['Selesai', [BatchStatus::Done]],
    ];
    $current = null;
    foreach ($steps as $i => [, $statuses]) {
        if (in_array($status, $statuses, true)) {
            $current = $i;
        }
    }
@endphp

<ol aria-label="Tahap batch" class="grid grid-cols-3 gap-2 sm:grid-cols-6">
    @foreach ($steps as $i => [$label])
        @php
            $state = $current === null ? 'idle' : ($i < $current ? 'done' : ($i === $current ? 'current' : 'idle'));
        @endphp
        <li @if ($state === 'current') aria-current="step" @endif
            class="rounded-md border px-2 py-2 text-center text-xs font-medium
                   {{ $state === 'current' ? 'border-indigo-600 bg-indigo-50 text-indigo-700' : '' }}
                   {{ $state === 'done' ? 'border-slate-200 bg-white text-slate-700' : '' }}
                   {{ $state === 'idle' ? 'border-slate-200 bg-slate-50 text-slate-400' : '' }}">
            @if ($state === 'done')
                <span aria-hidden="true">✓</span>
                <span class="sr-only">Selesai:</span>
            @endif
            {{ $label }}
        </li>
    @endforeach
</ol>
