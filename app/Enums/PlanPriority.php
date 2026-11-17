<?php

namespace App\Enums;

enum PlanPriority: string
{
    case Mendesak = 'mendesak';
    case Normal = 'normal';
    case Nanti = 'nanti';

    public function label(): string
    {
        return match ($this) {
            self::Mendesak => 'Mendesak',
            self::Normal => 'Normal',
            self::Nanti => 'Nanti',
        };
    }
}
