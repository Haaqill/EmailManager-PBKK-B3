# Gmail Inbox Manager

Aplikasi Laravel untuk mengelola inbox Gmail dengan bantuan agen AI. Laravel
memegang login, UI, database, riwayat, dan log; agen Python (redaksi PII, LLM
kampus, workflow LangGraph, tool Gmail) berada di folder `gmail-agent/`.

## Struktur repo

```
/               proyek Laravel (app/, routes/, database/, resources/, tests/, ...)
gmail-agent/    agen Python: app/, eval/, tests/, requirements.txt
docs/           ERD dan screenshot
```

Folder `app/` di root adalah kode Laravel (namespace `App\`). Kode Python ada di
`gmail-agent/app/`; panduan menjalankannya ada di
[`gmail-agent/README.md`](./gmail-agent/README.md).

## Menjalankan aplikasi

Prasyarat: PHP **8.3 atau lebih baru**, Composer 2, Node.js/npm, dan ekstensi
PHP yang dibutuhkan Laravel (termasuk `pdo_sqlite` bila memakai SQLite).
Semua perintah dijalankan dari root repo.

```powershell
composer install
Copy-Item .env.example .env
php artisan key:generate
New-Item -ItemType File -Path database\database.sqlite -Force
php artisan migrate:fresh --seed
npm install
npm run build
php artisan test
vendor\bin\pint --preset psr12 --test
```

Pastikan `DB_CONNECTION=sqlite` di `.env`. Untuk menjalankan server lokal:

```powershell
php artisan serve
```

Akun seeder: `demo@inbox-manager.test` / `password`.

## Skema dan relasi

```mermaid
erDiagram
    users ||--o{ chat_sessions : "hasMany"
    chat_sessions ||--o{ chat_messages : "hasMany"
    chat_sessions ||--o{ batch_plan_items : "hasMany"
    chat_sessions ||--o{ tool_execution_logs : "FK cascade"
    chat_messages ||--o{ tool_execution_logs : "morphMany"
    batch_plan_items ||--o{ tool_execution_logs : "morphMany"

    users {
        bigint id PK
    }
    chat_sessions {
        bigint id PK
        bigint user_id FK
        string title
        string mode
        string status
        string agent_thread_id UK
    }
    chat_messages {
        bigint id PK
        bigint chat_session_id FK
        string role
        text content
        string tool_call_id
    }
    batch_plan_items {
        bigint id PK
        bigint chat_session_id FK
        string gmail_thread_id
        string category
        string priority
        string action
        string decision
    }
    tool_execution_logs {
        bigint id PK
        bigint chat_session_id FK
        string loggable_type
        bigint loggable_id
        string tool_name
        json arguments
        json result
        string status
    }
```

`ToolExecutionLog` memakai polymorphic `morphTo()` untuk sumber log dari
`ChatMessage` atau `BatchPlanItem`. Karena pasangan kolom polymorphic tidak
dapat memiliki foreign key, `chat_session_id` tetap menjadi foreign key dengan
cascade; event `deleting` pada kedua sumber menghapus log saat sumber dihapus
secara individual. Alias morph yang dipakai adalah `chat_message` dan
`batch_plan_item`.

`chat_messages.content` hanya menyimpan teks yang sudah diredaksi (contoh:
`<PERSON_1>` dan `<EMAIL_1>`); pemetaan PII tidak disimpan.

## Eager loading dan bukti

Halaman riwayat menggunakan `withCount(['messages', 'toolLogs'])`. Detail sesi
memuat `messages.toolLogs` dan `planItems.toolLogs` melalui eager loading, dan
`Model::preventLazyLoading()` mengungkap relasi yang lupa dimuat saat
development/testing.

Untuk bukti, login dengan akun demo lalu buka detail sesi batch yang berisi 10
item. Buka panel Debugbar bagian **Queries** dan ambil screenshot yang
memperlihatkan halaman batch serta query eager loading untuk sesi, pesan, log
pesan, item batch, dan log item (5 query data agen; query auth/session tidak
dihitung). Screenshot tersimpan di `docs/debugbar-n1.png`.

## Pemetaan keluaran agen Python

| Keluaran agen | Penyimpanan Laravel |
|---|---|
| Perintah pengguna dan jawaban agen (loop ReAct) | `chat_messages` |
| Tool call `id`, `name`, dan `arguments` | `tool_execution_logs` |
| Rencana batch: thread, kategori, prioritas, aksi, draft, alasan | `batch_plan_items` |
| Keputusan review setujui/edit/tolak | `batch_plan_items.decision` |
| Checkpoint LangGraph `thread_id` | `chat_sessions.agent_thread_id` |

Tabel Laravel adalah kontrak data saja; integrasi runtime dengan agen Python
belum termasuk tugas ini.

## Anggota kelompok

| Nama | NRP |
|---|---|
| Ja'far Balyan Al Karim | 5025241040 |
| Hanif Aqil Janardana | 5025241111 |
| Dafa Kumara Sahasika | 5025241112 |
| Royan Habibi Alfatih | 5025241115 |