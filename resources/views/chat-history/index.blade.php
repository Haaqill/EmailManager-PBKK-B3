<x-app-layout>
    <x-slot name="header">
        <h2 class="font-semibold text-xl text-gray-800 leading-tight">
            Riwayat Obrolan
        </h2>
    </x-slot>

    <div class="py-12">
        <div class="max-w-7xl mx-auto sm:px-6 lg:px-8">
            <div class="bg-white overflow-hidden shadow-sm sm:rounded-lg">
                <div class="p-6 text-gray-900">
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead>
                                <tr class="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-600">
                                    <th class="px-4 py-3">Judul</th>
                                    <th class="px-4 py-3">Mode</th>
                                    <th class="px-4 py-3">Status</th>
                                    <th class="px-4 py-3">Pesan</th>
                                    <th class="px-4 py-3">Log</th>
                                    <th class="px-4 py-3">Waktu</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100 text-sm text-gray-700">
                                @forelse ($sessions as $session)
                                    <tr>
                                        <td class="px-4 py-3">
                                            <a href="{{ route('riwayat.show', $session) }}" class="text-indigo-600 hover:underline">
                                                {{ $session->title }}
                                            </a>
                                        </td>
                                        <td class="px-4 py-3 uppercase">{{ $session->mode }}</td>
                                        <td class="px-4 py-3">{{ $session->status }}</td>
                                        <td class="px-4 py-3">{{ $session->messages_count }}</td>
                                        <td class="px-4 py-3">{{ $session->tool_logs_count }}</td>
                                        <td class="px-4 py-3">{{ $session->updated_at->format('d M Y, H:i') }}</td>
                                    </tr>
                                @empty
                                    <tr>
                                        <td colspan="6" class="px-4 py-6 text-center text-gray-500">
                                            Belum ada riwayat obrolan.
                                        </td>
                                    </tr>
                                @endforelse
                            </tbody>
                        </table>
                    </div>

                    <div class="mt-6">
                        {{ $sessions->links() }}
                    </div>
                </div>
            </div>
        </div>
    </div>
</x-app-layout>
