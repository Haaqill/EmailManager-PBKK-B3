<?php

namespace App\Http\Controllers;

use App\Models\ChatSession;
use Illuminate\View\View;

/**
 * Halaman Obrolan. Isinya komponen Livewire SessionSidebar dan ChatAgent;
 * otorisasi rute chat.show lewat middleware can:view (ChatSessionPolicy).
 */
class ChatController extends Controller
{
    public function index(): View
    {
        return view('chat', ['session' => null]);
    }

    public function show(ChatSession $session): View
    {
        return view('chat', ['session' => $session]);
    }
}
