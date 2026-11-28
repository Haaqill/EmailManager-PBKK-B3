# Percobaan build desktop (NativePHP)

Percobaan 23 Nov 2026 di branch `feat/native-build`, Windows 10, PHP 8.4, Node 26.
Tujuannya membuktikan aplikasi Laravel bisa menjadi installer desktop, sebelum fitur lain
bertambah. Agen Python belum ikut dibundel.

## Hasil

| Pemeriksaan | Hasil |
|---|---|
| `nativephp/desktop` terpasang dengan Laravel 13 dan Livewire 4 | Ya, versi 2.5.0, tanpa konflik |
| Mode dev (`native:run`) | Berjalan: jendela terbuka, migrasi otomatis, queue worker dan scheduler aktif |
| Installer Windows (`native:build win x64`) | Berhasil: `Gmail Inbox Manager-1.0.0-setup.exe`, 145 MB (488 MB setelah diekstrak) |
| Aplikasi hasil build (production) | Registrasi, `/chat`, `/batch`, `/riwayat`, dan halaman 404 terbuka; alur demo `/batch` (Mulai → Menunggu review → Setujui yang aman → Jalankan → Selesai) berjalan |
| Tes Laravel setelah NativePHP terpasang | 135 tes lolos |
| Dipasang di laptop lain tanpa PHP | **Belum diuji** |

Alur demo diuji dengan memanggil aksi Livewire lewat HTTP ke server aplikasi desktop, bukan
dengan mengklik jendela. Obrolan di aplikasi hasil build belum diuji (lihat "Belum diuji").

## Cara menjalankan ulang

Dari root repo:

```powershell
composer install                     # nativephp/desktop sudah ada di composer.json
php artisan native:install --no-interaction
npm run build
php artisan native:run               # mode dev
php artisan native:build win x64     # installer di nativephp/electron/dist/
```

Dua masalah lingkungan yang ditemui:

1. **Terminal di dalam VS Code mewarisi `ELECTRON_RUN_AS_NODE`.** Akibatnya Electron berjalan
   sebagai Node biasa dan gagal dengan "does not provide an export named 'BrowserWindow'".
   Hapus dulu variabelnya di terminal itu: `Remove-Item Env:ELECTRON_RUN_AS_NODE`, atau
   jalankan dari terminal di luar VS Code.
2. **Binary Electron tidak terunduh saat `native:install`** ("Electron uninstall" saat
   `native:run`). Diatasi dengan menjalankan skrip unduhnya secara manual:
   `node install.js` di `vendor/nativephp/desktop/resources/electron/node_modules/electron`.

## Perubahan di repo

| File | Isi |
|---|---|
| `composer.json`, `composer.lock` | `nativephp/desktop ^2.5`, skrip `native:dev`, dan `native:install` di `post-update-cmd` (ditambahkan installer). `post-update-cmd` tidak menimpa `config/nativephp.php` yang sudah ada. |
| `app/Providers/NativeAppServiceProvider.php` | Dari installer; membuka satu jendela. |
| `config/nativephp.php` | Dari installer (id aplikasi `com.emailmanager.app` dari `main`), lalu diubah: deskripsi, updater dimatikan, dan daftar pembersihan di bawah. |
| `.gitignore` | Mengabaikan `nativephp/electron/dist` (hasil build). `nativephp/binaries` sudah diabaikan oleh `.gitignore` miliknya sendiri. |

### Yang dikecualikan dari bundel

Build menyalin **seluruh folder proyek**, lalu membuang pola di `cleanup_exclude_files`, dan
menyalin `.env` setelah membuang kunci di `cleanup_env_keys`. Tambahan dari bawaan:

- `cleanup_exclude_files`:
  - `gmail-agent` (berisi `credentials.json`, `gmail-agent/.env` dengan kunci LLM, dan `.venv`);
  - `body.json`, `docs`, `contracts`, `tests`.
