# Skenario demo

Alur demo dari landing sampai laporan batch, dengan agen tiruan (`AGENT_DRIVER=fake`).

## Persiapan (sekali)

```sh
php artisan migrate                          # jangan migrate:fresh (menghapus riwayat chat)
php artisan db:seed --class=DemoSeeder       # hanya di APP_ENV=local
composer run dev                             # server + Vite
```

Pastikan `.env` berisi `AGENT_DRIVER=fake` (atau tidak diisi; bawaannya `fake`).

**Akun demo:** `demo@inbox-manager.test` / `password`. Ini kredensial contoh untuk demo lokal,
bukan akun sungguhan. Akun ini sama dengan yang dibuat `AgentDemoSeeder`.

## Langkah

| # | Langkah | Yang terlihat |
|---|---|---|
| 1 | Buka `/` | Halaman landing. |
| 2 | Klik **Log in**, masuk dengan akun demo | Diarahkan ke **Obrolan**. |
| 3 | Kirim pesan di Obrolan, mis. "Rangkum email ini: …" | Jawaban mengalir, lalu nama model dan latensi. Di bawah kolom pesan: "AI dapat membuat kesalahan." Obrolan memakai LLM sungguhan (Senopati, cadangan Ollama), jadi butuh koneksi. |
| 4 | Buka **Batch** di navigasi | Spanduk "Mode demo: data contoh, tidak terhubung ke Gmail", kartu **Mulai proses email**, daftar batch. |
| 5 | Isi jumlah email (1–10), klik **Mulai** | Halaman batch dengan tahap Scan → Klasifikasi → Draf berjalan otomatis (sekitar 2 detik per tahap). Bisa **Batalkan**. |
| 6 | Tunggu sampai **Review** | Ringkasan per aksi dan jumlah item butuh perhatian, lalu daftar item: subjek, pengirim, kategori, prioritas, aksi usulan, alasan, tingkat keyakinan (redup), peringatan, dan draf. |
| 7 | Tinjau item | Ubah isi draf (otomatis tersimpan saat keluar dari kolom), **Kembalikan ke draf asli**, **Setujui**/**Tolak**. Item Sampah hanya bisa disetujui lewat dialog konfirmasi. **Setujui semua yang aman** melewati item Sampah, berperingatan, dan berkeyakinan rendah. |
| 8 | Klik **Jalankan** | Dialog ringkasan jumlah aksi (label, draf, arsip, Sampah). Setelah dikonfirmasi: tahap Eksekusi, lalu **Laporan**. |
| 9 | Laporan | Jumlah berhasil, gagal, dilewati, ditolak, dan hasil per item. Item yang tidak diputuskan tercatat "Dilewati". Isi email dan draf sudah dihapus dari aplikasi. |

## Yang perlu diketahui saat demo

Pada mode ini **agen disimulasikan**. Tidak ada email Gmail yang dibaca dan tidak ada LLM yang
dipanggil untuk batch. Delapan item berasal dari `resources/demo/batch_awaiting_review.json`
(fiktif), statusnya maju berdasarkan waktu, dan "eksekusi" hanya menghitung laporan dari keputusan
Anda. Tingkat keyakinan di data contoh juga ditulis tangan, bukan hasil model.

Kode peringatan: dari agen sungguhan, saat ini hanya `UNRESOLVED_PLACEHOLDER` yang benar-benar
dihasilkan (placeholder data pribadi yang gagal dipulihkan). `REPLY_TO_DOMAIN_MISMATCH` di item
pertama hanya data contoh; kode itu baru dicadangkan di kontrak dan belum dihasilkan agen.
