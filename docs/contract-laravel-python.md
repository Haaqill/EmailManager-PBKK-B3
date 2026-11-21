# Kontrak Laravel ↔ Python (tahap 1)

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

## 5. Format sync (`GET /v1/batches/{id}`, usulan)

Endpoint ini belum ada (di luar tahap 1). `BatchSyncService::sync()` mengharapkan JSON berikut;
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

## 6. Keputusan yang belum diambil

- Satu akun Gmail per instalasi atau per user.
- `agent/turns` masuk v1 atau v1.1.
- Cara membundel FastAPI di build NativePHP.

## 7. Riwayat perubahan

| Tanggal | Perubahan |
|---|---|
| 16 Nov 2026 | Versi pertama: skema `PlanSnapshot`, kebijakan data, penyimpanan minimal Laravel. |
| 17 Nov 2026 | Tambah `also_archive` agar item arsip + draf tidak kehilangan niat arsip. |
| 18 Nov 2026 | `confidence` diubah dari angka 0..1 menjadi tiga tingkat (`tinggi`/`sedang`/`rendah`) yang dihasilkan klasifikasi; nilai hilang/tidak valid menjadi `null`. |
