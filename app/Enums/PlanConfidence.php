<?php

namespace App\Enums;

/**
 * Keyakinan model terhadap kategori dan aksi usulan. Hanya untuk menyorot baris
 * di UI; bukan gerbang keamanan (tidak mengubah keputusan, konfirmasi trash,
 * atau kewajiban review).
 */
enum PlanConfidence: string
{
    case Tinggi = 'tinggi';
    case Sedang = 'sedang';
    case Rendah = 'rendah';

    public function label(): string
    {
        return match ($this) {
            self::Tinggi => 'Keyakinan tinggi',
            self::Sedang => 'Keyakinan sedang',
            self::Rendah => 'Keyakinan rendah',
        };
    }
}
