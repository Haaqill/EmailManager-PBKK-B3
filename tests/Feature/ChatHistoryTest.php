<?php

namespace Tests\Feature;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\ToolExecutionLog;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class ChatHistoryTest extends TestCase
{
    use RefreshDatabase;

    public function test_halaman_riwayat_bebas_n_plus_1(): void
    {
        $user = User::factory()->create();
        $small = $this->seedSession($user, messages: 2, items: 1);
        $large = $this->seedSession($user, messages: 40, items: 25);

        $smallQueries = $this->countQueries(fn () => $this->actingAs($user)
            ->get(route('riwayat.show', $small))
            ->assertOk());

        $largeQueries = $this->countQueries(fn () => $this->actingAs($user)
            ->get(route('riwayat.show', $large))
            ->assertOk()
            ->assertSee($large->title));

        $this->assertSame($smallQueries, $largeQueries);
    }

    public function test_daftar_riwayat_menampilkan_jumlah_dengan_withcount(): void
    {
        $user = User::factory()->create();
        $session = $this->seedSession($user, messages: 3, items: 0);

        $this->actingAs($user)
            ->get(route('riwayat.index'))
            ->assertOk()
            ->assertSee($session->title);
    }

    public function test_user_tidak_bisa_membuka_sesi_milik_user_lain(): void
    {
        $owner = User::factory()->create();
        $intruder = User::factory()->create();
        $session = $this->seedSession($owner, messages: 1, items: 0);

        $this->actingAs($intruder)
            ->get(route('riwayat.show', $session))
            ->assertNotFound();
    }

    public function test_tamu_diarahkan_ke_login(): void
    {
        $this->get(route('riwayat.index'))->assertRedirect(route('login'));
    }

    public function test_sesi_chat_bisa_dilanjutkan_dari_riwayat(): void
    {
        $user = User::factory()->create();
        $chat = ChatSession::factory()->for($user)->create(['mode' => 'chat', 'title' => 'Sesi chat']);
        $batch = $this->seedSession($user, messages: 1, items: 0);
        $continue = '/<a\b[^>]*href="' . preg_quote(route('chat.show', $chat), '/') . '"[^>]*>\s*Lanjutkan obrolan\s*<\/a>/';

        $html = $this->actingAs($user)->get(route('riwayat.show', $chat))->assertOk()->getContent();
        $this->assertMatchesRegularExpression($continue, $html);

        $this->actingAs($user)->get(route('riwayat.show', $batch))->assertOk()->assertDontSee('Lanjutkan obrolan');
        $this->actingAs($user)->get(route('riwayat.index'))->assertOk()
            ->assertSee('href="' . route('chat.show', $chat) . '"', false)
            ->assertDontSee('href="' . route('chat.show', $batch) . '"', false);
    }

    public function test_pesan_panjang_tanpa_spasi_dipenggal(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat', 'title' => str_repeat('q', 60)]);
        $session->messages()->create(['role' => 'user', 'content' => str_repeat('q', 1000)]);

        $html = $this->actingAs($user)->get(route('riwayat.show', $session))->assertOk()->getContent();

        $this->assertMatchesRegularExpression('/<p class="[^"]*\[overflow-wrap:anywhere\][^"]*">q{1000}<\/p>/', $html);
        $this->assertMatchesRegularExpression('/<h2 class="[^"]*\[overflow-wrap:anywhere\][^"]*">\s*q{60}\s*<\/h2>/', $html);
    }

    private function seedSession(User $user, int $messages, int $items): ChatSession
    {
        $session = ChatSession::factory()->batch()->for($user)->create();

        ChatMessage::factory()->count($messages)->assistant()->for($session)->create()->each(
            fn (ChatMessage $message) => ToolExecutionLog::factory()->count(2)->forLoggable($message)->create()
        );

        BatchPlanItem::factory()->count($items)->for($session)->create()->each(
            fn (BatchPlanItem $item) => ToolExecutionLog::factory()->forLoggable($item)->create()
        );

        return $session;
    }

    private function countQueries(callable $callback): int
    {
        DB::flushQueryLog();
        DB::enableQueryLog();
        $callback();
        $count = count(DB::getQueryLog());
        DB::disableQueryLog();

        return $count;
    }
}
