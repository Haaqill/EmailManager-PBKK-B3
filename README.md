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
