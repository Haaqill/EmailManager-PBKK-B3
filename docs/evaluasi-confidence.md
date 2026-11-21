# Evaluasi confidence klasifikasi

`confidence` (`tinggi`/`sedang`/`rendah`) adalah penilaian diri LLM berdasarkan rubrik di
`SYSTEM_CLASSIFY`. Dokumen ini menjelaskan cara menguji apakah level itu bermakna: item
`tinggi` seharusnya lebih sering benar daripada `sedang`, dan `sedang` daripada `rendah`.

Confidence **bukan gerbang keamanan** (lihat `docs/contract-laravel-python.md`). Hasil evaluasi
hanya menentukan cara level ditampilkan di UI.

## Cara menjalankan

Dari folder `gmail-agent/`:

```sh
python -m eval.run_eval                                   # mock, tanpa jaringan
python -m eval.run_eval --backend campus --runs 3 --out hasil.json
```

- Hanya tahap klasifikasi: thread dari `eval/dataset.json` lewat `MockGmailAPIClient`,
  diredaksi oleh `fetch_thread`, lalu diklasifikasi oleh node `classify` di `InboxGraph`.
  Tidak ada draf dan tidak ada aksi Gmail.
- Keluaran hanya ID thread dan label (kategori, prioritas, aksi, `needs_reply`, confidence).
  Isi email, summary, reason, dan pesan error LLM tidak dicetak atau disimpan.
- `--backend campus` mengirim isi dataset (fiktif) ke `LLM_BASE_URL` di `.env`.

## Metrik

| Metrik | Arti |
|---|---|
| `n` per level | jumlah item yang diberi level itu; `kosong` = confidence null/tidak valid |
| akurasi kategori, aksi, keduanya | dibanding `expected` di dataset; "keduanya" adalah yang dinilai rubrik |
| prioritas, `needs_reply` | dilaporkan, tetapi tidak dinilai oleh confidence |
| `injeksi` | jumlah item `is_injection` di level itu |
| urutan | akurasi "keduanya" tidak naik dari tinggi → sedang → rendah; tidak dinilai bila <2 level berisi |
| stabilitas | dari beberapa putaran: porsi thread dengan level sama dan label sama di semua putaran |
| gagal | thread yang tidak terklasifikasi (dihitung terpisah, tidak masuk akurasi) |

Kode: `gmail-agent/eval/metrics.py`, `gmail-agent/eval/run_eval.py`; tes:
`gmail-agent/tests/test_eval.py`.

## Hasil

| Tanggal | Backend | Putaran | Hasil |
|---|---|---|---|
| 21 Nov 2026 | mock (`DatasetLLM`) | 2 | Uji asap saja. Akurasi 100% di semua level dan stabilitas 100%, karena jawaban mock disalin dari `expected` dan levelnya dari crc32 `thread_id`. **Tidak bermakna** untuk kualitas confidence. |
| — | campus (`qwen3:14b`) | — | Belum dijalankan. |

### Keterbatasan

- Dataset hanya 10 thread, 3 di antaranya injeksi. Satu thread bisa menggeser akurasi satu
  level puluhan persen, jadi hasil apa pun hanya indikasi, bukan bukti kalibrasi.
- Aksi di klasifikasi hanya `keep`/`archive`; `trash` belum dinilai.

## Status di UI

Sampai ada hasil dari LLM sungguhan, level ditampilkan redup dengan keterangan bahwa itu
perkiraan model yang belum dievaluasi. Item `rendah` tidak ikut "Setujui semua yang aman";
aturan ini hanya menambah kehati-hatian, jadi berlaku apa pun hasil evaluasinya.
