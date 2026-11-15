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

class ChatAiStreamApiTest extends TestCase
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
        $this->postJson('/api/chat-ai/stream', ['prompt' => 'Halo'])->assertUnauthorized();
    }

    public function test_prompt_kosong_ditolak_422(): void
    {
        Sanctum::actingAs(User::factory()->create());

        $this->postJson('/api/chat-ai/stream', ['prompt' => ''])
            ->assertUnprocessable()
            ->assertJsonValidationErrors(['prompt' => 'Prompt wajib diisi.']);
    }

    public function test_stream_mengirim_delta_lalu_done_dan_menyimpan_pesan(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);
        Http::fake([self::OLLAMA => Http::response($this->sse(['Halo', ', ini', ' ringkasannya.'], 'qwen2.5:1.5b'))]);

        $response = $this->postJson('/api/chat-ai/stream', ['prompt' => 'Ringkas email dosen.']);

        $response->assertOk();
        $this->assertStringStartsWith('text/event-stream', $response->headers->get('Content-Type'));
        $events = $this->events($response->streamedContent());

        $this->assertSame(['delta', 'delta', 'delta', 'done'], array_column($events, 'event'));
        $this->assertSame('Halo', $events[0]['data']['content']);

        $done = $events[3]['data'];
        $this->assertSame('success', $done['status']);
        $this->assertSame('qwen2.5:1.5b', $done['data']['model_used']);
        $this->assertSame('Ringkas email dosen.', $done['data']['prompt']);
        $this->assertSame('Halo, ini ringkasannya.', $done['data']['ai_response']);
        $this->assertStringEndsWith('+07:00', $done['data']['timestamp']);

        $this->assertSame(1, ChatSession::count());
        $this->assertSame(ChatSession::first()->id, $done['data']['session_id']);
        $assistant = ChatMessage::where('role', 'assistant')->first();
        $this->assertSame('Halo, ini ringkasannya.', $assistant->content);
        $this->assertSame(12, $assistant->prompt_tokens);
        $this->assertSame(5, $assistant->completion_tokens);
        $this->assertSame(2, ChatMessage::count());

        Http::assertSent(fn ($request) => $request['stream'] === true
            && $request['stream_options'] === ['include_usage' => true]);
    }

    public function test_session_id_milik_user_lain_404_tanpa_memanggil_llm(): void
    {
        $other = ChatSession::factory()->create();
        Sanctum::actingAs(User::factory()->create());
        Http::fake();

        $this->postJson('/api/chat-ai/stream', ['prompt' => 'Halo', 'session_id' => $other->id])
            ->assertNotFound();

        Http::assertNothingSent();
    }

    public function test_ollama_gagal_fallback_ke_senopati_sebelum_stream(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([
            self::OLLAMA => fn () => throw new ConnectionException('Connection refused'),
            self::SENOPATI => Http::response($this->sse(['Jawaban', ' Senopati.'], 'senopati-model')),
        ]);

        $events = $this->events(
            $this->postJson('/api/chat-ai/stream', ['prompt' => 'Halo'])->assertOk()->streamedContent()
        );

        $this->assertSame('done', end($events)['event']);
        $this->assertSame('senopati-model', end($events)['data']['data']['model_used']);
    }

    public function test_semua_provider_gagal_503_json_tanpa_pesan_tersimpan(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([
            self::OLLAMA => Http::response('error', 500),
            self::SENOPATI => Http::response('rate limited', 429),
        ]);

        $this->postJson('/api/chat-ai/stream', ['prompt' => 'Halo'])
            ->assertStatus(503)
            ->assertExactJson([
                'status' => 'error',
                'message' => 'Layanan LLM sedang tidak tersedia.',
            ]);

        $this->assertSame(0, ChatMessage::count());
    }

    public function test_stream_tanpa_isi_mengirim_event_error_tanpa_pesan_tersimpan(): void
    {
        Sanctum::actingAs(User::factory()->create());
        Http::fake([self::OLLAMA => Http::response("data: [DONE]\n\n")]);

        $events = $this->events(
            $this->postJson('/api/chat-ai/stream', ['prompt' => 'Halo'])->assertOk()->streamedContent()
        );

        $this->assertSame(['error'], array_column($events, 'event'));
        $this->assertSame('error', $events[0]['data']['status']);
        $this->assertSame(0, ChatMessage::count());
        $this->assertSame(0, ChatSession::count());
    }

    /**
     * @param  list<string>  $pieces
     */
    private function sse(array $pieces, string $model): string
    {
        $lines = [];
        foreach ($pieces as $piece) {
            $lines[] = 'data: ' . json_encode([
                'model' => $model,
                'choices' => [['index' => 0, 'delta' => ['content' => $piece]]],
            ]);
        }
        $lines[] = 'data: ' . json_encode([
            'model' => $model,
            'choices' => [],
            'usage' => ['prompt_tokens' => 12, 'completion_tokens' => 5, 'total_tokens' => 17],
        ]);
        $lines[] = 'data: [DONE]';

        return implode("\n\n", $lines) . "\n\n";
    }

    /**
     * @return list<array{event: string, data: array<string, mixed>}>
     */
    private function events(string $body): array
    {
        $events = [];
        foreach (preg_split('/\n\n/', trim($body)) as $block) {
            preg_match('/^event: (.+)$/m', $block, $event);
            preg_match('/^data: (.+)$/m', $block, $data);
            $events[] = ['event' => $event[1], 'data' => json_decode($data[1], true)];
        }

        return $events;
    }
}
