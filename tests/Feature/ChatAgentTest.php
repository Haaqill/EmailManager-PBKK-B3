<?php

namespace Tests\Feature;

use App\Livewire\ChatAgent;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\User;
use App\Services\Llm\LlmClient;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Livewire\Livewire;
use Tests\TestCase;

class ChatAgentTest extends TestCase
{
    use RefreshDatabase;

    private const SENOPATI = 'https://senopati.test/v1/chat/completions';

    private const OLLAMA = 'http://ollama.test/v1/chat/completions';

    protected function setUp(): void
    {
        parent::setUp();

        config([
            'services.llm.providers' => ['senopati', 'ollama'],
            'services.llm.senopati' => [
                'base_url' => 'https://senopati.test/v1',
                'model' => 'qwen3:14b',
                'api_key' => 'rahasia-uji',
            ],
            'services.llm.ollama' => [
                'base_url' => 'http://ollama.test/v1',
                'model' => 'qwen3:4b',
                'api_key' => '',
            ],
        ]);
        $this->app->forgetInstance(LlmClient::class);
        Http::preventStrayRequests();
    }

    public function test_tamu_diarahkan_ke_login(): void
    {
        $this->get('/chat')->assertRedirect('/login');
    }

    public function test_halaman_chat_tampil_untuk_user_login(): void
    {
        $this->actingAs(User::factory()->create())
            ->get('/chat')
            ->assertOk()
            ->assertSeeLivewire(ChatAgent::class);
    }

    public function test_prompt_kosong_ditolak(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fake();

        Livewire::test(ChatAgent::class)
            ->set('prompt', '')
            ->call('sendMessage')
            ->assertHasErrors(['prompt' => 'required']);

        Http::assertNothingSent();
    }

    public function test_senopati_menjawab_dan_pesan_tersimpan(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        Http::fake([self::SENOPATI => Http::response($this->sse(['Halo', ', ini ringkasannya.'], 'qwen3:14b'))]);

        $component = $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Ringkas email dosen.')
            ->call('sendMessage'));

        $session = ChatSession::sole();
        $component->assertSet('sessionId', $session->id)
            ->assertSet('modelUsed', 'qwen3:14b')
            ->assertSet('prompt', '')
            ->assertSet('errorMessage', null)
            ->assertSet('messages', [
                ['role' => 'user', 'content' => 'Ringkas email dosen.'],
                ['role' => 'assistant', 'content' => 'Halo, ini ringkasannya.'],
            ]);

        $this->assertSame($user->id, $session->user_id);
        $this->assertSame(2, ChatMessage::count());
        Http::assertSentCount(1);
    }

    public function test_senopati_gagal_fallback_ke_ollama(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fake([
            self::SENOPATI => fn () => throw new ConnectionException('Connection refused'),
            self::OLLAMA => Http::response($this->sse(['Jawaban Ollama.'], 'qwen3:4b')),
        ]);

        $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage'))
            ->assertSet('modelUsed', 'qwen3:4b')
            ->assertSet('errorMessage', null);

        $this->assertSame('qwen3:4b', ChatMessage::where('role', 'assistant')->value('model'));
    }

    public function test_reasoning_tidak_masuk_jawaban(): void
    {
        $this->actingAs(User::factory()->create());
        $body = 'data: ' . json_encode(['choices' => [['delta' => ['reasoning_content' => 'Pengguna menyapa...']]]]) . "\n\n"
            . 'data: ' . json_encode(['choices' => [['delta' => ['content' => 'Halo juga!']]]]) . "\n\n"
            . "data: [DONE]\n\n";
        Http::fake([self::SENOPATI => Http::response($body)]);

        $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage'))
            ->assertSet('messages.1.content', 'Halo juga!');
    }

    public function test_semua_provider_gagal_menampilkan_error_tanpa_menyimpan(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fake([
            self::SENOPATI => Http::response('rate limited', 429),
            self::OLLAMA => Http::response('error', 500),
        ]);

        $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage'))
            ->assertSet('errorMessage', 'Layanan LLM sedang tidak tersedia. Coba lagi nanti.')
            ->assertSet('sessionId', null);

        $this->assertSame(0, ChatMessage::count());
        $this->assertSame(0, ChatSession::count());
    }

    public function test_session_id_tidak_bisa_diubah_dari_klien(): void
    {
        $this->actingAs(User::factory()->create());
        $other = ChatSession::factory()->create();

        $this->expectException(\Livewire\Features\SupportLockedProperties\CannotUpdateLockedPropertyException::class);

        Livewire::test(ChatAgent::class)->set('sessionId', $other->id);
    }

    /**
     * Livewire menulis potongan wire:stream langsung ke output; tahan agar
     * tidak tercetak di keluaran tes.
     *
     * @template T
     *
     * @param  callable(): T  $callback
     * @return T
     */
    private function silently(callable $callback): mixed
    {
        ob_start();

        try {
            return $callback();
        } finally {
            ob_end_clean();
        }
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
        $lines[] = 'data: [DONE]';

        return implode("\n\n", $lines) . "\n\n";
    }
}
