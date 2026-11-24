<?php

namespace App\Enums;

enum BatchStatus: string
{
    case Queued = 'queued';
    case Scanning = 'scanning';
    case Classifying = 'classifying';
    case Drafting = 'drafting';
    case AwaitingReview = 'awaiting_review';
    case Executing = 'executing';
    case Done = 'done';
    case Failed = 'failed';
    case Cancelled = 'cancelled';
    /** Hanya dipakai Laravel (lihat batches:prune-review-data); agen tidak pernah mengirimnya. */
    case Expired = 'expired';

    public const POLLABLE = [self::Queued, self::Scanning, self::Classifying, self::Drafting, self::Executing];

    public function label(): string
    {
        return match ($this) {
            self::Queued => 'Antre',
            self::Scanning => 'Memindai',
            self::Classifying => 'Mengklasifikasi',
            self::Drafting => 'Menyusun draf',
            self::AwaitingReview => 'Menunggu review',
            self::Executing => 'Menjalankan',
            self::Done => 'Selesai',
            self::Failed => 'Gagal',
            self::Cancelled => 'Dibatalkan',
            self::Expired => 'Kedaluwarsa',
        };
    }

    /** Status yang membawa data review sementara. */
    public function inReview(): bool
    {
        return $this === self::AwaitingReview || $this === self::Executing;
    }

    /** Status akhir: data sementara wajib sudah kosong. */
    public function isFinished(): bool
    {
        return in_array($this, [self::Done, self::Failed, self::Cancelled, self::Expired], true);
    }
}
