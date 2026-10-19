# EmailManager-PBKK-B3

Agen pengelola inbox Gmail: merangkum, memberi label kategori dan prioritas,
mengarsip, dan membuat **draft** balasan. Setiap aksi ditinjau pengguna dulu
lewat tabel review. Agen tidak pernah mengirim atau menghapus email.

### Setup (Windows PowerShell)
```
# 1. Clone
git clone https://github.com/Haaqill/EmailManager-PBKK-B3.git
cd EmailManager-PBKK-B3

# 2. Virtualenv (Python 3.11 atau lebih baru)
py -3.11 -m venv .venv          # atau: py -3.13 -m venv .venv
.venv\Scripts\activate          # jika ditolak: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
                                # prompt harus diawali (.venv)

# 3. Dependensi
pip install -r requirements.txt

# 4. Konfigurasi (default LLM_BACKEND=mock, tanpa API key)
cp .env.example .env

# 4b. (Opsional) Pakai LLM kampus "Senopati" — edit .env:
#     LLM_BACKEND=campus
#     LLM_BASE_URL=...     ┐
#     LLM_API_KEY=...      ├ minta ke Lima lewat jalur privat; JANGAN di-commit
#     LLM_MODEL=...        ┘
#     Cek koneksi:  python smoke_test_llm.py   (exit code 0 = lolos)

# 5. Tes — harus hijau
pytest

# 6. Jalankan aplikasi → http://localhost:8501 (hentikan: Ctrl+C)
streamlit run app/ui/streamlit_app.py
```

Jika `pytest` atau `streamlit` tidak ditemukan, pastikan venv aktif lalu ulangi langkah 3.

### Menjalankan demo

```
streamlit run app/ui/streamlit_app.py
```

Browser terbuka di `localhost:8501`. Klik **Proses 10 email**, periksa/edit tabel
(kategori, prioritas, aksi, draft; hapus centang untuk menolak), lalu **Jalankan**.
Laporan menunjukkan aksi yang berhasil dan gagal.

Mode LLM (atur di `.env`, lalu **restart** Streamlit karena konfigurasi di-cache):

| `LLM_BACKEND` | Perilaku |
|---|---|
| `mock` (default) | Offline; jawaban klasifikasi dan draft diambil dari `expected` di dataset. Tidak butuh API key. |
| `campus` | LLM kampus "Senopati" (`qwen3:14b`, OpenAI-compatible). Isi `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. |

**Demo saat ini memakai `mock`.** Mode `campus` sudah diimplementasikan dan teruji
dengan respons rekaman, tetapi saat pengujian (19 Okt) gateway Senopati sedang
kewalahan: permintaan sekecil "Jawab: OK" pun berakhir `504 Gateway Time-out`
setelah 60 detik, lalu `429 max_parallel_requests` (limit 2 permintaan paralel per
API key). Karena hambatan ini di luar kendali aplikasi, demo memakai `mock` agar
alur lengkap (baca → klasifikasi → review → eksekusi → laporan) bisa ditunjukkan
dengan andal. Dengan `mock`, kebenaran klasifikasi berasal dari kunci jawaban, jadi
yang didemokan adalah alur aplikasi, bukan kualitas LLM.

Gmail selalu `MockGmailAPIClient`: tidak ada email sungguhan yang diubah, dan
perubahan hilang saat **Reset inbox palsu** atau restart.

### Dataset mock

`eval/dataset.json` adalah array JSON dengan satu objek `DatasetRow` per thread
(10 thread sintetis). `MockGmailAPIClient` membaca file ini dan menyimpan perubahan
label, arsip, serta draft hanya selama proses berjalan.

### Masalah yang diketahui

- **429 / 504 dari LLM kampus**: gateway sedang ramai. Pakai `LLM_BACKEND=mock`,
  atau coba lagi di jam sepi dengan batch kecil (slider di sidebar). Jangan
  menekan "Proses" berulang kali: tiap percobaan yang gagal bisa menahan slot
  paralel API key lebih lama.
- **Batch kosong / berkurang**: mock hanya mengambil email 7 hari terakhir. Tanggal
  di `eval/dataset.json` (18–19 Okt) perlu digeser jika demo setelah ±25 Okt.
