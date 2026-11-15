<?php

namespace App\Console\Commands;

use App\Models\User;
use Illuminate\Console\Command;

class CreateApiToken extends Command
{
    protected $signature = 'app:api-token {email : Email user pemilik token} {--name=postman : Nama token}';

    protected $description = 'Buat token Sanctum untuk user dan tampilkan token plain-text satu kali';

    public function handle(): int
    {
        $email = (string) $this->argument('email');
        $user = User::where('email', $email)->first();

        if ($user === null) {
            $this->error("User dengan email {$email} tidak ditemukan.");

            return self::FAILURE;
        }

        $token = $user->createToken((string) $this->option('name'));

        $this->info("Token untuk {$user->email} (simpan sekarang, tidak akan ditampilkan lagi):");
        $this->line($token->plainTextToken);

        return self::SUCCESS;
    }
}
