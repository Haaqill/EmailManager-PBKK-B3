# Status proyek Gmail Inbox Manager

Kondisi per **22 Nov 2026**, branch `feat/ui`. Dokumen ini merangkum isi proyek, apa yang sudah
selesai, apa yang masih tiruan atau belum ada, dan usulan langkah berikutnya. Detail teknis ada di
dokumen yang dirujuk; dokumen ini tidak menggantikannya.

## 1. Ringkasan

Aplikasi untuk merapikan inbox Gmail mahasiswa dengan bantuan agen AI. Agen membaca sejumlah
thread (maks. 10 per batch), mengklasifikasikan kategori dan prioritas, mengusulkan aksi (label,
arsip, Sampah, draf balasan), lalu **menunggu persetujuan pengguna** sebelum menjalankan apa pun.
Aplikasi tidak pernah mengirim atau menghapus permanen email.

Prinsip yang dipegang di seluruh proyek:

- **Manusia menyetujui setiap aksi.** Item yang tidak diputuskan tidak dijalankan (default-deny).
  Sampah wajib dikonfirmasi per item.
- **LLM tidak melihat data pribadi.** Isi email diredaksi menjadi placeholder (`<PERSON_1>`,
  `<EMAIL_1>`, …) sebelum dikirim ke LLM, dan isi email diperlakukan sebagai data, bukan perintah
  (pertahanan prompt injection).
- **Laravel tidak memegang token Gmail.** Akses Gmail hanya di agen Python.
- **Data review bersifat sementara.** Isi draf, alasan, dan peringatan dihapus dari Laravel saat
  batch selesai.

## 2. Arsitektur

```
Browser ──► Laravel (root repo)                         Agen Python (gmail-agent/)
            ├─ login (Breeze), UI Livewire              ├─ redaksi PII (privacy/redact.py)
            ├─ Obrolan  ──► LLM (Senopati → Ollama)     ├─ klien Gmail: mock / OAuth asli
            ├─ API /api/chat-ai (Sanctum, SSE)          ├─ dispatcher tool Gmail
            ├─ Riwayat obrolan                          ├─ LangGraph InboxGraph
            ├─ /batch ──► AgentClient ─ ─ ─ ─ ─ ─ ─ ─ ► │   scan → classify → draft → review → execute
            │             (driver "fake" saat ini;      ├─ builder PlanSnapshot (kontrak)
            │              driver "http" belum ada)     ├─ UI review Streamlit
            └─ SQLite: users, chat_*, batches,          └─ eval/ (evaluasi klasifikasi)
               batch_plan_items, tool_execution_logs
```

Garis putus-putus belum ada: Laravel dan agen Python **belum terhubung saat runtime**. Halaman
`/batch` saat ini memakai agen tiruan.

| Bagian | Teknologi |
|---|---|
| Web | Laravel 13, Livewire 4, Tailwind 3, Breeze, Sanctum, SQLite (dev) |
| Agen | Python 3.13, LangGraph 0.2, Pydantic 2, klien `openai` (OpenAI-compatible), Google API client, keyring, Streamlit |
| LLM | Gateway Senopati (`senopati.lab-alpro.com`, model `qwen3:14b`); cadangan Ollama lokal (`qwen3:4b`) di sisi chat Laravel |

## 3. Status per komponen

Legenda: **Selesai** = berfungsi dan teruji. **Demo** = UI jadi, tetapi data tiruan.
**Belum** = belum ada.

### Laravel

