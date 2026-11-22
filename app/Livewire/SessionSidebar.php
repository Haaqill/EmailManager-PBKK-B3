<?php

namespace App\Livewire;

use App\Models\ChatSession;
use Illuminate\Contracts\View\View;
use Illuminate\Support\Facades\DB;
use Livewire\Attributes\Locked;
use Livewire\Attributes\On;
use Livewire\Component;

/**
 * Daftar sesi obrolan milik pengguna (mode chat), terbaru di atas.
 */
class SessionSidebar extends Component
{
    public const LIMIT = 50;

    #[Locked]
    public ?int $activeId = null;

    public function mount(?int $activeId = null): void
    {
        if ($activeId !== null) {
            $this->authorize('view', ChatSession::query()->findOrFail($activeId));
            $this->activeId = $activeId;
        }
    }

    /**
     * Dipicu ChatAgent setelah pesan dikirim; hanya menandai sesi aktif milik
     * pengguna sendiri.
     */
    #[On('chat-session-updated')]
    public function sessionUpdated(int $id): void
    {
        $session = ChatSession::query()->find($id);
        if ($session !== null && auth()->user()->can('view', $session)) {
            $this->activeId = $id;
        }
    }

    public function deleteSession(int $id): void
    {
        $session = ChatSession::query()->findOrFail($id);
        $this->authorize('delete', $session);

        // FK chat_messages/tool_execution_logs/batch_plan_items ke chat_sessions memakai cascade.
        DB::transaction(fn () => $session->delete());

        if ($this->activeId === $id) {
            $this->redirectRoute('chat');
        }
    }

    public function render(): View
    {
        return view('livewire.session-sidebar', [
            'sessions' => auth()->user()
                ->chatSessions()
                ->where('mode', 'chat')
                ->latest('updated_at')
                ->latest('id')
                ->limit(self::LIMIT)
                ->get(['id', 'title', 'updated_at']),
        ]);
    }
}
