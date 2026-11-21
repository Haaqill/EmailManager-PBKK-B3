<?php

namespace Tests\Feature;

use App\Livewire\ChatAgent;
use App\Livewire\SessionSidebar;
use App\Models\ChatMessage;
use App\Models\ChatSession;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Livewire\Livewire;
use Tests\TestCase;

class ChatPageTest extends TestCase
{
    use RefreshDatabase;

    public function test_tamu_diarahkan_ke_login(): void
    {
        $session = ChatSession::factory()->create();

        $this->get('/chat')->assertRedirect('/login');
        $this->get("/chat/{$session->id}")->assertRedirect('/login');
    }

    public function test_dashboard_mengalihkan_ke_chat(): void
    {
        $this->actingAs(User::factory()->create())
            ->get('/dashboard')
            ->assertRedirect(route('chat'));
    }

    public function test_halaman_chat_menyematkan_kedua_komponen(): void
    {
        $this->actingAs(User::factory()->create())
            ->get(route('chat'))
            ->assertOk()
            ->assertSee('<html lang="id">', false)
            ->assertSee('Lompat ke konten')
            ->assertSee('AI dapat membuat kesalahan.')
            ->assertDontSee('Keyakinan tinggi')
            ->assertSeeLivewire(SessionSidebar::class)
            ->assertSeeLivewire(ChatAgent::class);
    }

    public function test_pemilik_bisa_membuka_sesinya(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat', 'title' => 'Sesi saya']);
        $session->messages()->create(['role' => 'user', 'content' => 'Isi pesan saya']);

        $this->actingAs($user)
            ->get(route('chat.show', $session))
            ->assertOk()
            ->assertSee('Isi pesan saya')
            ->assertSee('aria-current="page"', false);
    }

    public function test_sesi_orang_lain_mendapat_403(): void
    {
        $other = ChatSession::factory()->create();

        $this->actingAs(User::factory()->create())
            ->get(route('chat.show', $other))
            ->assertForbidden();
    }

    public function test_sidebar_hanya_memuat_sesi_chat_milik_pengguna_terbaru_di_atas(): void
    {
        $user = User::factory()->create();
        ChatSession::factory()->for($user)->create(['mode' => 'chat', 'title' => 'Sesi lama', 'updated_at' => now()->subDay()]);
        ChatSession::factory()->for($user)->create(['mode' => 'chat', 'title' => 'Sesi baru', 'updated_at' => now()]);
        ChatSession::factory()->for($user)->create(['mode' => 'batch', 'title' => 'Sesi batch']);
        ChatSession::factory()->create(['mode' => 'chat', 'title' => 'Sesi orang lain']);
        $this->actingAs($user);

        Livewire::test(SessionSidebar::class)
            ->assertSeeInOrder(['Sesi baru', 'Sesi lama'])
            ->assertDontSee('Sesi orang lain')
            ->assertDontSee('Sesi batch');
    }

    public function test_sidebar_maksimal_50_sesi_dan_keadaan_kosong(): void
    {
        $user = User::factory()->create();
        $this->actingAs($user);

        Livewire::test(SessionSidebar::class)->assertSee('Belum ada obrolan.');

        ChatSession::factory()->for($user)->count(55)->create(['mode' => 'chat']);
        $this->assertCount(50, Livewire::test(SessionSidebar::class)->viewData('sessions'));
    }

    public function test_hapus_sesi_oleh_pemilik_ikut_menghapus_pesan(): void
    {
        $user = User::factory()->create();
        $session = ChatSession::factory()->for($user)->create(['mode' => 'chat']);
        $session->messages()->create(['role' => 'user', 'content' => 'Halo']);
        $session->messages()->create(['role' => 'assistant', 'content' => 'Hai']);
        $this->actingAs($user);

        Livewire::test(SessionSidebar::class, ['activeId' => $session->id])
            ->call('deleteSession', $session->id)
            ->assertRedirect(route('chat'));

        $this->assertDatabaseMissing('chat_sessions', ['id' => $session->id]);
        $this->assertSame(0, ChatMessage::count());
    }

    public function test_hapus_sesi_milik_orang_lain_ditolak(): void
    {
        $other = ChatSession::factory()->create();
        $other->messages()->create(['role' => 'user', 'content' => 'Rahasia orang lain']);
        $this->actingAs(User::factory()->create());

        Livewire::test(SessionSidebar::class)
            ->call('deleteSession', $other->id)
            ->assertForbidden();

        $this->assertDatabaseHas('chat_sessions', ['id' => $other->id]);
        $this->assertSame(1, ChatMessage::count());
    }

    public function test_sidebar_tidak_bisa_dibuka_dengan_sesi_orang_lain(): void
    {
        $other = ChatSession::factory()->create();
        $this->actingAs(User::factory()->create());

        Livewire::test(SessionSidebar::class, ['activeId' => $other->id])->assertForbidden();
    }

    public function test_item_nav_segera_bukan_tautan(): void
    {
        $html = $this->actingAs(User::factory()->create())->get(route('chat'))->assertOk()->getContent();

        // Batch dan Pengaturan, masing-masing di sidebar desktop dan drawer mobile.
        $this->assertSame(4, substr_count($html, 'aria-disabled="true" data-nav-soon'));
        $this->assertSame(4, substr_count($html, '>Segera</span>'));
        foreach (['Batch', 'Pengaturan'] as $label) {
            $this->assertDoesNotMatchRegularExpression('/<a\b[^>]*>\s*' . $label . '\s*<\/a>/', $html);
        }
        $this->assertMatchesRegularExpression('/<a\b[^>]*aria-current="page"[^>]*>\s*Obrolan\s*<\/a>/', $html);
    }

    public function test_navigasi_tampil_di_halaman_profil(): void
    {
        $this->actingAs(User::factory()->create())
            ->get(route('profile.edit'))
            ->assertOk()
            ->assertSee('Obrolan')
            ->assertSee('Keluar');
    }
}
