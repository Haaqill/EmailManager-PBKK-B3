<?php

namespace App\Policies;

use App\Models\Batch;
use App\Models\User;

/**
 * Batch hanya boleh dilihat, dieksekusi, dan dibatalkan pemiliknya.
 */
class BatchPolicy
{
    public function view(User $user, Batch $batch): bool
    {
        return $user->id === $batch->user_id;
    }

    public function execute(User $user, Batch $batch): bool
    {
        return $user->id === $batch->user_id;
    }

    public function cancel(User $user, Batch $batch): bool
    {
        return $user->id === $batch->user_id;
    }
}