- `cleanup_env_keys`:
  - `*_PASSWORD`, `LLM_*_KEY`, `AGENT_TOKEN`;
  - `APP_ENV` dan `APP_DEBUG`, supaya build memakai bawaan `config/app.php` (production, debug
    mati), bukan nilai dev.

Hasil build sudah diperiksa:
- tidak ada `gmail-agent/`, database dev, `docs/`, tes, atau Debugbar;
- `.env` di bundel tidak memuat `LLM_SENOPATI_KEY` atau password;
- halaman galat tidak menampilkan detail debug.

## Temuan untuk jalur lain

| Pertanyaan | Temuan |
|---|---|
| Lokasi database | Dev: `database/nativephp.sqlite`, terpisah dari database dev biasa. Production: `%APPDATA%\gmail-inbox-manager\database\database.sqlite`. NativePHP memaksa koneksi `nativephp` dan menjalankan migrasi sendiri. |
| Migrasi | Otomatis saat aplikasi dibuka; 11 migrasi berjalan di dev dan production. |
| Queue (orang 2) | NativePHP menyalakan worker sendiri dari `queue_workers` di `config/nativephp.php` dan memaksa `queue.default = database`. Job Laravel akan berjalan di aplikasi desktop tanpa langkah tambahan. |
| Session | NativePHP memaksa `session.driver = file`, apa pun isi `.env`. |
| Akun | `DemoSeeder` tidak jalan di production; registrasi biasa berfungsi. |
| Menjalankan agen Python (keputusan nomor 8) | NativePHP punya API `ChildProcess::start(cmd, alias, cwd, env, persistent)` untuk menyalakan proses lain dari aplikasi, dan `Shell` untuk membuka URL di browser (dibutuhkan untuk login Gmail, kontrak 6f). Belum dicoba dengan agen. |

## Catatan keamanan

- **Server PHP aplikasi (`127.0.0.1:8100`) bisa diakses dari browser biasa** di laptop yang
  sama, baik di dev maupun production (HTTP 200 saat diuji). Aksesnya tetap butuh login, tetapi
  program lain di laptop bisa memanggilnya.
- **`APP_KEY` dari `.env` dev ikut terbundel.** Semua installer memakai kunci yang sama, dan
  kunci dev developer ikut tersebar. Perlu diputuskan sebelum installer dibagikan, mis. memakai
  kunci khusus build.
- Installer belum ditandatangani (code signing), jadi Windows SmartScreen kemungkinan
  memperingatkan saat dipasang.

## Belum diuji

- Memasang installer di laptop lain yang tidak punya PHP. Ini kriteria selesai percobaan dan
  harus dilakukan tim.
- Obrolan di aplikasi hasil build. Kunci Senopati sengaja tidak ikut, jadi obrolan hanya bisa
  menjawab bila Ollama berjalan di laptop itu. Cara pengguna mengisi kunci (mis. lewat
  `/pengaturan`) belum dibuat.
- Aplikasi ditutup lalu dibuka lagi: data dan user tetap ada.
- Uninstall: `delete_app_data_on_uninstall` bawaannya `false`, jadi data di `%APPDATA%` tertinggal.

## Usulan untuk keputusan nomor 8

1. Aplikasi desktop menyalakan agen lewat `ChildProcess` saat aplikasi dibuka dan menghentikannya
   saat ditutup.
   - Port dan `AGENT_TOKEN` dibuat oleh aplikasi, lalu diberikan ke agen lewat `env`.
   - Agen tetap memakai Python yang dipasang pengguna, dibantu skrip setup, sesuai rencana tim.
2. Sebelum itu, perlu dipastikan dosen menerima Python dipasang terpisah, karena installer tidak
   lagi "berjalan tanpa instalasi tambahan".
3. Konsekuensi untuk kontrak 6e: agen ikut mati saat aplikasi ditutup, jadi batch yang sedang
   direview menjadi `failed` saat aplikasi dibuka lagi. Ini sesuai opsi A yang sudah dipilih.
