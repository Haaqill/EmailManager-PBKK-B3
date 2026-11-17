<?php

namespace App\Services\Agent;

use App\Enums\PlanAction;
use App\Enums\PlanCategory;
use App\Enums\PlanPriority;

/**
 * Satu PlanItem dari agen. Satu-satunya tempat pemetaan field kabel -> kolom
 * batch_plan_items (lihat contracts/plan-schema.json).
 */
final readonly class PlanItemData
{
    public const SUBJECT_MAX = 255;

    public const FROM_NAME_MAX = 255;

    /**
     * @param  array<string, mixed>  $reviewData
     */
    public function __construct(
        public string $itemId,
        public string $threadId,
        public ?string $subject,
        public ?string $fromName,
        public PlanCategory $category,
        public PlanPriority $priority,
        public PlanAction $action,
        public array $reviewData,
    ) {
    }

    /**
     * @param  array<string, mixed>  $item
     *
     * @throws InvalidAgentPayload
     */
    public static function fromArray(array $item, int $index = 0): self
    {
        $at = "plan.items[{$index}]";
        $thread = is_array($item['thread'] ?? null) ? $item['thread'] : [];
        $draft = $item['draft'] ?? null;
        $confidence = $item['confidence'] ?? null;

        if ($confidence !== null && (! is_numeric($confidence) || $confidence < 0 || $confidence > 1)) {
            throw InvalidAgentPayload::field("{$at}.confidence");
        }
        if ($draft !== null && ! is_array($draft)) {
            throw InvalidAgentPayload::field("{$at}.draft");
        }

        return new self(
            itemId: self::requiredString($item, 'item_id', $at),
            threadId: self::requiredString($item, 'thread_id', $at),
            subject: self::truncate($thread['subject'] ?? null, self::SUBJECT_MAX),
            fromName: self::truncate($thread['from_name'] ?? null, self::FROM_NAME_MAX),
            category: PlanCategory::tryFrom((string) ($item['category'] ?? ''))
                ?? throw InvalidAgentPayload::field("{$at}.category"),
            priority: PlanPriority::tryFrom((string) ($item['priority'] ?? ''))
                ?? throw InvalidAgentPayload::field("{$at}.priority"),
            action: PlanAction::tryFrom((string) ($item['action'] ?? ''))
                ?? throw InvalidAgentPayload::field("{$at}.action"),
            reviewData: [
                'reason' => (string) ($item['reason'] ?? ''),
                'confidence' => $confidence === null ? null : (float) $confidence,
                'draft' => $draft === null ? null : [
                    'to' => (string) ($draft['to'] ?? ''),
                    'subject' => (string) ($draft['subject'] ?? ''),
                    'body' => (string) ($draft['body'] ?? ''),
                ],
                'warnings' => array_values(array_map(
                    fn ($w) => ['code' => (string) ($w['code'] ?? ''), 'message' => (string) ($w['message'] ?? '')],
                    array_filter((array) ($item['warnings'] ?? []), 'is_array'),
                )),
                'requires_confirmation' => (bool) ($item['requires_confirmation'] ?? false),
                'attachments' => array_values(array_map(
                    fn ($a) => [
                        'filename' => (string) ($a['filename'] ?? ''),
                        'type' => (string) ($a['type'] ?? ''),
                        'size' => (int) ($a['size'] ?? 0),
                    ],
                    array_filter((array) ($thread['attachments'] ?? []), 'is_array'),
                )),
            ],
        );
    }

    /**
     * Kolom kekal (disimpan selamanya untuk riwayat).
     *
     * @return array<string, mixed>
     */
    public function permanentColumns(): array
    {
        return [
            'thread_id' => $this->threadId,
            'subject' => $this->subject,
            'from_name' => $this->fromName,
            'category' => $this->category,
            'priority' => $this->priority,
            'action' => $this->action,
        ];
    }

    /**
     * @param  array<string, mixed>  $item
     */
    private static function requiredString(array $item, string $key, string $at): string
    {
        $value = $item[$key] ?? null;
        if (! is_string($value) || $value === '') {
            throw InvalidAgentPayload::field("{$at}.{$key}", 'wajib berupa string');
        }

        return $value;
    }

    private static function truncate(mixed $value, int $max): ?string
    {
        return is_string($value) ? mb_substr($value, 0, $max) : null;
    }
}
