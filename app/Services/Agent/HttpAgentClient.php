<?php

namespace App\Services\Agent;

use App\Models\Batch;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Factory as HttpFactory;
use Illuminate\Http\Client\Response;
use Illuminate\Support\Facades\Log;
use SensitiveParameter;
use stdClass;

final class HttpAgentClient implements AgentClient
{
    public function __construct(
        private readonly HttpFactory $http,
        private readonly string $url,
        #[SensitiveParameter] private readonly string $token,
        private readonly int $timeout,
    ) {
    }

    public function startBatch(int $userId, array $filters): string
    {
        $payload = $this->object($this->request($userId, 'POST', '/v1/batches', 202, ['filters' => $filters]));
        $this->expectStatus($payload, 'queued');
        $id = $payload->batch_id ?? null;
        if (! is_string($id) || trim($id) === '' || strlen($id) > 255 || in_array($id, ['.', '..'], true)) {
            throw InvalidAgentPayload::field('batch_id');
        }

        return $id;
    }

    public function getBatch(int $userId, string $agentBatchId): array
    {
        $response = $this->request($userId, 'GET', $this->batchPath($agentBatchId), 200);

        return BatchSnapshotValidator::validate($this->object($response), $response->json(flags: 0), $agentBatchId);
    }

    public function execute(int $userId, string $agentBatchId, int $planVersion, #[SensitiveParameter] array $decisions): void
    {
        $payload = $this->object($this->request($userId, 'POST', $this->batchPath($agentBatchId) . '/execute', 202, [
            'plan_version' => $planVersion,
            'decisions' => $decisions,
        ], executing: true));
        $this->expectStatus($payload, 'executing');
    }

    public function cancel(int $userId, string $agentBatchId): void
    {
        $payload = $this->object($this->request($userId, 'POST', $this->batchPath($agentBatchId) . '/cancel', 202));
        $this->expectStatus($payload, 'cancelled');
    }

    public function getGmailStatus(int $userId): array
    {
        $payload = $this->object($this->request($userId, 'GET', '/v1/auth/status', 200));
        $status = $payload->status ?? null;
        if (! in_array($status, ['connected', 'not_connected', 'expired'], true)) {
            throw InvalidAgentPayload::field('status');
        }

        return ['status' => $status];
    }

    public function startGmailLogin(int $userId): array
    {
        $payload = $this->object($this->request($userId, 'POST', '/v1/auth/login', 200));
        $url = $payload->auth_url ?? null;
        $parts = is_string($url) && filter_var($url, FILTER_VALIDATE_URL) !== false ? parse_url($url) : false;
        if ($parts === false || strtolower($parts['scheme'] ?? '') !== 'https'
            || strtolower($parts['host'] ?? '') !== 'accounts.google.com'
            || ($parts['port'] ?? 443) !== 443 || isset($parts['user']) || isset($parts['pass'])) {
            throw InvalidAgentPayload::field('auth_url');
        }

        return ['auth_url' => $url];
    }

    private function batchPath(string $id): string
    {
        if ($id === '' || in_array($id, ['.', '..'], true)) {
            throw new AgentUnavailable('ID batch untuk permintaan agen tidak valid.', agentCode: 'invalid_request');
        }

        return '/v1/batches/' . rawurlencode($id);
    }

    private function request(
        int $userId,
        string $method,
        string $path,
        int $expectedStatus,
        #[SensitiveParameter] ?array $body = null,
        bool $executing = false,
    ): Response {
        $base = filter_var($this->url, FILTER_VALIDATE_URL) !== false ? parse_url($this->url) : false;
        if ($base === false || ! in_array($base['scheme'] ?? null, ['http', 'https'], true)
            || isset($base['user']) || isset($base['pass']) || isset($base['query']) || isset($base['fragment'])
            || $this->timeout < 1 || $this->timeout > Batch::MAX_HTTP_TIMEOUT) {
            throw new AgentUnavailable('Konfigurasi URL atau timeout agen tidak valid.');
        }
        if ($this->token === '' || preg_match('/[^\x21-\x7e]/', $this->token) === 1) {
            Log::warning('Token HTTP agen belum dikonfigurasi dengan benar.', ['code' => 'unauthorized']);

            throw new AgentUnavailable('Token HTTP agen belum dikonfigurasi dengan benar.', agentCode: 'unauthorized');
        }

        try {
            $response = $this->http->acceptJson()
                ->withToken($this->token)
                ->withHeaders(['X-User-Id' => (string) $userId])
                ->withoutRedirecting()
                ->timeout($this->timeout)
                ->send($method, rtrim($this->url, '/') . $path, $body === null ? [] : ['json' => $body]);
        } catch (ConnectionException) {
            throw new AgentUnavailable('Koneksi HTTP ke agen gagal atau melewati batas waktu.');
        }

        if (! $response->successful()) {
            $this->throwAgentError($response, $executing);
        }
        if ($response->status() !== $expectedStatus) {
            throw InvalidAgentPayload::field('http_status');
        }

        return $response;
    }

    private function throwAgentError(#[SensitiveParameter] Response $response, bool $executing): never
    {
        $status = $response->status();
        $error = $response->object(0)->error ?? null;
        $allowed = match ($status) {
            401 => ['unauthorized'],
            404 => ['batch_not_found'],
            409 => ['plan_version_mismatch', 'invalid_state', 'gmail_not_connected'],
            422 => ['invalid_request'],
            503 => ['llm_unavailable', 'gmail_unavailable'],
            default => [],
        };
        $code = $error instanceof stdClass && is_string($error->message ?? null)
            && in_array($error->code ?? null, $allowed, true) ? $error->code : null;

        if ($status === 401 || $status === 422) {
            Log::warning('Permintaan HTTP ke agen ditolak. Periksa konfigurasi atau payload Laravel.', [
                'http_status' => $status,
                'code' => $code,
            ]);
        }
        if ($executing && in_array($code, ['plan_version_mismatch', 'invalid_state'], true)) {
            throw new PlanVersionMismatch('Agen menolak eksekusi berdasarkan versi atau status batch.', agentCode: $code);
        }

        throw new AgentUnavailable('Agen menolak permintaan HTTP.', $status, agentCode: $code);
    }

    private function object(#[SensitiveParameter] Response $response): stdClass
    {
        $payload = $response->object(0);
        if (! $payload instanceof stdClass) {
            throw InvalidAgentPayload::field('response', 'wajib berupa objek JSON');
        }

        return $payload;
    }

    private function expectStatus(#[SensitiveParameter] stdClass $payload, string $expected): void
    {
        if (($payload->status ?? null) !== $expected) {
            throw InvalidAgentPayload::field('status');
        }
    }
}
