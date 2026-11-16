<?php

namespace Tests\Feature;

use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\User;
use App\Services\Llm\LlmClient;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ChatAiApiTest extends TestCase
{
    use RefreshDatabase;

    private const SENOPATI = 'https://senopati.test/v1/chat/completions';

    private const OLLAMA = 'http://ollama.test/v1/chat/completions';

    protected function setUp(): void
    {
        parent::setUp();

        config([
            'services.llm.providers' => ['ollama', 'senopati'],
            'services.llm.ollama' => [
                'base_url' => 'http://ollama.test/v1',
                'model' => 'qwen2.5:1.5b',
                'api_key' => '',
            ],
            'services.llm.senopati' => [
                'base_url' => 'https://senopati.test/v1',
                'model' => 'senopati-config-model',
                'api_key' => 'rahasia-uji',
            ],
        ]);
        $this->app->forgetInstance(LlmClient::class);
        Http::preventStrayRequests();
    }

    public function test_tanpa_token_ditolak_401(): void
    {
        $this->postJson('/api/chat-ai', ['prompt' => 'Halo'])->assertUnauthorized();
    }

    public function test_prompt_kosong_ditolak_422(): void
    {
        Sanctum::actingAs(User::factory()->create());

        $this->postJson('/api/chat-ai', ['prompt' => ''])
            ->assertUnprocessable()
            ->assertJsonValidationErrors(['prompt' => 'Prompt wajib diisi.']);
    }

    public function test_prompt_lebih_dari_1000_karakter_ditolak_422(): void
    {
        Sanctum::actingAs(User::factory()->create());

        $this->postJson('/api/chat-ai', ['prompt' => str_repeat('a', 1001)])
            ->assertUnprocessable()
            ->assertJsonValidationErrors(['prompt' => 'Prompt maksimal 1000 karakter.']);
    }

    public function test_sukses_menyimpan_sesi_dan_dua_pesan(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);
        Http::fake([self::OLLAMA => Http::response($this->completion('Ini ringkasannya.', 'qwen2.5:1.5b'))]);

        $response = $this->postJson('/api/chat-ai', ['prompt' => 'Ringkas email dari dosen.']);

        $response->assertOk()
            ->assertExactJsonStructure([
                'status',
                'data' => ['session_id', 'model_used', 'prompt', 'ai_response', 'timestamp'],
            ])
            ->assertJsonPath('status', 'success')
            ->assertJsonPath('data.model_used', 'qwen2.5:1.5b')
            ->assertJsonPath('data.prompt', 'Ringkas email dari dosen.')
            ->assertJsonPath('data.ai_response', 'Ini ringkasannya.');
        $this->assertStringEndsWith('+07:00', $response->json('data.timestamp'));

        $this->assertSame(1, ChatSession::count());
        $session = ChatSession::first();
        $this->assertSame($user->id, $session->user_id);
        $this->assertSame($session->id, $response->json('data.session_id'));
        $this->assertSame(2, ChatMessage::count());

        $assistant = ChatMessage::where('role', 'assistant')->first();
        $this->assertSame('qwen2.5:1.5b', $assistant->model);
        $this->assertSame(12, $assistant->prompt_tokens);
        $this->assertSame(5, $assistant->completion_tokens);
        $this->assertNotNull($assistant->latency_ms);

        Http::assertSent(fn ($request) => $request->url() === self::OLLAMA
            && $request['messages'][0]['role'] === 'system'
            && $request['messages'][1]['content'] === 'Ringkas email dari dosen.'
            && ! $request->hasHeader('Authorization'));
    }

    public function test_session_id_milik_user_lain_404(): void
    {
        $other = ChatSession::factory()->create();
        Sanctum::actingAs(User::factory()->create());
        Http::fake();

        $this->postJson('/api/chat-ai', ['prompt' => 'Halo', 'session_id' => $other->id])
            ->assertNotFound();

        Http::assertNothingSent();
    }

    public function test_ollama_500_fallback_ke_senopati(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([
            self::OLLAMA => Http::response('error', 500),
            self::SENOPATI => Http::response($this->completion('Jawaban Senopati.', 'senopati-model')),
        ]);

        $this->postJson('/api/chat-ai', ['prompt' => 'Halo'])
            ->assertOk()
            ->assertJsonPath('data.model_used', 'senopati-model');

        Http::assertSent(fn ($request) => $request->url() === self::SENOPATI
            && $request->hasHeader('Authorization', 'Bearer rahasia-uji'));
    }

    public function test_ollama_tidak_terhubung_fallback_ke_senopati(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([
            self::OLLAMA => fn () => throw new ConnectionException('Connection refused'),
            self::SENOPATI => Http::response($this->completion('Jawaban Senopati.', 'senopati-model')),
        ]);

        $this->postJson('/api/chat-ai', ['prompt' => 'Halo'])
            ->assertOk()
            ->assertJsonPath('data.model_used', 'senopati-model');
    }

    public function test_semua_provider_gagal_503_tanpa_pesan_tersimpan(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([
            self::OLLAMA => Http::response('error', 500),
            self::SENOPATI => Http::response('rate limited', 429),
        ]);

        $this->postJson('/api/chat-ai', ['prompt' => 'Halo'])
            ->assertStatus(503)
            ->assertExactJson([
                'status' => 'error',
                'message' => 'Layanan LLM sedang tidak tersedia.',
            ]);

        $this->assertSame(0, ChatMessage::count());
        $this->assertSame(0, ChatSession::count());
    }

    public function test_session_id_milik_sendiri_mengirim_riwayat(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create();
        $session->messages()->create(['role' => 'user', 'content' => 'Pesan lama']);
        $session->messages()->create(['role' => 'assistant', 'content' => 'Jawaban lama']);
        Sanctum::actingAs($user);
        Http::fake([self::OLLAMA => Http::response($this->completion('Lanjutan.', 'qwen2.5:1.5b'))]);

        $this->postJson('/api/chat-ai', ['prompt' => 'Lanjut', 'session_id' => $session->id])
            ->assertOk()
            ->assertJsonPath('data.session_id', $session->id);

        $this->assertSame(4, $session->messages()->count());
        Http::assertSent(fn ($request) => array_column($request['messages'], 'content') === [
            LlmClient::SYSTEM_PROMPT, 'Pesan lama', 'Jawaban lama', 'Lanjut',
        ]);
    }

    /**
     * @return array<string, mixed>
     */
    private function completion(string $content, string $model): array
    {
        return [
            'model' => $model,
            'choices' => [['message' => ['role' => 'assistant', 'content' => $content]]],
            'usage' => ['prompt_tokens' => 12, 'completion_tokens' => 5, 'total_tokens' => 17],
        ];
    }
}
