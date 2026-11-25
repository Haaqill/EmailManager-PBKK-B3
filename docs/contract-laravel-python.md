# Kontrak Laravel ↔ Python (tahap 1 dan 2)

Sumber kebenaran skema: `gmail-agent/app/privacy/contract.py`.
JSON Schema hasil ekspor: `contracts/plan-schema.json` (dibuat ulang dengan
`python export_plan_schema.py` dari `gmail-agent/`; tes `test_plan_contract.py` gagal bila
file ini tertinggal dari kode).

## 1. Tujuan dan ruang lingkup tahap 1

Tahap 1 menetapkan **bentuk data** yang dikirim agen Python ke Laravel untuk satu batch,
**kebijakan data** di kedua sisi, dan **penyimpanan minimal** di Laravel.

Termasuk tahap 1:

- skema `PlanSnapshot`/`PlanItem` (Pydantic) dan ekspor JSON Schema-nya;
- builder `build_plan_snapshot(plan, raw_threads, pii_map, plan_version)` yang mengubah
  `InboxState.plan` (teks teredaksi) menjadi `PlanSnapshot` (teks asli);
- tabel `batches`, kolom kontrak di `batch_plan_items`, `BatchSyncService`, dan command
  `batches:prune-review-data` di Laravel.

Bukan tahap 1: endpoint FastAPI, `AgentClient` HTTP di Laravel, UI `/batch`, endpoint
`/auth/*`, dan `agent/turns`.

## 2. Perubahan terhadap `InboxState.plan` dan alasannya

`InboxState.plan` berisi `app.contracts.PlanItem` (internal agen, teks teredaksi). Yang dikirim ke
Laravel adalah `app.privacy.contract.PlanItem`. Field yang ditambahkan:

| Field | Tipe | Sumber data | Kenapa ditambah |
|---|---|---|---|
| `item_id` | `string` (`i_01`, `i_02`, …) | builder, urutan plan | ID stabil per `plan_version`; dipakai Laravel untuk keputusan dan sebagai kunci idempotensi eksekusi. |
| `thread{}` | `ThreadInfo` (`subject`, `from_name`, `from_domain`, `date`, `attachments[]`) | metadata thread asli (sebelum redaksi) | Laravel butuh subjek dan pengirim untuk menampilkan baris dan riwayat; di plan lama hanya ada `thread_id`, sedangkan Laravel tidak boleh memegang token Gmail untuk mencarinya sendiri. |
| `confidence` | `"tinggi"`, `"sedang"`, `"rendah"`, atau `null` | keluaran klasifikasi (`ClassificationOutput.confidence`); hilang/tidak valid → `null` | Keyakinan model terhadap kategori dan aksi yang diusulkan, untuk menyorot baris yang meragukan di UI. Tiga tingkat, bukan angka: skor angka dari LLM memberi presisi palsu, sedangkan tiga tingkat jujur soal ketidakpastian. **Bukan gerbang keamanan**: tidak mengubah keputusan bawaan, `requires_confirmation`, atau kewajiban review; persetujuan manusia tetap wajib untuk semua item. |
| `draft.to` / `draft.subject` | `string` | header thread (Reply-To atau From pesan yang dibalas; `Re: <subjek>`) | Prompt persetujuan Fase 2 menampilkan penerima sebenarnya; UI harus menampilkan hal yang sama karena pengguna menyetujui draft untuk penerima itu. Berasal dari header thread, bukan dari LLM. |
| `warnings[]` | `{code, message}[]` | builder | Peringatan wajib Fase 2 dibuat terstruktur supaya UI bisa menonjolkannya tanpa mengurai teks. Ditambah `UNRESOLVED_PLACEHOLDER` untuk placeholder yang gagal dipulihkan. |
| `requires_confirmation` | `boolean` | builder: `action == "trash"` | Trash berisiko tinggi dan wajib konfirmasi per item; ditentukan di Python agar tidak bergantung pada UI. |
| `also_archive` | `boolean` (default `false`) | builder: item `archive` yang punya draf | Plan lama bisa berisi arsip dan draf sekaligus, sedangkan `action` hanya satu nilai; tanpa field ini niat arsip hilang dan pengguna tidak melihat seluruh aksi yang ia setujui. Hanya boleh `true` bila `action == "draft_reply"`. |
| `plan_version` (level batch) | `integer` ≥ 1 | agen | Mencegah persetujuan dari tampilan yang sudah usang. |

