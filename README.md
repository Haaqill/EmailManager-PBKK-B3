# Gmail Inbox Manager

Repository ini memuat dua aplikasi yang berbeda, jadi direktori sumbernya sengaja
dipisahkan:

- **Agen Gmail Python** berada di root (`app/`, `tests/`, `eval/`).
- **Aplikasi Laravel untuk Tugas 9** berada di [`laravel/`](./laravel/).
- [`EmailManager-PBKK-B3/`](./EmailManager-PBKK-B3/) adalah salinan/referensi
  proyek terdahulu; bukan lokasi untuk menjalankan aplikasi Tugas 9.

Jangan pindahkan direktori `laravel/app` ke root: keduanya memiliki folder `app`
dengan bahasa dan fungsi berbeda.

## Agen Gmail Python

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest
```

`eval/dataset.json` berisi data tiruan untuk pengujian. `MockGmailAPIClient`
menyimpan perubahan label, arsip, dan draft hanya selama proses berjalan.

## Laravel Tugas 9

Lihat [`laravel/README.md`](./laravel/README.md) untuk instalasi, skema, seeder,
riwayat, dan tes Laravel. Laravel harus dijalankan dari direktori `laravel/`.
