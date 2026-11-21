@use('App\Enums\PlanDecision')
@php
    $focus = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600';
    $resultLabels = ['ok' => 'Berhasil', 'failed' => 'Gagal', 'skipped' => 'Dilewati', 'rejected' => 'Ditolak'];
@endphp

<section aria-labelledby="judul-laporan" class="space-y-4">
    <div class="rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
        <h2 id="judul-laporan" class="font-semibold text-slate-900">Laporan batch</h2>
        <dl class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            @foreach ($resultCounts as $label => $count)
                <div class="rounded-md bg-slate-50 px-3 py-2">
                    <dt class="text-xs text-slate-500">{{ $label }}</dt>
                    <dd class="text-lg font-semibold text-slate-900">{{ $count }}</dd>
                </div>
            @endforeach
        </dl>
        <p class="mt-3 text-xs text-slate-500">Isi email dan draf sudah dihapus dari aplikasi setelah batch selesai.</p>
    </div>

    <ul class="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white" aria-label="Hasil per item">
        @foreach ($items as $item)
            @php $applied = $item->applied ?? []; @endphp
            <li wire:key="hasil-{{ $item->item_id }}" class="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                <div class="min-w-0">
                    <p class="break-words text-sm font-medium text-slate-900">{{ $item->subject ?: '(tanpa subjek)' }}</p>
                    <p class="text-xs text-slate-500">
                        {{ $item->category->label() }} · {{ $item->action->label() }} ·
                        {{ $item->decision === PlanDecision::Pending ? 'Belum diputuskan' : $item->decision->label() }}
                    </p>
                    @if ($applied)
                        <p class="mt-1 break-words text-xs text-slate-600">
                            @if ($applied['labels'] ?? []) Label: {{ implode(', ', $applied['labels']) }}. @endif
                            @if ($applied['archived'] ?? false) Diarsipkan. @endif
                            @if ($applied['draft_id'] ?? null) Draf dibuat. @endif
                        </p>
                    @endif
                </div>
                <span class="shrink-0 self-start rounded px-2 py-0.5 text-xs font-medium
                             {{ $item->result_status === 'ok' ? 'bg-green-50 text-green-800' : ($item->result_status === 'failed' ? 'bg-red-50 text-red-800' : 'bg-slate-100 text-slate-700') }}">
                    {{ $resultLabels[$item->result_status] ?? 'Tidak diketahui' }}
                </span>
            </li>
        @endforeach
    </ul>

    <a href="{{ route('batch') }}"
       class="inline-flex min-h-10 items-center rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-500 {{ $focus }}">
        Mulai batch baru
    </a>
</section>