| Komponen | Status | Catatan |
|---|---|---|
| Login, registrasi, profil (Breeze) | Selesai | Akun demo dari seeder: `demo@inbox-manager.test` / `password` (hanya lokal). |
| Obrolan `/chat` (Livewire, streaming) | Selesai | LLM sungguhan dengan fallback Senopati → Ollama; menampilkan model dan latensi; catatan "AI dapat membuat kesalahan". Obrolan ini LLM biasa, **belum** terhubung ke Gmail atau agen. |
| API `POST /api/chat-ai` dan `/stream` (SSE) | Selesai | Sanctum, rate limit 10/menit, konteks 10 pesan terakhir. Prompt disimpan **tanpa redaksi**. Lihat README bagian P11. |
| Riwayat `/riwayat` | Selesai | Daftar sesi dan detail pesan; sesi chat bisa dilanjutkan; teks panjang tanpa spasi tidak meluber. |
| Skema data agen (P9) | Selesai | `chat_sessions`, `chat_messages`, `batch_plan_items`, `tool_execution_logs` (polymorphic); eager loading, `preventLazyLoading`. |
| Kontrak batch: `batches`, `BatchSyncService` | Selesai | Menyimpan payload agen sesuai kontrak; menolak enum tidak valid; keputusan lokal tidak ditimpa sync. |
| `batches:prune-review-data` | Selesai, **belum dijadwalkan** | Menandai batch `awaiting_review` > 7 hari sebagai `expired` dan mengosongkan data sementara. |
| Halaman `/batch` (mulai, progres, review, eksekusi, laporan) | Demo | `FakeAgentClient` + 8 item contoh di `resources/demo/batch_awaiting_review.json`. Skenario di `docs/demo-skenario.md`. |
| `AgentClient` driver `http` | Belum | Memilih `AGENT_DRIVER=http` melempar pengecualian. |

### Agen Python

Nomor fase mengikuti penamaan di kode dan komentar agen.

| Komponen | Status | Catatan |
|---|---|---|
| Smoke test LLM (Fase 0) | Selesai | `python smoke_test_llm.py`; lolos di gateway lab-alpro per 22 Nov 2026. |
| Login OAuth Gmail (Fase 1.1) | Selesai | OAuth Desktop App, scope `gmail.modify`, token di keyring OS. Bawaan `GMAIL_BACKEND=mock`. |
| Redaksi PII (Fase 1.2) | Selesai | Placeholder yang bisa dipulihkan; deteksi NIK, kartu, telepon, email, nama. |
| Tool Gmail + dispatcher | Selesai | Scan maks. 10 thread, baca thread, label, arsip, simpan draf; aksi hanya setelah review. |
| Loop ReAct untuk perintah bebas | Belum | `app/agent/react_loop.py` masih stub (`NotImplementedError`, "setelah MVP"). Ini mesin untuk `agent/turns`. |
| Workflow `InboxGraph` (LangGraph) | Selesai | Klasifikasi dan draf lewat tool call, dengan koreksi ulang bila keluaran tidak valid. |
| Kontrak `PlanSnapshot` + ekspor JSON Schema | Selesai | `app/privacy/contract.py` → `contracts/plan-schema.json`; tes gagal bila skema tertinggal. |
| Tingkat confidence (`tinggi`/`sedang`/`rendah`) | Selesai | Penilaian diri LLM; **bukan gerbang keamanan**, hanya sorotan di UI. |
| UI review Streamlit | Selesai | Tetap dipertahankan sebagai alat pengembangan; UI pengguna adalah Laravel. |
| Status batch setelah agen restart | Belum | `MemorySaver` (memori proses): batch hilang tanpa jejak bila agen di-restart. Kontrak 6e: batch yang belum selesai harus dilaporkan `failed`, jadi registri batch perlu disimpan persisten. |
| Aksi Sampah (`trash_thread`) | Belum | Tool belum ada ("setelah MVP"); `execute` mencatat Sampah sebagai gagal `NOT_ALLOWED`, padahal UI dan kontrak sudah mendukungnya. |
| Token Gmail per user | Selesai | Keyring memakai entri `oauth-token:<user_id>`; CLI memakai ID bawaan `dev`. |
| Evaluasi klasifikasi (`eval/`) | Selesai | Lihat bagian 5. |
| Run terjadwal (Fase 3), embedding (Fase 4), metrik kebocoran PII (Fase 5) | Belum / sebagian | Disebut di kode sebagai fase berikutnya; embedding opsional dan belum tersedia. |
| Layanan HTTP (FastAPI) untuk Laravel | Belum | Endpoint di `docs/contract-laravel-python.md` bagian 5 dan 6 masih usulan. |

## 4. Kontrak Laravel ↔ Python

Sumber: `docs/contract-laravel-python.md`.

