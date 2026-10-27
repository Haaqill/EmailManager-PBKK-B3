# EmailManager-PBKK-B3

### Setup
```
# 1. Clone repo

# 2.
py -3.11 -m venv .venv
.venv\Scripts\activate

# 3.
pip install -r requirements.txt

# 4.
cp .env.example .env

# 5.
pytest  # harus hijau
```

### Dataset mock

`eval/dataset.json` adalah array JSON dengan satu objek `DatasetRow` per thread.
`MockGmailAPIClient` membaca file ini dan menyimpan perubahan label, arsip, serta
draft hanya selama proses berjalan.

### Gmail API OAuth (opsional)

Mode default adalah `GMAIL_BACKEND=mock`; tidak memerlukan Google account.
Untuk menghubungkan akun uji:

1. Buat project di [Google Cloud Console](https://console.cloud.google.com/), aktifkan **Gmail API**, dan siapkan OAuth consent screen. Untuk aplikasi berstatus Testing, tambahkan akun Gmail uji sebagai test user.
2. Buat OAuth client bertipe **Desktop app**, unduh file client secret, lalu simpan sebagai `credentials.json` di root proyek. File ini tidak boleh dimasukkan ke Git. Jangan memakai JSON OAuth bertipe **Web application** untuk flow ini; aplikasi akan menolaknya sebelum membuka browser.
3. Pastikan dependency terpasang (`pip install -r requirements.txt`) dan OS menyediakan backend keyring yang berfungsi. OAuth token disimpan lokal melalui keyring sistem, bukan `token.json`.
4. Pilih backend dengan `GMAIL_BACKEND=gmail` di `.env`, atau tambahkan `GMAIL_BACKEND = "gmail"` di bagian top-level `.streamlit/secrets.toml`. Prioritasnya environment proses, Streamlit secrets, `.env`, lalu default `mock`. Restart aplikasi setelah mengubah `.env`.
5. Pilih **Login Gmail / perbarui sesi** di sidebar dan setujui scope tunggal `gmail.modify`. Google akan mengarahkan browser kembali ke server lokal sementara.

Flow desktop ini mengirim redirect URI loopback dinamis: `http://localhost:<port-acak>/` (contoh: `http://localhost:53142/`, dengan trailing slash). Karena port dipilih OS pada setiap login, URI ini tidak didaftarkan sebagai URI web tetap. Di Google Cloud Console, pilih/ubah OAuth client menjadi **Desktop app**; bagian **Authorized redirect URIs** pada client Web tidak berlaku untuk flow ini. Jika Console yang sedang dibuka hanya menampilkan daftar URI web, itu tanda bahwa JSON yang diunduh adalah tipe client yang salah.

`client_id`, `client_secret`, `redirect_uri`, `cookie_secret`, dan
`server_metadata_url` di bagian `[auth]` Streamlit mengatur login OIDC ke
aplikasi, bukan izin Gmail API. Gmail API menggunakan OAuth Desktop App dari
`credentials.json` di root proyek. UI menampilkan **Mock Mode** untuk dataset
sintetis, **Gmail Connected** setelah profile Gmail berhasil diverifikasi,
atau pesan koneksi aman tanpa data akun/token saat verifikasi gagal.

Login dan pemeriksaan juga tersedia melalui `python -m app.gmail.auth login`
dan `python -m app.gmail.auth check`; logout dengan
`python -m app.gmail.auth logout`. Jika refresh token dicabut/kedaluwarsa,
jalankan login lagi. Gmail client digunakan hanya oleh workflow: scan dibatasi
10 thread di UI, detail thread dibaca sesuai kebutuhan, dan label/arsip/draft
hanya dijalankan setelah persetujuan review. Aplikasi tidak mengirim atau
menghapus email.
