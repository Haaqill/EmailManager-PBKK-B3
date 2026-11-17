<?php

namespace App\Policies;

use App\Models\ChatSession;
use App\Models\User;

/**
 * Sesi chat hanya boleh dilihat dan dihapus pemiliknya.
 * Ditemukan otomatis oleh Laravel (konvensi nama App\Policies\{Model}Policy).
 */
class ChatSessionPolicy
{
    public function view(User $user, ChatSession $session): bool
    {
        return $user->id === $session->user_id;
    }

    public function delete(User $user, ChatSession $session): bool
    {
        return $user->id === $session->user_id;
    }
}
