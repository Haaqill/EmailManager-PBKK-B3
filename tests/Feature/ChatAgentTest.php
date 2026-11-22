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
use Illuminate\Support\Facades\RateLimiter;
use Livewire\Features\SupportLockedProperties\CannotUpdateLockedPropertyException;
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
        RateLimiter::clear('chat-agent:1');
    }

    public function test_pesan_pertama_membuat_sesi_judul_dan_dua_pesan_dengan_metadata(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        Http::fake([self::SENOPATI => Http::response($this->sse(['Halo', ', ini ringkasannya.'], 'qwen3:14b', usage: [12, 5]))]);

        $prompt = 'Tolong ringkas email dari dosen pembimbing tentang revisi bab tiga skripsi saya.';
        $component = $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', $prompt)
            ->call('sendMessage'));

        $session = ChatSession::sole();
        $component->assertSet('sessionId', $session->id)
            ->assertSet('prompt', '')
            ->assertSet('errorMessage', null)
            ->assertDispatched('chat-session-updated', id: $session->id)
            ->assertSee('Halo, ini ringkasannya.')
            ->assertSee('qwen3:14b');

        $this->assertSame($user->id, $session->user_id);
        $this->assertSame('chat', $session->mode);
        $this->assertSame(mb_substr($prompt, 0, 60), $session->title);

        [$userMessage, $reply] = ChatMessage::query()->orderBy('id')->get()->all();
        $this->assertSame(['user', $prompt], [$userMessage->role, $userMessage->content]);
        $this->assertSame('assistant', $reply->role);
        $this->assertSame('Halo, ini ringkasannya.', $reply->content);
        $this->assertSame('qwen3:14b', $reply->model);
        $this->assertSame(12, $reply->prompt_tokens);
        $this->assertSame(5, $reply->completion_tokens);
        $this->assertIsInt($reply->latency_ms);
        Http::assertSentCount(1);
    }

    public function test_membuka_halaman_tidak_membuat_sesi(): void
    {
        $this->actingAs(User::factory()->create());

        Livewire::test(ChatAgent::class)->assertSee('Mulai obrolan baru');

        $this->assertSame(0, ChatSession::count());
    }

    public function test_pesan_lanjutan_memakai_sesi_dan_riwayat_yang_sama(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat']);
        $session->messages()->create(['role' => 'user', 'content' => 'Pertanyaan lama']);
        $session->messages()->create(['role' => 'assistant', 'content' => 'Jawaban lama']);
        Http::fake([self::SENOPATI => Http::response($this->sse(['Lanjut.'], 'qwen3:14b'))]);

        $this->silently(fn () => Livewire::test(ChatAgent::class, ['sessionId' => $session->id])
            ->set('prompt', 'Pertanyaan baru')
            ->call('sendMessage'));

        $this->assertSame(1, ChatSession::count());
        $this->assertSame(4, $session->messages()->count());
        Http::assertSent(function ($request) {
            $contents = array_column($request['messages'], 'content');

            return array_slice($contents, 1) === ['Pertanyaan lama', 'Jawaban lama', 'Pertanyaan baru'];
        });
    }

    public function test_prompt_kosong_ditolak_dengan_pesan_indonesia(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fake();

        Livewire::test(ChatAgent::class)
            ->set('prompt', '   ')
            ->call('sendMessage')
            ->assertHasErrors(['prompt' => 'required'])
            ->assertSee('Prompt wajib diisi.');

        Http::assertNothingSent();
        $this->assertSame(0, ChatSession::count());
    }

    public function test_prompt_terlalu_panjang_ditolak_dengan_pesan_indonesia(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fake();

        Livewire::test(ChatAgent::class)
            ->set('prompt', str_repeat('a', 1001))
            ->call('sendMessage')
            ->assertHasErrors(['prompt' => 'max'])
            ->assertSee('Prompt maksimal 1000 karakter.');

        Http::assertNothingSent();
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
            ->assertSet('errorMessage', null);

        $this->assertSame('qwen3:4b', ChatMessage::where('role', 'assistant')->value('model'));
    }

    public function test_provider_gagal_pesan_user_tersimpan_dan_coba_lagi_tidak_menggandakan(): void
    {
        $this->actingAs(User::factory()->create());
        Http::fakeSequence(self::SENOPATI)
            ->push('rate limited', 429)
            ->push($this->sse(['Akhirnya terjawab.'], 'qwen3:14b'));
        Http::fake([self::OLLAMA => Http::response('error', 500)]);

        $component = $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage'))
            ->assertSet('errorMessage', ChatAgent::ERROR_UNAVAILABLE)
            ->assertSee('Coba lagi')
            ->assertDontSee('rate limited');

        $session = ChatSession::sole();
        $component->assertSet('sessionId', $session->id);
        $this->assertSame(['user'], ChatMessage::pluck('role')->all());

        $this->silently(fn () => $component->call('retry'))
            ->assertSet('errorMessage', null)
            ->assertSee('Akhirnya terjawab.');

        $this->assertSame(['user', 'assistant'], ChatMessage::orderBy('id')->pluck('role')->all());
        $this->assertSame(1, ChatMessage::where('role', 'user')->count());
    }

    public function test_coba_lagi_tanpa_pesan_tertunda_tidak_memanggil_llm(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat']);
        $session->messages()->create(['role' => 'user', 'content' => 'Halo']);
        $session->messages()->create(['role' => 'assistant', 'content' => 'Hai']);
        Http::fake();

        Livewire::test(ChatAgent::class, ['sessionId' => $session->id])
            ->assertDontSee('Coba lagi')
            ->call('retry');

        Http::assertNothingSent();
        $this->assertSame(2, ChatMessage::count());
    }

    public function test_sesi_milik_orang_lain_ditolak_saat_mount(): void
    {
        $this->actingAs(User::factory()->create());
        $other = ChatSession::factory()->create();

        Livewire::test(ChatAgent::class, ['sessionId' => $other->id])->assertForbidden();
    }

    public function test_session_id_tidak_bisa_diubah_dari_klien(): void
    {
        $this->actingAs(User::factory()->create());
        $other = ChatSession::factory()->create();

        $this->expectException(CannotUpdateLockedPropertyException::class);

        Livewire::test(ChatAgent::class)->set('sessionId', $other->id);
    }

    public function test_keluaran_model_berbahaya_tidak_menjadi_markup_aktif(): void
    {
        $this->actingAs(User::factory()->create());
        $answer = "Lihat <script>alert('x')</script> dan [klik](javascript:alert(1)) <img src=x onerror=alert(2)>";
        $body = 'data: ' . json_encode(['choices' => [['delta' => ['reasoning_content' => '<script>alert("PENANDA_REASONING")</script>']]]]) . "\n\n"
            . 'data: ' . json_encode(['model' => 'qwen3:14b', 'choices' => [['delta' => ['content' => $answer]]]]) . "\n\n"
            . "data: [DONE]\n\n";
        Http::fake([self::SENOPATI => Http::response($body)]);

        $component = $this->silently(
            fn () => Livewire::test(ChatAgent::class)->set('prompt', 'Halo')->call('sendMessage'),
            $streamed,
        );

        // Potongan stream (disisipkan sebagai HTML oleh wire:stream) sudah di-escape.
        $this->assertStringContainsString('streamedReply', $streamed);
        $this->assertStringContainsString('&lt;script&gt;', $streamed);
        $this->assertStringNotContainsString('<script>', $streamed);
        $this->assertStringNotContainsString('<img', $streamed);
        $this->assertStringNotContainsString('PENANDA_REASONING', $streamed);

        $html = $component->html();
        $this->assertStringNotContainsString('<script>alert', $html);
        $this->assertStringNotContainsString('javascript:', $html);
        $this->assertStringNotContainsString('<img', $html);
        $this->assertStringNotContainsString('PENANDA_REASONING', $html);
    }

    public function test_reasoning_tidak_tersimpan_hanya_content(): void
    {
        $this->actingAs(User::factory()->create());
        $body = 'data: ' . json_encode(['choices' => [['delta' => ['reasoning_content' => 'Pengguna menyapa, balas ramah.']]]]) . "\n\n"
            . 'data: ' . json_encode(['choices' => [['delta' => ['content' => 'Halo juga!']]]]) . "\n\n"
            . "data: [DONE]\n\n";
        Http::fake([self::SENOPATI => Http::response($body)]);

        $this->silently(fn () => Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage'))
            ->assertDontSee('Pengguna menyapa');

        $this->assertSame('Halo juga!', ChatMessage::where('role', 'assistant')->value('content'));
        $this->assertSame(0, ChatMessage::where('content', 'like', '%Pengguna menyapa%')->count());
    }

    public function test_pembatasan_laju_per_pengguna(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        RateLimiter::clear('chat-agent:' . $user->id);
        for ($i = 0; $i < ChatAgent::RATE_LIMIT; $i++) {
            RateLimiter::hit('chat-agent:' . $user->id, ChatAgent::RATE_WINDOW_SECONDS);
        }
        Http::fake();

        Livewire::test(ChatAgent::class)
            ->set('prompt', 'Halo')
            ->call('sendMessage')
            ->assertHasErrors('prompt')
            ->assertSee('Terlalu banyak pesan.');

        Http::assertNothingSent();
        $this->assertSame(0, ChatMessage::count());
    }

    public function test_hanya_100_pesan_terakhir_dimuat(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat']);
        for ($i = 1; $i <= 105; $i++) {
            $session->messages()->create(['role' => $i % 2 ? 'user' : 'assistant', 'content' => "pesan-nomor-{$i}."]);
        }

        Livewire::test(ChatAgent::class, ['sessionId' => $session->id])
            ->assertDontSee('pesan-nomor-5.')
            ->assertSee('pesan-nomor-6.')
            ->assertSee('pesan-nomor-105.');
    }

    /**
     * Livewire menulis potongan wire:stream langsung ke output lalu memanggil
     * ob_flush(); tampung lewat callback agar tidak tercetak dan bisa diperiksa.
     *
     * @template T
     *
     * @param  callable(): T  $callback
     * @return T
     */
    private function silently(callable $callback, ?string &$output = null): mixed
    {
        $output = '';
        ob_start(function (string $buffer) use (&$output): string {
            $output .= $buffer;

            return '';
        });

        try {
            return $callback();
        } finally {
            ob_end_clean();
        }
    }

    /**
     * @param  list<string>  $pieces
     * @param  array{0: int, 1: int}|null  $usage
     */
    private function sse(array $pieces, string $model, ?array $usage = null): string
    {
        $lines = [];
        foreach ($pieces as $piece) {
            $lines[] = 'data: ' . json_encode([
                'model' => $model,
                'choices' => [['index' => 0, 'delta' => ['content' => $piece]]],
            ]);
        }
        if ($usage !== null) {
            $lines[] = 'data: ' . json_encode([
                'model' => $model,
                'choices' => [],
                'usage' => ['prompt_tokens' => $usage[0], 'completion_tokens' => $usage[1]],
            ]);
        }
        $lines[] = 'data: [DONE]';

        return implode("\n\n", $lines) . "\n\n";
    }
}