Catatan pemetaan nama dan nilai:

- `draft_body` → `draft.body`; `thread_id` tetap `thread_id`.
- `category` dan `priority` diubah ke huruf kecil (`Akademik` → `akademik`, `Mendesak` → `mendesak`).
- `action`: `keep` → `label_only`, `archive` → `archive`, `trash` → `trash`; item yang punya draft
  (dan bukan `trash`) → `draft_reply`.
- Item `archive` yang punya draf dikirim sebagai `action: "draft_reply"` dengan `also_archive: true`:
  draf balasan dibuat, lalu thread diarsipkan. Menyetujui item berarti menyetujui keduanya.
- `summary` dan `needs_reply` lama tidak dikirim.
- Validasi: `draft` wajib ada **jika dan hanya jika** `action == "draft_reply"`;
  `requires_confirmation` wajib `true` **jika dan hanya jika** `action == "trash"`;
  `also_archive` hanya boleh `true` bila `action == "draft_reply"`.

## 3. Kebijakan data

### a. Di Python

- `restore()` (dari `app/privacy/redact.py`) dipanggil di Python; **hanya teks asli yang keluar**
  ke Laravel. LLM tidak pernah melihat data pribadi.
- Yang **tidak pernah keluar** dari Python: `pii_map`, token Gmail, teks yang sudah diredaksi.
- Teks hasil restore **tidak ditulis ke log atau stdout**.
- Setelah restore, sisa placeholder (`<PERSON_n>`, `<EMAIL_n>`, `<PHONE_n>`, `<ACCOUNT_n>`)
  dideteksi dengan regex milik `redact.py` dan dilaporkan sebagai warning
  `UNRESOLVED_PLACEHOLDER`. `[SECRET]` bukan placeholder dan tidak dipulihkan, jadi tidak memicu
  warning.

### b. Penyimpanan di Laravel

| Kelompok | Isi | Umur |
|---|---|---|
| **Kekal** | `batches` (`agent_batch_id`, `status`, `plan_version`, `filters`, `summary` berisi angka saja, `finished_at`) dan kolom `batch_plan_items` selain dua kolom sementara: `item_id`, `thread_id`, `subject` (maks. 255 karakter), `from_name`, `category`, `priority`, `action`, `decision`, `result_status`, `applied` (hanya nama label, flag arsip, `draft_id`) | selama riwayat disimpan |
| **Sementara** | `review_data` (`also_archive`, `reason`, `confidence`, `draft{to,subject,body}`, `warnings[]`, `requires_confirmation`, `attachments`) dan `edited_draft_body` | dikosongkan saat batch `done`/`failed`/`cancelled`/`expired` |
| **Tidak disimpan** | isi email, snippet | — |

- `decision` dan `edited_draft_body` adalah status lokal Laravel dan tidak pernah ditimpa oleh sync
  dari agen. Bila `plan_version` berubah selama review, semua `decision` kembali ke `pending` dan
  `edited_draft_body` dikosongkan.
- Batch `awaiting_review` yang tidak disentuh lebih dari N hari (default 7) ditandai `expired` oleh
  `php artisan batches:prune-review-data`, dan data sementaranya dikosongkan. Command ini belum
  dijadwalkan karena `routes/console.php` belum memakai scheduler.
- Kolom skema lama di `batch_plan_items` (`chat_session_id`, `gmail_thread_id`, `draft_body`,
  `reason`) masih ada untuk riwayat lama. Baris dari kontrak ini tidak mengisinya. `draft_body` dan
  `reason` lama menyimpan teks secara kekal, jadi bertentangan dengan kebijakan di atas;
  penghapusannya dijadwalkan di PR terpisah.

### c. Status kebijakan

Aturan kampus soal data pribadi **belum terbit**. Kebijakan ini harus ditinjau ulang begitu aturan
itu ada.

## 4. Kode warning

| Kode | Arti | Status tahap 1 |
|---|---|---|
| `REPLY_TO_DOMAIN_MISMATCH` | Alamat penerima draft (Reply-To) berbeda domain dengan pengirim thread. | Dicadangkan; belum dihasilkan builder. |
| `NEW_RECIPIENT` | Draft ditujukan ke alamat yang belum pernah berkorespondensi dengan pengguna. | Dicadangkan; belum dihasilkan builder. |
| `CROSS_THREAD_DATA` | Draft memuat data yang berasal dari thread lain. | Dicadangkan; belum dihasilkan builder. |
| `UNRESOLVED_PLACEHOLDER` | Setelah `restore()`, masih ada placeholder di `reason` atau `draft.body`. Pesan hanya menyebut jenisnya (mis. `PERSON`), bukan placeholdernya. | Dihasilkan builder. |