- **Tahap 1 (selesai):** bentuk data `PlanSnapshot`/`PlanItem` (item_id, metadata thread,
  kategori, prioritas, aksi `label_only`/`archive`/`trash`/`draft_reply`, `also_archive`, draf
  dengan penerima dan subjek, `warnings[]`, `requires_confirmation`, `confidence`,
  `plan_version`), kebijakan data, dan penyimpanan minimal di Laravel.
- **Tahap 2 (dikunci 23 Nov 2026, belum diimplementasikan):** empat operasi batch
  (`startBatch`, `getBatch`, `execute`, `cancel`) dan dua operasi auth Gmail, autentikasi
  `AGENT_TOKEN` + `X-User-Id`, kode galat, timeout dan polling, serta perilaku saat agen restart.
  Driver tiruan sudah memakai bentuk operasi batch ini. Cara menyalakan agen menunggu
  `native:build`.
- **Kode peringatan:** hanya `UNRESOLVED_PLACEHOLDER` yang benar-benar dihasilkan.
  `REPLY_TO_DOMAIN_MISMATCH`, `NEW_RECIPIENT`, dan `CROSS_THREAD_DATA` masih dicadangkan.
- **Sudah diputuskan (22 Nov 2026):** satu akun Gmail per user; Laravel adalah UI utama,
  Streamlit tetap ada untuk pengembangan.
- **Keputusan terbuka:** `agent/turns` masuk v1 atau v1.1; cara membundel FastAPI di build
  NativePHP.

## 5. Kualitas klasifikasi

Sumber: `docs/evaluasi-confidence.md`. Dataset: `gmail-agent/eval/dataset.json`, 10 thread
fiktif, 3 di antaranya injeksi.

| Evaluasi (qwen3:14b, 3 putaran) | Kategori + aksi benar | Prioritas | Stabilitas level |
|---|---|---|---|
| 21 Nov 2026, sebelum perbaikan | 80% | 47% | 80% |
| 22 Nov 2026, setelah rubrik dan label diperbaiki | **90%** | **73%** | 90% |

Perbaikan 22 Nov: rubrik prioritas didefinisikan lengkap dengan patokan tanggal pesan; tanggal
diberi nama hari; rubrik Pengumuman dan Spam dipertegas; label t001/t002 dikoreksi; t006 ditulis
ulang menjadi phishing yang jelas.

Yang masih menjadi masalah:

- Confidence hampir selalu `tinggi` (29 dari 30) dan belum terkalibrasi. UI menampilkannya redup
  dengan keterangan "perkiraan model, belum terkalibrasi".
- Model kadang memberi prioritas Nanti padahal menandai perlu balasan (t004, t010). Ini bertentangan
  dengan rubrik dan belum divalidasi di kode.
- t004 kadang diarsipkan padahal seharusnya tetap di inbox.
- Dataset terlalu kecil: satu thread menggeser akurasi 10 poin. Belum ada set uji terpisah
  (holdout), dan aksi `trash` belum pernah dinilai.

## 6. Pengujian

| Suite | Perintah | Hasil per 22 Nov 2026 |
|---|---|---|
| Laravel (PHPUnit) | `php artisan test` | 135 tes, 569 asersi, lolos |
| Agen (pytest) | `pytest` dari `gmail-agent/` | 400 tes, lolos |
| Gaya kode PHP | `vendor\bin\pint --preset psr12 --test` | dipakai di setiap perubahan |

Semua tes berjalan tanpa jaringan (LLM dan Gmail di-mock). Evaluasi dengan LLM kampus hanya
dijalankan manual.

## 7. Konfigurasi lingkungan

- Laravel membaca `.env` di root; agen membaca `gmail-agent/.env`. Keduanya tidak di-commit.
- Gateway LLM agen dipindah ke `senopati.lab-alpro.com` karena `senopati.its.ac.id` memberi
  HTTP 504 (21 Nov 2026). Gateway lab-alpro menolak User-Agent bawaan Python dengan HTTP 403,
  jadi transport agen kini mengirim User-Agent eksplisit.
