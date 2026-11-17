<?php

namespace App\Enums;

enum PlanAction: string
{
    case LabelOnly = 'label_only';
    case Archive = 'archive';
    case DraftReply = 'draft_reply';
    case Trash = 'trash';

    public function label(): string
    {
        return match ($this) {
            self::LabelOnly => 'Beri label',
            self::Archive => 'Arsipkan',
            self::DraftReply => 'Draft balasan',
            self::Trash => 'Pindahkan ke Sampah',
        };
    }
}
