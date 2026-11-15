<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\View\View;

class ChatHistoryController extends Controller
{
    public function index(Request $request): View
    {
        $sessions = $request->user()
            ->chatSessions()
            ->withCount(['messages', 'toolLogs'])
            ->latest('updated_at')
            ->paginate(15);

        return view('chat-history.index', compact('sessions'));
    }

    public function show(Request $request, int $chatSession): View
    {
        $session = $request->user()
            ->chatSessions()
            ->with([
                'messages.toolLogs',
                'planItems.toolLogs',
            ])
            ->findOrFail($chatSession);

        return view('chat-history.show', compact('session'));
    }
}