Tiga kode pertama dicadangkan karena repo belum punya logika peringatan Fase 2 yang bisa dipakai
ulang. Saat logika itu dibuat, hasilnya diisi ke `warnings[]` di builder tanpa mengubah skema.

## 5. Format sync (`GET /v1/batches/{id}`)

Endpoint ini dikunci di tahap 2 (bagian 6) dan diimplementasikan oleh server agen.
`BatchSyncService::sync()` mengharapkan JSON berikut;
contoh lengkap ada di `tests/Fixtures/agent/`.

```json
{
  "batch_id": "b_…",
  "status": "queued|scanning|classifying|drafting|awaiting_review|executing|done|failed|cancelled",
  "filters": { "…": "…" },
  "plan": { "plan_version": 1, "items": [ "PlanItem …" ] },
  "report": {
    "summary": { "approved": 1, "rejected": 1, "actions_ok": 2, "actions_failed": 0 },
    "results": [
      { "item_id": "i_01", "status": "ok",
        "applied": { "labels": ["Kategori/Akademik"], "archived": false, "draft_id": "r-…" } }
    ]
  }
}
```

- `plan` boleh `null` sebelum `awaiting_review`; `report` hanya dibaca saat status akhir.
- `expired` hanya dipakai Laravel. Payload agen dengan status itu ditolak.
- Nilai enum yang tidak valid membuat `InvalidAgentPayload` dilempar, dan tidak ada baris yang
  tersimpan.
- Dari `report.summary` hanya nilai angka yang disimpan. Dari `applied` hanya `labels`,
  `archived`, dan `draft_id`.

## 6. Perintah Laravel → agen (tahap 2, dikunci 23 Nov 2026)

Antarmuka di Laravel: `App\Services\Agent\AgentClient`, dipilih lewat `config('agent.driver')`
(`AGENT_DRIVER`). Saat ini hanya ada driver `fake` (`FakeAgentClient`, mode demo dengan data
contoh dari `resources/demo/batch_awaiting_review.json`). Driver `http` belum ada; memilihnya
melempar pengecualian. Bagian ini adalah acuan untuk driver `http` dan server agen.

Satu hal belum dikunci: siapa yang menyalakan proses agen dan di port mana. Keputusan itu
menunggu hasil percobaan `native:build` (bagian 7).

### a. Koneksi dan autentikasi

- Laravel memanggil agen di `AGENT_URL`. Agen hanya mendengar di `127.0.0.1`.
- Setiap request membawa `Authorization: Bearer <AGENT_TOKEN>`. Token yang sama diisi di `.env`
  root (Laravel) dan `gmail-agent/.env`, tidak di-commit, dan dibandingkan secara constant-time
  oleh agen. Token tidak ada atau salah → 401.
- Setiap request membawa header `X-User-Id: <users.id>`. Agen memercayai header ini hanya karena
  tokennya valid. Agen memakai id ini untuk memilih token Gmail milik user (satu akun Gmail per
  user, bagian 7).
- Batch terikat pada user yang memulainya. Batch milik user lain diperlakukan seperti tidak ada
  (404, bukan 403), supaya keberadaannya tidak bocor.
- Konfigurasi Laravel (belum ada): `AGENT_URL`, `AGENT_TOKEN`, `AGENT_TIMEOUT`, diisi juga di
  `.env.example` tanpa nilai rahasia.

### b. Endpoint

| Operasi `AgentClient` | HTTP | Body request | Respons sukses |
|---|---|---|---|
| `startBatch(userId, filters)` | `POST /v1/batches` | `{"filters": {"max_results": 1..10}}` | 202 `{"batch_id": "b_…", "status": "queued"}`; `batch_id` adalah nilai kembali `startBatch` |
| `getBatch(userId, agentBatchId)` | `GET /v1/batches/{id}` | — | 200, payload bagian 5 |
| `execute(userId, agentBatchId, planVersion, decisions)` | `POST /v1/batches/{id}/execute` | `{"plan_version": n, "decisions": [...]}` | 202 `{"status": "executing"}` |
| `cancel(userId, agentBatchId)` | `POST /v1/batches/{id}/cancel` | — | 202 `{"status": "cancelled"}` |
| *(baru)* status Gmail | `GET /v1/auth/status` | — | 200 `{"status": "connected\|not_connected\|expired"}` |
| *(baru)* mulai login Gmail | `POST /v1/auth/login` | — | 200 `{"auth_url": "https://accounts.google.com/…"}` |

