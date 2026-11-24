<?php

namespace App\Services\Agent;

use App\Enums\BatchStatus;
use App\Enums\PlanAction;
use App\Enums\PlanCategory;
use App\Enums\PlanConfidence;
use App\Enums\PlanPriority;
use Illuminate\Support\Facades\Validator;
use Illuminate\Validation\Rule;
use SensitiveParameter;
use stdClass;

final class BatchSnapshotValidator
{
    /**
     * @param  array<string, mixed>  $payload
     * @return array<string, mixed>
     */
    public static function validate(
        #[SensitiveParameter] stdClass $snapshot,
        #[SensitiveParameter] array $payload,
        string $expectedBatchId,
    ): array {
        if (($snapshot->batch_id ?? null) !== $expectedBatchId) {
            throw InvalidAgentPayload::field('batch_id');
        }
        $status = is_string($snapshot->status ?? null) ? BatchStatus::tryFrom($snapshot->status) : null;
        if ($status === null || $status === BatchStatus::Expired) {
            throw InvalidAgentPayload::field('status');
        }
        if (isset($snapshot->filters) && ! $snapshot->filters instanceof stdClass) {
            throw InvalidAgentPayload::field('filters');
        }

        $plan = $snapshot->plan ?? null;
        if (($plan !== null || $status->inReview()) && (! $plan instanceof stdClass || ! is_array($plan->items ?? null))) {
            throw InvalidAgentPayload::field('plan');
        }
        if ($plan !== null) {
            self::validatePlan($plan, $payload['plan']);
        }

        $report = $snapshot->report ?? null;
        if ($status === BatchStatus::Done && $report === null) {
            throw InvalidAgentPayload::field('report');
        }
        if ($report !== null) {
            if (! $report instanceof stdClass || ! ($report->summary ?? null) instanceof stdClass
                || ! is_array($report->results ?? null)) {
                throw InvalidAgentPayload::field('report');
            }
            self::validateReport($report, $payload['report']);
        }

        return $payload;
    }

    private static function validatePlan(#[SensitiveParameter] stdClass $plan, #[SensitiveParameter] array $payload): void
    {
        if (array_diff_key($payload, ['plan_version' => true, 'items' => true]) !== [] || Validator::make($payload, [
            'plan_version' => ['required', 'integer:strict', 'min:1'],
            'items' => ['present', 'array', 'list'],
            'items.*' => ['array:item_id,thread_id,thread,category,priority,action,also_archive,reason,confidence,draft,warnings,requires_confirmation'],
            'items.*.item_id' => ['required', 'string', 'regex:/\Ai_[0-9]{2,}\z/', 'max:255', 'distinct:strict'],
            'items.*.thread_id' => ['required', 'string', 'max:255'],
            'items.*.thread' => ['required', 'array:subject,from_name,from_domain,date,attachments'],
            'items.*.thread.subject' => ['present', 'string'],
            'items.*.thread.from_name' => ['present', 'string'],
            'items.*.thread.from_domain' => ['present', 'string'],
            'items.*.thread.date' => ['present', 'string'],
            'items.*.thread.attachments' => ['sometimes', 'array', 'list'],
            'items.*.thread.attachments.*' => ['array:filename,type,size'],
            'items.*.thread.attachments.*.filename' => ['present', 'string'],
            'items.*.thread.attachments.*.type' => ['present', 'string'],
            'items.*.thread.attachments.*.size' => ['required', 'integer:strict', 'min:0'],
            'items.*.category' => ['required', Rule::enum(PlanCategory::class)],
            'items.*.priority' => ['required', Rule::enum(PlanPriority::class)],
            'items.*.action' => ['required', Rule::enum(PlanAction::class)],
            'items.*.reason' => ['present', 'string'],
            'items.*.draft' => ['nullable', 'array:to,subject,body'],
            'items.*.warnings' => ['sometimes', 'array', 'list'],
            'items.*.warnings.*' => ['array:code,message'],
            'items.*.warnings.*.code' => ['required', Rule::in([
                'REPLY_TO_DOMAIN_MISMATCH', 'NEW_RECIPIENT', 'CROSS_THREAD_DATA', 'UNRESOLVED_PLACEHOLDER',
            ])],
            'items.*.warnings.*.message' => ['present', 'string'],
            'items.*.requires_confirmation' => ['required', 'boolean:strict'],
        ])->fails()) {
            throw InvalidAgentPayload::field('plan');
        }

        foreach ($plan->items as $item) {
            if (! $item instanceof stdClass) {
                throw InvalidAgentPayload::field('plan.items');
            }
            $draft = $item->draft ?? null;
            $confidence = $item->confidence ?? null;
            $alsoArchive = property_exists($item, 'also_archive') ? $item->also_archive : false;
            $isReply = $item->action === PlanAction::DraftReply->value;
            if ($confidence !== null && (! is_string($confidence) || PlanConfidence::tryFrom($confidence) === null)) {
                throw InvalidAgentPayload::field('plan.items.confidence');
            }
            if ($isReply !== ($draft instanceof stdClass)
                || ($draft !== null && (! is_string($draft->to ?? null) || ! is_string($draft->subject ?? null) || ! is_string($draft->body ?? null)))) {
                throw InvalidAgentPayload::field('plan.items.draft');
            }
            if (! is_bool($alsoArchive) || ($alsoArchive && ! $isReply)) {
                throw InvalidAgentPayload::field('plan.items.also_archive');
            }
            if ($item->requires_confirmation !== ($item->action === PlanAction::Trash->value)) {
                throw InvalidAgentPayload::field('plan.items.requires_confirmation');
            }
            if (! is_array($item->warnings ?? []) || ! is_array($item->thread->attachments ?? [])) {
                throw InvalidAgentPayload::field('plan.items');
            }
        }
    }

    private static function validateReport(#[SensitiveParameter] stdClass $report, #[SensitiveParameter] array $payload): void
    {
        if (Validator::make($payload, [
            'results.*' => ['array'],
            'results.*.item_id' => ['required', 'string', 'regex:/\Ai_[0-9]{2,}\z/', 'max:255', 'distinct:strict'],
            'results.*.status' => ['required', Rule::in(['ok', 'failed', 'skipped', 'rejected'])],
            'results.*.applied' => ['nullable', 'array'],
            'results.*.applied.labels' => ['sometimes', 'array', 'list'],
            'results.*.applied.labels.*' => ['string'],
            'results.*.applied.draft_id' => ['nullable', 'string'],
        ])->fails()) {
            throw InvalidAgentPayload::field('report.results');
        }

        foreach ($report->results as $result) {
            if (! $result instanceof stdClass) {
                throw InvalidAgentPayload::field('report.results');
            }
            $applied = $result->applied ?? null;
            if ($applied !== null && (! $applied instanceof stdClass
                || ! is_array($applied->labels ?? [])
                || (property_exists($applied, 'archived') && ! is_bool($applied->archived)))) {
                throw InvalidAgentPayload::field('report.results.applied');
            }
        }
    }
}
