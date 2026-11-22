<?php

namespace App\Enums;

/**
 * Keputusan pengguna atas satu item. Status lokal Laravel: tidak pernah
 * ditimpa oleh data dari agen.
 */
enum PlanDecision: string
{
    case Pending = 'pending';
    case Approve = 'approve';
    case Reject = 'reject';

    public function label(): string
    {
        return match ($this) {
            self::Pending => 'Menunggu',
            self::Approve => 'Disetujui',
            self::Reject => 'Ditolak',
        };
    }
}