- `startBatch` dan `execute` langsung kembali (202); pekerjaan berjalan di latar belakang agen.
  Tidak ada endpoint yang menunggu LLM atau Gmail.
- `execute` pada batch `executing`/`done` mengembalikan 202 tanpa mengeksekusi ulang (idempoten).
- `cancel` pada batch yang sudah `cancelled` mengembalikan 202. `cancel` pada batch `executing`,
  `done`, atau `failed` → 409 `invalid_state`.
- Dua operasi auth ditambahkan ke `AgentClient` (nama metode ditentukan saat implementasi) dan
  diimplementasikan juga oleh `FakeAgentClient`.

### c. Galat

Body galat: `{"error": {"code": "<kode>", "message": "<pesan singkat>"}}`. Pesan tidak boleh memuat
isi email, alamat email, atau token.

| HTTP | `code` | Kapan | Di Laravel |
|---|---|---|---|
| 401 | `unauthorized` | `AGENT_TOKEN` tidak ada atau salah | `AgentUnavailable`, dicatat di log sebagai salah konfigurasi |
| 404 | `batch_not_found` | batch tidak dikenal atau milik user lain | `AgentUnavailable` |
| 409 | `plan_version_mismatch` | `plan_version` tidak sama dengan versi terbaru | `PlanVersionMismatch` |
| 409 | `invalid_state` | operasi tidak sah untuk status batch (mis. `execute` sebelum `awaiting_review`) | `PlanVersionMismatch` untuk `execute`; `AgentUnavailable` untuk lainnya |
| 409 | `gmail_not_connected` | `startBatch` saat Gmail user belum terhubung atau `expired` | `AgentUnavailable`; UI mengarahkan ke Hubungkan Gmail |
| 422 | `invalid_request` | body atau header tidak valid | `AgentUnavailable`, dicatat di log (bug di Laravel) |
| 503 | `llm_unavailable`, `gmail_unavailable` | layanan luar tidak tersedia saat menerima perintah | `AgentUnavailable` |
| — | — | koneksi gagal atau timeout | `AgentUnavailable` |

- Laravel meneruskan `code` di `AgentUnavailable` agar UI bisa memilih pesan yang tepat.
- Payload sukses yang tidak sesuai bagian 5 tetap menghasilkan `InvalidAgentPayload`.
- Galat saat batch sudah berjalan (LLM mati di tengah klasifikasi) tidak dikirim sebagai HTTP
  error, melainkan sebagai status batch `failed` pada `getBatch`.

### d. Timeout, polling, dan pengulangan

- Timeout setiap panggilan Laravel ke agen 10 detik (`AGENT_TIMEOUT`).
- Laravel menyinkronkan status (`getBatch`) setiap 2 detik selama batch `queued`, `scanning`,
  `classifying`, `drafting`, atau `executing`. Sync berjalan di queue, bukan di request Livewire.
- `startBatch` tidak diulang otomatis, karena pengulangan bisa membuat dua batch. `getBatch`
  cukup dicoba lagi pada sync berikutnya. `execute` aman diulang karena idempoten.

### e. Agen di-restart

| Status batch saat agen berhenti | Setelah agen menyala lagi |
|---|---|
| `queued`, `scanning`, `classifying`, `drafting` | `failed`; pengguna memulai batch baru |
| `awaiting_review` | `failed`; pengguna memulai batch baru. Belum ada aksi Gmail yang dijalankan. |
| `executing` | `failed`; report berisi aksi yang sudah dijalankan (`ok`/`failed`), sisanya `skipped`. Eksekusi tidak diulang otomatis. |

- Review tidak bisa dilanjutkan setelah restart karena `pii_map` hanya ada di memori agen dan tidak
  boleh diserialisasi (bagian 3a). Tanpa peta itu, plan tidak bisa dipulihkan ke teks asli dan
  `create_draft_reply` tidak bisa memulihkan isi draf. Me-refresh halaman, logout, atau
  me-restart Laravel tidak berpengaruh; yang dimaksud di sini hanya proses agen yang berhenti.
