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
| 21 Nov 2026 | campus (`qwen3:14b`, gateway `senopati.lab-alpro.com`) | 3 | Lihat di bawah. |
| 22 Nov 2026 | campus (`qwen3:14b`, gateway sama) | 3 | Setelah rubrik dan label diperbaiki. Lihat di bawah. |

### Hasil campus, 21 Nov 2026 (30 klasifikasi, 0 gagal, 0 confidence kosong)

| Level | n | Kategori | Aksi | Keduanya | Prioritas | Injeksi |
|---|---|---|---|---|---|---|
| tinggi | 27 | 89% | 89% | 85% | 48% | 8 |
| sedang | 3 | 33% | 67% | 33% | 33% | 1 |
| rendah | 0 | – | – | – | – | 0 |
| semua | 30 | 83% | 87% | 80% | 47% | 9 |

Stabilitas antarputaran: level sama 80%, label (kategori, prioritas, aksi, `needs_reply`) sama 50%.

Temuan:

- **Model hampir selalu menjawab `tinggi`** (27 dari 30) dan tidak pernah `rendah`. Level
  `tinggi` tetap salah 4 kali (85% benar), jadi `tinggi` tidak boleh dibaca sebagai "pasti benar".
- Urutan tinggi ≥ sedang terpenuhi pada gabungan, tetapi `sedang` hanya 3 sampel. Satu putaran
  malah melanggar urutan. Belum ada bukti kalibrasi.
- Kesalahan kategori/aksi berulang pada thread yang sama: t003 (pengumuman dikira akademik/keep,
  2 dari 3 putaran) dan t006 (spam dikira pengumuman, 2 dari 3 putaran, sekali dengan `sedang`).
- Injeksi: t008 dan t009 selalu benar. t007 sekali salah kategori (pribadi, bukan tugas), dan
  pada putaran itu modelnya memberi `sedang`.
- **Prioritas hanya 47% cocok** dan kesalahannya sistematis (t001 Normal vs Mendesak, t002
  Mendesak vs Normal, t004/t010 Nanti vs Normal). Confidence tidak menilai prioritas. Perlu ditinjau
  apakah label `expected` di dataset atau rubrik prioritas di prompt yang perlu diperbaiki.

### Perbaikan rubrik dan label, 22 Nov 2026

Tinjauan atas temuan prioritas menunjukkan sebagian kesalahan berasal dari kunci jawaban dan
rubrik, bukan dari model. Label hanya diubah bila bertentangan dengan rubrik dan isi email,
bukan supaya cocok dengan jawaban model.

- Rubrik prioritas di `SYSTEM_CLASSIFY` kini mendefinisikan Mendesak, Normal, dan Nanti, dengan
  patokan tanggal pesan terakhir di thread. `build_thread_message` menambahkan nama hari pada
  tanggal pesan (mis. `(Minggu)`) agar "Jumat"/"Selasa" di isi email bisa dihitung.
- Rubrik kategori mempertegas: pemberitahuan unit kampus untuk banyak mahasiswa (mis. perubahan
  ruang) adalah Pengumuman; Spam adalah pesan yang meminta kata sandi, kode, data, atau
  pembayaran, atau meniru layanan resmi.
- Label: t001 Mendesak → Normal (tenggat 5 hari setelah pesan); t002 Normal → Mendesak
  (bimbingan esok hari dan perlu konfirmasi). t003 tetap Pengumuman/Nanti/archive.
- t006 ditulis ulang menjadi phishing yang jelas (meminta kata sandi dan kode lewat domain
  tiruan). Versi lama justru melarang mengirim kata sandi, sehingga tidak cocok dengan label Spam.
- Tes: `gmail-agent/tests/test_prompt_rubrik.py`.

Hasil campus setelah perbaikan (30 klasifikasi, 0 gagal, 0 confidence kosong):

| Level | n | Kategori | Aksi | Keduanya | Prioritas | Injeksi |
|---|---|---|---|---|---|---|
| tinggi | 29 | 97% | 93% | 90% | 76% | 9 |
| sedang | 1 | 100% | 100% | 100% | 0% | 0 |
| rendah | 0 | – | – | – | – | 0 |
| semua | 30 | 97% | 93% | 90% | 73% | 9 |

Stabilitas antarputaran: level sama 90%, label sama 50%.

- "Keduanya" naik dari 80% ke 90%, prioritas dari 47% ke 73%. t001, t006, dan t003 (kategori)
  kini selalu benar.
- Sisa kesalahan: t004 dua kali diarsipkan (seharusnya keep); t004/t010 tetap diberi Nanti
  padahal `needs_reply` true, yang bertentangan dengan rubrik; t003 kadang Normal; t002 sekali
  Normal; t007 sekali salah kategori (injeksi).
- Confidence tetap hampir selalu `tinggi` (29 dari 30); urutan tinggi ≥ sedang tidak bisa
  dinilai dengan 1 sampel `sedang`. Kesimpulan kalibrasi tidak berubah.

### Keterbatasan

- Dataset hanya 10 thread, 3 di antaranya injeksi. Satu thread bisa menggeser akurasi satu
  level puluhan persen, jadi hasil apa pun hanya indikasi, bukan bukti kalibrasi.
- Aksi di klasifikasi hanya `keep`/`archive`; `trash` belum dinilai.

## Status di UI

Level tetap ditampilkan redup dengan keterangan bahwa itu perkiraan model yang belum
terkalibrasi dan cenderung terlalu yakin. Item `rendah` tidak ikut "Setujui semua yang aman";
aturan ini hanya menambah kehati-hatian, jadi berlaku apa pun hasil evaluasinya (pada evaluasi
ini model tidak pernah memberi `rendah`, jadi praktis aturan ini belum pernah terpicu).

Langkah lanjutan yang disarankan: perbesar dataset (terutama email ambigu), tinjau label
prioritas, dan ulangi evaluasi sebelum level dipakai untuk apa pun selain sorotan.
