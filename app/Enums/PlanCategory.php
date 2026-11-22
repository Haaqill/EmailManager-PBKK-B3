<?php

namespace App\Enums;

enum PlanCategory: string
{
    case Akademik = 'akademik';
    case Tugas = 'tugas';
    case Pengumuman = 'pengumuman';
    case Pribadi = 'pribadi';
    case Promosi = 'promosi';
    case Spam = 'spam';

    public function label(): string
    {
        return match ($this) {
            self::Akademik => 'Akademik',
            self::Tugas => 'Tugas',
            self::Pengumuman => 'Pengumuman',
            self::Pribadi => 'Pribadi',
            self::Promosi => 'Promosi',
            self::Spam => 'Spam',
        };
    }
}
