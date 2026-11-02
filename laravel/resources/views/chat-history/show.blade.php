<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">
            {{ $session->title }}
        </h2>
    </x-slot>

    <div class="py-12">
        <div class="max-w-7xl mx-auto sm:px-6 lg:px-8 space-y-6">
            <div class="bg-white overflow-hidden shadow-sm sm:rounded-lg">
                <div class="p-6 text-gray-900">
                    <div class="mb-4 text-sm text-gray-600">
                        <span class="font-semibold">Mode:</span> {{ $session->mode }}
                        <span class="mx-2">|</span>
                        <span class="font-semibold">Status:</span> {{ $session->status }}
                    </div>

                    <h3 class="text-lg font-semibold mb-3">Pesan</h3>
                    <div class="space-y-4">
                        @forelse ($session->messages as $message)
                            <div class="rounded-lg border border-gray-200 p-4">
                                <div class="flex justify-between text-xs uppercase tracking-wide text-gray-500 mb-2">
                                    <span>{{ $message->role }}</span>
                                    <span>{{ $message->created_at?->format('d M Y, H:i') }}</span>
                                </div>
                                <p class="whitespace-pre-wrap text-sm text-gray-800">{{ $message->content }}</p>

                                @if ($message->toolLogs->isNotEmpty())
                                    <div class="mt-4">
                                        <h4 class="text-xs font-semibold uppercase text-gray-600 mb-2">Tool log</h4>
                                        <ul class="space-y-2 text-xs text-gray-700">
                                            @foreach ($message->toolLogs as $log)
                                                <li class="rounded bg-gray-50 px-3 py-2">
                                                    <div class="font-medium">{{ $log->tool_name }}</div>
                                                    <div>{{ $log->status }} · {{ $log->duration_ms ?? 0 }} ms</div>
                                                </li>
                                            @endforeach
                                        </ul>
                                    </div>
                                @endif
                            </div>
                        @empty
                            <p class="text-gray-500">Belum ada pesan pada sesi ini.</p>
                        @endforelse
                    </div>
                </div>
            </div>

            <div class="bg-white overflow-hidden shadow-sm sm:rounded-lg">
                <div class="p-6 text-gray-900">
                    <h3 class="text-lg font-semibold mb-3">Batch Plan Items</h3>
                    @if ($session->planItems->isNotEmpty())
                        <div class="overflow-x-auto">
                            <table class="min-w-full divide-y divide-gray-200 text-sm">
                                <thead>
                                    <tr class="bg-gray-50 text-left text-xs uppercase text-gray-600">
                                        <th class="px-3 py-2">Thread</th>
                                        <th class="px-3 py-2">Kategori</th>
                                        <th class="px-3 py-2">Prioritas</th>
                                        <th class="px-3 py-2">Aksi</th>
                                        <th class="px-3 py-2">Keputusan</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-gray-100">
                                    @foreach ($session->planItems as $item)
                                        <tr>
                                            <td class="px-3 py-2">{{ $item->gmail_thread_id }}</td>
                                            <td class="px-3 py-2">{{ $item->category }}</td>
                                            <td class="px-3 py-2">{{ $item->priority }}</td>
                                            <td class="px-3 py-2">{{ $item->action }}</td>
                                            <td class="px-3 py-2">{{ $item->decision }}</td>
                                        </tr>
                                        @if ($item->toolLogs->isNotEmpty())
                                            <tr>
                                                <td colspan="5" class="px-3 py-2 bg-gray-50">
                                                    <div class="text-xs font-semibold uppercase text-gray-600 mb-2">Tool log</div>
                                                    <ul class="space-y-1">
                                                        @foreach ($item->toolLogs as $log)
                                                            <li>{{ $log->tool_name }} — {{ $log->status }}</li>
                                                        @endforeach
                                                    </ul>
                                                </td>
                                            </tr>
                                        @endif
                                    @endforeach
                                </tbody>
                            </table>
                        </div>
                    @else
                        <p class="text-gray-500">Tidak ada item batch.</p>
                    @endif
                </div>
            </div>
        </div>
    </div>
</x-app-layout>