- `AGENT_DRIVER` bawaannya `fake`.
- Jangan menjalankan `migrate:fresh`/`migrate:reset` di DB dev karena menghapus riwayat obrolan.
  Tes memakai `RefreshDatabase`.

## 8. Kaitan dengan tugas kuliah

Butir yang belum ada di repo per 22 Nov 2026:

| Pertemuan | Yang belum ada |
|---|---|
| P1 | Landing page (`/` masih `welcome` bawaan Laravel) |
| P2 | Halaman 404 lewat `Route::fallback` |
| P3 | Form `/pengaturan` (rute belum ada) |
| P5 | Peran admin/tester (tabel `users` belum punya kolom role) |
| P7 | Hapus riwayat dengan soft delete dan pesan flash |
| P10 | Dashboard `/admin` |
| P15 | Job queue (`app/Jobs` belum ada) dan installer `native:build` |

Bobot P15 terbesar ada pada build desktop (35%) dan UI responsif saat tool berjalan lewat queue
(35%), jadi keduanya didahulukan di bagian 10.

`body.json` di root adalah file uji manual dan tidak boleh di-commit.

## 9. Utang teknis dan risiko yang diketahui

| Hal | Dampak | Rujukan |
|---|---|---|
| Laravel dan agen belum terhubung (driver `http` dan FastAPI belum ada) | `/batch` hanya demo; inti produk belum berjalan ujung ke ujung | kontrak bagian 6 |
| Kolom lama `draft_body` dan `reason` di `batch_plan_items` menyimpan teks secara kekal | Bertentangan dengan kebijakan data sementara | kontrak bagian 3b |
| `batches:prune-review-data` belum dijadwalkan | Data review batch yang ditinggalkan tidak pernah dibersihkan otomatis | kontrak bagian 3b |
| Prompt API chat disimpan tanpa redaksi | Data pribadi yang diketik pengguna tersimpan apa adanya | README P11 |
| Tiga kode peringatan Fase 2 belum dihasilkan | Draf ke penerima baru atau domain berbeda tidak diberi peringatan | kontrak bagian 4 |
| Nilai Senopati di `.env.example` salah tempat (`LLM_SENOPATI_MODEL` berisi URL, `LLM_SENOPATI_KEY` berisi nama model) | Membingungkan saat setup baru | `.env.example` |
| Confidence belum terkalibrasi; dataset 10 thread | Level tidak boleh dipakai untuk keputusan otomatis | bagian 5 |
| Review tidak bisa dilanjutkan setelah agen restart | Pengguna harus memulai batch baru (diterima, kontrak 6e), karena `pii_map` tidak disimpan | `app/privacy/redact.py` |
| Sampah belum bisa dijalankan | Usulan Sampah yang disetujui selalu gagal | `app/agent/graph.py` |
| Token Gmail satu entri keyring | Belum memenuhi keputusan satu akun Gmail per user | `app/gmail/auth.py` |
| Senopati hanya dari jaringan kampus | Uji pengguna di luar kampus perlu Ollama | `LLM_API_STYLE` di `gmail-agent/.env` |
| Aturan kampus soal data pribadi belum terbit | Kebijakan data harus ditinjau ulang setelah aturan terbit | kontrak bagian 3c |

## 10. Usulan langkah berikutnya

Urutan berdasarkan ketergantungan dan bobot nilai. Langkah 2 adalah inti produk; langkah lain bisa
berjalan paralel oleh anggota berbeda.

### Langkah 1: kurangi risiko build (segera)

- Coba `native:build` dengan `AGENT_DRIVER=fake` untuk membuktikan Laravel bisa jadi installer.
- Konfirmasi tertulis ke dosen: tema disetujui, dan agen Python dipasang terpisah lewat skrip setup.
- Perbaiki nilai Senopati yang salah tempat di `.env.example`; buka PR `feat/ui` → `main`.

### Langkah 2: hubungkan Laravel dengan agen (tahap 2 kontrak) dan queue

1. ~~Tentukan cara autentikasi Laravel ke agen.~~ Selesai: kontrak bagian 6a.
2. ~~Kunci bagian 6 kontrak.~~ Selesai 23 Nov 2026, kecuali cara menyalakan agen.
3. Agen: simpan registri batch secara persisten (user, status, `plan_version`, hasil per item;
   tanpa isi email dan `pii_map`), dan simpan token Gmail per user (entri keyring per `userId`).