- Agen menyimpan secara persisten (tanpa isi email dan tanpa `pii_map`): pemetaan batch → user,
  status, `plan_version`, dan hasil per item yang sudah dijalankan. Dengan begitu, setelah restart
  agen menjawab `getBatch` dengan status `failed`, bukan 404.
- Checkpoint LangGraph persisten tidak diwajibkan oleh kontrak ini.

### f. Login Gmail

- `POST /v1/auth/login` membuat URL login OAuth (Desktop App, loopback) untuk user di
  `X-User-Id`, lalu agen menunggu redirect di latar belakang. Login baru untuk user yang sama
  menggantikan yang lama.
- Laravel membuka `auth_url` di browser, lalu memanggil `GET /v1/auth/status` setiap 2 detik
  (`wire:poll`) sampai `connected`.
- `expired`: refresh token dicabut atau kedaluwarsa; pengguna login ulang.
- Token Gmail tidak pernah keluar dari agen. Respons status hanya berisi `status`.

### g. Keputusan item (`execute`)

Bentuk `decisions`:

```json
[
  { "item_id": "i_01", "decision": "approve", "edited_draft_body": "…" },
  { "item_id": "i_02", "decision": "reject" },
  { "item_id": "i_07", "decision": "approve", "confirmed_trash": true }
]
```

- Hanya item yang diputuskan eksplisit yang dikirim. Item `pending` tidak dikirim dan **tidak
  dijalankan** (default-deny); di report statusnya `skipped`.
- `edited_draft_body` hanya untuk item `draft_reply` yang disetujui dan drafnya diubah pengguna
  (maks. 10.000 karakter).
- `confirmed_trash: true` wajib untuk item `requires_confirmation` yang disetujui. Agen tidak
  menjalankan trash tanpa flag ini.
- `execute` idempoten: panggilan ulang pada batch `executing`/`done` tidak mengeksekusi ulang.
- Sebelum `execute`, Laravel mengambil `getBatch` terbaru. Bila `plan_version` berubah atau status
  bukan `awaiting_review`, Laravel tidak mengeksekusi, mereset keputusan, dan meminta pengguna
  meninjau ulang.
- Status report per item: `ok`, `failed`, `skipped`, `rejected`.

## 7. Keputusan

Sudah diambil (22 Nov 2026):

- **Satu akun Gmail per user.** Agen menyimpan token OAuth per user Laravel (token tetap hanya di
  Python). Setiap operasi `AgentClient` sudah membawa `userId`; agen wajib memakai token milik
  user itu dan menolak batch milik user lain.
- **UI utama adalah Laravel.** UI review Streamlit tetap ada di `gmail-agent/` sebagai alat
  pengembangan, bukan antarmuka pengguna.

Belum diambil:

- `agent/turns` masuk v1 atau v1.1.
- Siapa yang menyalakan proses agen, port bawaannya, dan cara membundelnya di build NativePHP.
  Menunggu hasil percobaan `native:build`.

## 8. Riwayat perubahan

| Tanggal | Perubahan |
|---|---|
| 16 Nov 2026 | Versi pertama: skema `PlanSnapshot`, kebijakan data, penyimpanan minimal Laravel. |
| 17 Nov 2026 | Tambah `also_archive` agar item arsip + draf tidak kehilangan niat arsip. |
| 18 Nov 2026 | `confidence` diubah dari angka 0..1 menjadi tiga tingkat (`tinggi`/`sedang`/`rendah`) yang dihasilkan klasifikasi; nilai hilang/tidak valid menjadi `null`. |
| 21 Nov 2026 | Tambah bagian 6 "Perintah Laravel → agen" (draf): empat operasi `AgentClient`, bentuk `decisions`, default-deny, `confirmed_trash`, idempotensi `execute`. |
| 22 Nov 2026 | Bagian 7: diputuskan satu akun Gmail per user dan Laravel sebagai UI utama (Streamlit tetap untuk pengembangan). |
| 23 Nov 2026 | Bagian 6 dikunci: autentikasi `AGENT_TOKEN` dan `X-User-Id`, endpoint batch dan auth, kode galat, timeout dan polling, perilaku saat agen restart (semua batch yang belum selesai menjadi `failed`, karena `pii_map` tidak disimpan), alur login Gmail. Cara menyalakan agen masih menunggu `native:build`. |
