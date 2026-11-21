<?php

namespace Database\Seeders;

use App\Models\User;
use Illuminate\Database\Seeder;
use RuntimeException;

/**
 * Akun demo untuk docs/demo-skenario.md. Hanya untuk environment local:
 *
 *     php artisan db:seed --class=DemoSeeder
 *
 * Tidak dipanggil DatabaseSeeder. Akunnya sama dengan AgentDemoSeeder
 * (demo@inbox-manager.test), tetapi seeder ini tidak membuat data contoh lain;
 * batch dibuat lewat /batch dengan AGENT_DRIVER=fake.
 */
class DemoSeeder extends Seeder
{
    public const EMAIL = 'demo@inbox-manager.test';

    public const PASSWORD = 'password';

    public function run(): void
    {
        if (! app()->environment('local')) {
            throw new RuntimeException('DemoSeeder hanya boleh dijalankan di environment local.');
        }

        $user = User::query()->firstOrNew(['email' => self::EMAIL]);
        $user->name = $user->name ?: 'Akun Demo';
        $user->password = self::PASSWORD;
        // Rute /chat dan /batch memakai middleware verified (berlaku bila User memakai MustVerifyEmail).
        $user->forceFill(['email_verified_at' => $user->email_verified_at ?? now()])->save();
    }
}