4. Buat layanan HTTP di `gmail-agent/` yang membungkus `InboxGraph`: `POST /v1/batches`,
   `GET /v1/batches/{id}`, `POST …/execute`, `POST …/cancel`, serta `/auth/login` dan
   `/auth/status` per user.
5. Buat driver `http` untuk `AgentClient` di Laravel. Panggilan ke agen dan sync status berjalan
   lewat Job di queue, sehingga UI tetap responsif. Tes kontrak memakai fixture yang sama
   dengan `BatchSyncService` dan `FakeAgentClient`.
6. Alur Hubungkan Gmail di `/pengaturan`, dengan `wire:poll` ke `/auth/status`.
7. Uji ujung ke ujung dengan `GMAIL_BACKEND=mock`, lalu dengan akun Gmail uji.

Kriteria selesai: skenario `docs/demo-skenario.md` berjalan dengan `AGENT_DRIVER=http` tanpa
mengubah UI.

### Langkah 3: kualitas klasifikasi

- Validasi di kode: tolak prioritas Nanti bila `needs_reply` true, lalu minta model memperbaiki
  (seperti aturan "Promosi/Spam harus Nanti" yang sudah ada).
- Perbesar dataset menjadi sekitar 80–100 thread (10–15 per kategori), fokus pada kasus sulit:
  tenggat relatif, thread berbalasan, dua bahasa, pengumuman yang meminta tindakan, phishing
  halus, dan kandidat Sampah.
- Pisahkan set pengembangan (`eval/dataset.json`) dan set uji (`eval/holdout.json`). Rubrik hanya
  diubah berdasarkan set pengembangan.
- Label diberi manusia berdasarkan rubrik, dengan alasan di kolom `notes`. Bila memungkinkan, dua
  orang memberi label secara terpisah.
- Jalankan ulang evaluasi dan perbarui `docs/evaluasi-confidence.md`.

### Langkah 4: kebijakan data dan keamanan

- Hapus kolom lama `draft_body`/`reason` setelah riwayat lama dimigrasikan atau tidak diperlukan.
- Jadwalkan `batches:prune-review-data` di scheduler Laravel.
- Hasilkan kode peringatan `REPLY_TO_DOMAIN_MISMATCH`, `NEW_RECIPIENT`, `CROSS_THREAD_DATA` di
  builder agen. Skema tidak perlu diubah.
- Putuskan apakah prompt obrolan/API perlu diredaksi sebelum disimpan.

- Sampah: buat tool `trash_thread` dengan konfirmasi per item, atau keluarkan Sampah dari usulan
  agen sampai tool itu ada.

### Langkah 5: tugas kuliah dan halaman pendukung

- Landing page, halaman 404 (`Route::fallback`), `/pengaturan` dengan status Senopati/Ollama.
- Peran admin/tester dengan Gate, `/admin` dengan widget.
- Hapus riwayat dengan soft delete dan pesan flash.

### Langkah 6: keputusan produk dan uji pengguna

- Apakah obrolan bisa memanggil agen Gmail (`agent/turns`) di v1 atau v1.1.
- Packaging (NativePHP dan cara membundel layanan Python).
- Uji oleh pengguna sasaran; di luar jaringan kampus agen diarahkan ke Ollama.
- Fase 3 (run terjadwal tanpa interaksi) setelah alur manual stabil.

## 11. Dokumen terkait

| Dokumen | Isi |
|---|---|
| `README.md` | Setup Laravel, API chat (P11), skema dan relasi (P9) |
| `gmail-agent/README.md` | Setup agen, OAuth Gmail |
| `docs/contract-laravel-python.md` | Kontrak data dan perintah Laravel ↔ agen |
| `docs/demo-skenario.md` | Langkah demo `/batch` |
| `docs/evaluasi-confidence.md` | Metode dan hasil evaluasi klasifikasi |
| `contracts/plan-schema.json` | JSON Schema `PlanSnapshot` |
