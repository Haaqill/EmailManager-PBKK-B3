<?php

namespace Tests\Feature;

use App\Enums\BatchStatus;
use App\Enums\PlanDecision;
use App\Jobs\RunBatchOperationJob;
use App\Jobs\SyncBatchStatusJob;
use App\Models\User;
use App\Services\Agent\AgentClient;
use App\Services\Agent\AgentUnavailable;
use App\Services\Agent\HttpAgentClient;
use App\Services\Agent\InvalidAgentPayload;
use App\Services\Agent\PlanVersionMismatch;
use Closure;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class HttpAgentClientTest extends TestCase
{
    use RefreshDatabase;

    private const URL = 'http://127.0.0.1:8123';

    private const TOKEN = 'token-fixture';

    private const BATCH_PATH = '/v1/batches/b_fiktif_0001';

    protected function setUp(): void
    {
        parent::setUp();
        config(['agent.driver' => 'http', 'agent.url' => self::URL . '/', 'agent.token' => self::TOKEN]);
        Http::preventStrayRequests();
    }

    private function fixture(string $status): array
    {
        return json_decode(file_get_contents(base_path("tests/Fixtures/agent/batch_{$status}.json")), true, flags: JSON_THROW_ON_ERROR);
    }

    public function test_enam_operasi_memakai_endpoint_header_dan_body_sesuai_kontrak(): void
    {
        $snapshot = $this->fixture('awaiting_review');
        $loginUrl = 'https://accounts.google.com/o/oauth2/v2/auth?state=state-fixture';
        Http::fake(function (Request $request, array $options) use ($snapshot, $loginUrl) {
            $this->assertSame(10, $options['timeout']);
            $this->assertFalse($options['allow_redirects']);

            return match ($request->url()) {
                self::URL . '/v1/batches' => Http::response(['batch_id' => $snapshot['batch_id'], 'status' => 'queued'], 202),
                self::URL . self::BATCH_PATH => Http::response($snapshot),
                self::URL . self::BATCH_PATH . '/execute' => Http::response(['status' => 'executing'], 202),
                self::URL . self::BATCH_PATH . '/cancel' => Http::response(['status' => 'cancelled'], 202),
                self::URL . '/v1/auth/status' => Http::response(['status' => 'connected']),
                self::URL . '/v1/auth/login' => Http::response(['auth_url' => $loginUrl]),
                default => null,
            };
        });

        $agent = app(AgentClient::class);
        $this->assertInstanceOf(HttpAgentClient::class, $agent);
        $id = $agent->startBatch(12, ['max_results' => 3]);
        $decisions = [
            ['item_id' => 'i_01', 'decision' => 'approve', 'edited_draft_body' => 'Draf uji'],
            ['item_id' => 'i_02', 'decision' => 'approve', 'confirmed_trash' => true],
        ];
        $this->assertSame($snapshot['batch_id'], $id);
        $this->assertSame($snapshot, $agent->getBatch(12, $id));
        $agent->execute(12, $id, 1, $decisions);
        $agent->cancel(12, $id);
        $this->assertSame(['status' => 'connected'], $agent->getGmailStatus(34));
        $this->assertSame(['auth_url' => $loginUrl], $agent->startGmailLogin(34));

        Http::assertSentInOrder([
            $this->requestIs('POST', '/v1/batches', 12, ['filters' => ['max_results' => 3]]),
            $this->requestIs('GET', self::BATCH_PATH, 12),
            $this->requestIs('POST', self::BATCH_PATH . '/execute', 12, ['plan_version' => 1, 'decisions' => $decisions]),
            $this->requestIs('POST', self::BATCH_PATH . '/cancel', 12),
            $this->requestIs('GET', '/v1/auth/status', 34),
            $this->requestIs('POST', '/v1/auth/login', 34),
        ]);
        Http::assertSentCount(6);
    }

    private function requestIs(string $method, string $path, int $userId, ?array $body = null): Closure
    {
        return fn (Request $request) => $request->method() === $method
            && $request->url() === self::URL . $path
            && $request->hasHeader('Authorization', 'Bearer ' . self::TOKEN)
            && $request->hasHeader('X-User-Id', (string) $userId)
            && $request->hasHeader('Accept', 'application/json')
            && ($body === null ? $request->body() === '' : $request->data() === $body);
    }

    public function test_status_gmail_menangani_akun_belum_terhubung_dan_kedaluwarsa(): void
    {
        config(['agent.timeout' => 7]);
        $responses = Http::sequence()->push(['status' => 'not_connected'])->push(['status' => 'expired']);
        Http::fake(function (Request $request, array $options) use ($responses) {
            $this->assertSame(7, $options['timeout']);

            return $responses($request);
        });
        $agent = app(AgentClient::class);

        $this->assertSame(['status' => 'not_connected'], $agent->getGmailStatus(12));
        $this->assertSame(['status' => 'expired'], $agent->getGmailStatus(34));
    }

    public static function unavailableErrors(): array
    {
        return [
            'token' => [401, 'unauthorized'],
            'batch asing' => [404, 'batch_not_found'],
            'gmail belum terhubung' => [409, 'gmail_not_connected'],
            'request invalid' => [422, 'invalid_request'],
            'LLM tidak tersedia' => [503, 'llm_unavailable'],
            'Gmail tidak tersedia' => [503, 'gmail_unavailable'],
        ];
    }

    #[DataProvider('unavailableErrors')]
    public function test_galat_agen_dipetakan_dengan_kode_aman(int $status, string $code): void
    {
        Log::spy();
        Http::fake([self::URL . '/v1/batches' => Http::response([
            'error' => ['code' => $code, 'message' => 'isi email dan token privat'],
        ], $status)]);

        try {
            app(AgentClient::class)->startBatch(12, ['max_results' => 3]);
            $this->fail('AgentUnavailable wajib dilempar.');
        } catch (AgentUnavailable $error) {
            $this->assertSame($code, $error->agentCode);
            $this->assertSame($code, $error->safeCode());
            $this->assertSame('Agen menolak permintaan HTTP.', $error->getMessage());
            $this->assertNull($error->getPrevious());
        }

        if (in_array($status, [401, 422], true)) {
            Log::shouldHaveReceived('warning')->once()->with(
                'Permintaan HTTP ke agen ditolak. Periksa konfigurasi atau payload Laravel.',
                ['http_status' => $status, 'code' => $code],
            );
        } else {
            Log::shouldNotHaveReceived('warning');
        }
        Http::assertSentCount(1);
    }

    public static function executeConflicts(): array
    {
        return [['plan_version_mismatch'], ['invalid_state']];
    }

    #[DataProvider('executeConflicts')]
    public function test_konflik_eksekusi_meminta_review_ulang(string $code): void
    {
        Http::fake([self::URL . self::BATCH_PATH . '/execute' => Http::response([
            'error' => ['code' => $code, 'message' => 'rincian privat'],
        ], 409)]);

        try {
            app(AgentClient::class)->execute(12, 'b_fiktif_0001', 1, []);
            $this->fail('PlanVersionMismatch wajib dilempar.');
        } catch (PlanVersionMismatch $error) {
            $this->assertSame($code, $error->agentCode);
            $this->assertStringNotContainsString('rincian privat', $error->getMessage());
        }
        Http::assertSentCount(1);
    }

    public function test_invalid_state_saat_batal_mempertahankan_kode_yang_dibaca_worker(): void
    {
        Http::fake([self::URL . self::BATCH_PATH . '/cancel' => Http::response([
            'error' => ['code' => 'invalid_state', 'message' => 'status tidak mengizinkan pembatalan'],
        ], 409)]);

        try {
            app(AgentClient::class)->cancel(12, 'b_fiktif_0001');
            $this->fail('AgentUnavailable wajib dilempar.');
        } catch (AgentUnavailable $error) {
            $this->assertSame('invalid_state', $error->safeCode());
        }
    }

    public static function transportFailures(): array
    {
        return [
            'timeout start' => ['startBatch', 'cURL error 28: timeout'],
            'login koneksi gagal' => ['startGmailLogin', 'cURL error 7: connection refused'],
        ];
    }

    #[DataProvider('transportFailures')]
    public function test_kegagalan_transport_tidak_mengulang_post_atau_membawa_exception_asli(string $method, string $message): void
    {
        $attempts = 0;
        Http::fake(function (Request $request) use ($message, &$attempts) {
            $attempts++;

            return Http::failedConnection($message . ' ' . self::TOKEN)($request);
        });
        $agent = app(AgentClient::class);

        try {
            $method === 'startBatch' ? $agent->startBatch(12, ['max_results' => 3]) : $agent->startGmailLogin(12);
            $this->fail('AgentUnavailable wajib dilempar.');
        } catch (AgentUnavailable $error) {
            $this->assertSame('agent_unavailable', $error->safeCode());
            $this->assertStringNotContainsString(self::TOKEN, $error->getMessage());
            $this->assertNull($error->getPrevious());
        }
        $this->assertSame(1, $attempts);
    }

    public function test_respons_galat_nonkontrak_tidak_menutup_batch_sebagai_404_agen(): void
    {
        Http::fake([self::URL . self::BATCH_PATH => Http::response('404 proxy: info privat', 404)]);

        try {
            app(AgentClient::class)->getBatch(12, 'b_fiktif_0001');
            $this->fail('AgentUnavailable wajib dilempar.');
        } catch (AgentUnavailable $error) {
            $this->assertNull($error->agentCode);
            $this->assertSame('agent_unavailable', $error->safeCode());
            $this->assertStringNotContainsString('info privat', $error->getMessage());
        }
    }

    public function test_konfigurasi_token_kosong_ditolak_tanpa_request(): void
    {
        config(['agent.token' => '']);
        Log::spy();
        Http::fake();

        try {
            app(AgentClient::class)->getGmailStatus(12);
            $this->fail('AgentUnavailable wajib dilempar.');
        } catch (AgentUnavailable $error) {
            $this->assertSame('unauthorized', $error->safeCode());
        }

        Http::assertNothingSent();
        Log::shouldHaveReceived('warning')->once()->with(
            'Token HTTP agen belum dikonfigurasi dengan benar.',
            ['code' => 'unauthorized'],
        );
    }

    public function test_timeout_yang_melampaui_anggaran_worker_ditolak_sebelum_koneksi(): void
    {
        config(['agent.timeout' => 21]);
        Http::fake();

        try {
            app(AgentClient::class)->getGmailStatus(12);
            $this->fail('Timeout di atas anggaran worker harus ditolak.');
        } catch (AgentUnavailable $error) {
            $this->assertSame('Konfigurasi URL atau timeout agen tidak valid.', $error->getMessage());
        }
        Http::assertNothingSent();
    }

    public static function invalidResponses(): array
    {
        return [
            'JSON terpotong' => ['startBatch', '{"batch_id":', 202],
            'bentuk daftar' => ['startBatch', '[{"batch_id":"b_1","status":"queued"}]', 202],
            'HTTP sukses yang salah' => ['startBatch', ['batch_id' => 'b_1', 'status' => 'queued'], 200],
            'ID kosong' => ['startBatch', ['batch_id' => '', 'status' => 'queued'], 202],
            'status awal salah' => ['startBatch', ['batch_id' => 'b_1', 'status' => 'done'], 202],
            'status eksekusi salah' => ['execute', ['status' => 'done'], 202],
            'status batal salah' => ['cancel', [], 202],
            'status Gmail salah' => ['getGmailStatus', ['status' => 'connecting'], 200],
            'URL login host lain' => ['startGmailLogin', ['auth_url' => 'https://accounts.google.com.example.test/'], 200],
            'URL login memakai userinfo' => ['startGmailLogin', ['auth_url' => 'https://ref@accounts.google.com/'], 200],
        ];
    }

    #[DataProvider('invalidResponses')]
    public function test_respons_sukses_nonkontrak_ditolak(string $operation, array|string $body, int $httpStatus): void
    {
        Http::fake([self::URL . '/v1/*' => Http::response($body, $httpStatus)]);
        $agent = app(AgentClient::class);

        $this->expectException(InvalidAgentPayload::class);
        match ($operation) {
            'startBatch' => $agent->startBatch(12, ['max_results' => 3]),
            'execute' => $agent->execute(12, 'b_fiktif_0001', 1, []),
            'cancel' => $agent->cancel(12, 'b_fiktif_0001'),
            default => $agent->{$operation}(12),
        };
    }

    public static function invalidSnapshots(): array
    {
        return [
            'batch berbeda' => ['batch_id', 'b_lain', 'batch_id'],
            'expired lokal' => ['status', 'expired', 'status'],
            'versi string' => ['plan.plan_version', '1', 'plan'],
            'items objek kosong' => ['plan.items', (object) [], 'plan'],
            'missing plan review' => ['plan', null, 'plan'],
            'done tanpa laporan' => ['report', null, 'report'],
            'enum aksi salah' => ['plan.items.0.action', 'send', 'plan'],
            'confidence bukan enum' => ['plan.items.0.confidence', '', 'plan.items.confidence'],
            'draft kosong' => ['plan.items.0.draft', null, 'plan.items.draft'],
            'trash tanpa konfirmasi' => ['plan.items.1.requires_confirmation', false, 'plan.items.requires_confirmation'],
            'status hasil invalid' => ['report.results.0.status', 'unknown', 'report.results'],
        ];
    }

    #[DataProvider('invalidSnapshots')]
    public function test_snapshot_batch_memvalidasi_bentuk_dan_field_bersarang(string $key, mixed $value, string $field): void
    {
        $snapshot = $this->fixture($key === 'plan' ? 'awaiting_review' : 'done');
        data_set($snapshot, $key, $value);
        Http::fake([self::URL . self::BATCH_PATH => Http::response($snapshot)]);

        $this->expectException(InvalidAgentPayload::class);
        $this->expectExceptionMessage("Payload agen: {$field} tidak valid.");
        app(AgentClient::class)->getBatch(12, 'b_fiktif_0001');
    }

    public function test_worker_bisa_sinkronisasi_mengeksekusi_dan_menyimpan_laporan_dengan_driver_http(): void
    {
        $review = $this->fixture('awaiting_review');
        $done = $this->fixture('done');
        $batch = User::factory()->create()->batches()->create([
            'agent_batch_id' => $review['batch_id'],
            'status' => BatchStatus::Queued,
        ]);
        Http::fake([
            self::URL . self::BATCH_PATH => Http::sequence()->push($review)->push($review)->push($done),
            self::URL . self::BATCH_PATH . '/execute' => Http::response(['status' => 'executing'], 202),
        ]);
        $syncJob = new SyncBatchStatusJob($batch->id);
        app()->call([$syncJob, 'handle']);

        $batch->refresh();
        $this->assertSame(BatchStatus::AwaitingReview, $batch->status);
        $batch->items()->where('item_id', 'i_01')->update(['decision' => PlanDecision::Approve]);
        $batch->update(['pending_operation' => [
            'id' => 'test-execute',
            'type' => RunBatchOperationJob::EXECUTE,
            'plan_version' => $batch->plan_version,
            'attempts' => 0,
        ]]);
        app()->call([new RunBatchOperationJob($batch->id, 'test-execute'), 'handle']);
        $this->assertSame(BatchStatus::Executing, $batch->fresh()->status);
        $this->assertNull($batch->fresh()->pending_operation);
        Http::assertSent($this->requestIs('POST', self::BATCH_PATH . '/execute', $batch->user_id, [
            'plan_version' => 1,
            'decisions' => [['item_id' => 'i_01', 'decision' => 'approve']],
        ]));

        app()->call([$syncJob, 'handle']);

        $this->assertSame(BatchStatus::Done, $batch->fresh()->status);
        $this->assertSame($done['report']['summary'], $batch->fresh()->summary);
        $this->assertSame(0, $batch->items()->whereNotNull('review_data')->count());
        Http::assertSentCount(4);
    }
}
