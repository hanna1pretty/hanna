# Hanna AI Bot

Bot Telegram berbasis [Pyrogram](https://docs.pyrogram.org/) yang menyediakan chat AI, vision, image generation, pilihan model, pencatatan pemakaian kredit, serta pengaturan provider melalui menu admin.

> **Status deployment:** kode ini sudah diaudit secara statis dan diperketat untuk deployment VPS. Tetap lakukan uji fungsional dengan bot dan API key milik Anda sebelum membuka akses publik.

## Fitur

- Chat AI melalui pesan privat Telegram.
- Analisis foto dengan caption atau prompt default.
- Image generation melalui endpoint OpenAI-compatible.
- Beberapa model dan provider yang dapat dipilih.
- Mode `ADMIN ONLY` sebagai default.
- Mode publik dengan batas harian user yang dapat dikonfigurasi; admin tidak terkena batas internal.
- Riwayat chat, model pilihan user, usage log, dan credit tracker di SQLite.
- Dukungan bot tambahan melalui `BOT_TOKEN_2`, `BOT_TOKEN_3`, dan seterusnya.
- Docker Compose dengan volume data/log, restart policy, dan healthcheck.

## Persyaratan

- VPS Linux dengan Docker Engine dan Docker Compose v2 (`docker compose`).
- Bot Telegram yang dibuat melalui [@BotFather](https://t.me/BotFather).
- Telegram `API_ID` dan `API_HASH` dari [my.telegram.org](https://my.telegram.org/).
- API key dari provider AI yang mendukung endpoint OpenAI-compatible.
- Domain atau port publik **tidak diperlukan** karena bot menggunakan koneksi keluar (long polling).

## Instalasi cepat di VPS

```bash
git clone https://github.com/hanna1pretty/hanna.git
cd hanna
cp .env.example .env
nano .env
mkdir -p data logs
docker compose up -d --build
docker compose ps
docker compose logs -f --tail=100
```

Jangan mengunggah atau meng-commit file `.env`. File tersebut sudah masuk `.gitignore` dan `.dockerignore`.

## Konfigurasi `.env`

Isi minimal berikut sebelum menjalankan container:

```dotenv
BOT_TOKEN=123456789:token-dari-botfather
API_ID=12345678
API_HASH=hash-dari-my.telegram.org
ADMIN_ID=123456789
```

Variabel penting lainnya:

| Variabel | Wajib | Default | Keterangan |
|---|---:|---:|---|
| `BOT_TOKEN` | Ya | - | Token bot utama dari BotFather. |
| `API_ID` | Ya | - | Angka dari my.telegram.org. |
| `API_HASH` | Ya | - | Hash dari my.telegram.org. |
| `ADMIN_ID` | Ya | - | ID Telegram admin; dapat berisi beberapa ID dipisah koma. |
| `TOP_TOOLS_API_KEY` | Tidak | kosong | API key provider awal. Jika kosong, set melalui `/setkey`. |
| `BASE_URL` | Tidak | `https://top-tools-ai.com/api/v1` | Base URL OpenAI-compatible provider awal. |
| `INITIAL_CREDITS` | Tidak | `220.00` | Saldo acuan untuk credit tracker lokal. |
| `DEFAULT_MODEL` | Tidak | `top-tools-ai` | Model awal untuk user baru; owner dapat memilih model Pay as you go secara manual. |
| `MAX_HISTORY` | Tidak | `20` | Jumlah pesan history per user dan bot. |
| `API_TIMEOUT` | Tidak | `60` | Timeout request provider dalam detik. |
| `API_RETRIES` | Tidak | `2` | Jumlah percobaan request. |
| `RETRY_DELAY` | Tidak | `2.0` | Jeda antar retry dalam detik. |
| `STREAM_UPDATE_INTERVAL` | Tidak | `0.8` | Interval minimum edit pesan Telegram saat streaming. |
| `MAX_IMAGE_BYTES` | Tidak | `10485760` | Batas foto vision, default 10 MiB. |
| `MAX_PROMPT_LENGTH` | Tidak | `4000` | Batas caption/prompt vision. |
| `MAX_FILE_BYTES` | Tidak | `5242880` | Batas file yang dibaca, default 5 MiB. |
| `MAX_EXTRACTED_CHARS` | Tidak | `20000` | Batas teks file yang dikirim ke AI. |
| `BOT_TOKEN_2` | Tidak | kosong | Bot tambahan kedua, jika diperlukan. |
| `PUBLIC_DAILY_REQUEST_LIMIT` | Tidak | `40` | Batas permintaan AI per user publik per hari. |
| `PUBLIC_DAILY_TOKEN_LIMIT` | Tidak | `100000` | Batas token AI per user publik per hari. |

Bot akan **gagal start dengan sengaja** jika `BOT_TOKEN`, `API_ID`, `API_HASH`, atau `ADMIN_ID` belum valid. Ini mencegah konfigurasi kosong membuat akses admin terbuka kepada semua orang.

## Setelah bot hidup

1. Kirim `/start` dari akun admin.
2. Kirim `/myid` bila perlu mengetahui Telegram ID.
3. Buka `API Settings` atau kirim `/api`.
4. Atur key dengan `/setkey <API_KEY>` jika belum mengisi `TOP_TOOLS_API_KEY`.
5. Atur provider lain dengan format:

   ```text
   /setprovider openrouter https://openrouter.ai/api/v1 sk-or-xxxx
   ```

6. Uji chat biasa, `/img sebuah rumah futuristik`, dan foto privat dengan caption.
7. Biarkan mode `ADMIN ONLY` selama pengujian. Aktifkan mode publik hanya setelah biaya, rate limit, dan provider sudah dipastikan.

Saldo pada menu `Saldo dan Limit` menampilkan saldo live dari endpoint provider bila provider menyediakannya. Pemakaian lokal ditampilkan terpisah dan bukan pengganti saldo provider. Saldo provider tetap tunduk pada limit, model, dan kebijakan provider; mode admin hanya melewati limit internal bot. Saat user publik mencapai limit, bot menampilkan instruksi untuk menghubungi admin terkait pembelian credit atau akses premium. Pembayaran belum otomatis dan tetap dilakukan melalui alur resmi provider/admin.

Paket premium awal yang ditampilkan bot adalah Rp5.000 untuk 7 hari, Rp15.000 untuk 30 hari, dan Rp35.000 untuk 90 hari. Setelah pembayaran diverifikasi manual, admin dapat menjalankan `/grantpremium <telegram_user_id> <hari>`. Akses premium melewati limit harian internal bot, tetapi tidak menghapus limit atau saldo dari provider AI.

Menu `Percakapan` memungkinkan user membuat beberapa sesi chat yang terpisah dan berpindah di antaranya tanpa mencampur riwayat. Riwayat lama dimigrasikan ke percakapan `Percakapan lama` saat bot dijalankan setelah update. Command premium admin yang tersedia: `/grantpremium`, `/premiumusers`, dan `/revokepremium`.

Ringkasan lengkap command admin, diagnostik `/ping`, status sistem, premium, provider, backup, dan update tersedia di [ADMIN_COMMANDS.md](ADMIN_COMMANDS.md).

> API key yang dimasukkan lewat `/setkey` atau `/setprovider` disimpan di SQLite pada volume `./data`. Batasi akses VPS dan backup file tersebut.

## Operasional Docker

```bash
# Status dan health
sudo docker compose ps
sudo docker inspect --format '{{json .State.Health}}' hanna-ai

# Log aplikasi
sudo docker compose logs -f --tail=200 hanna
# Log file di host
sudo tail -f logs/hanna.log

# Update dari GitHub
sudo docker compose down
git pull --ff-only
sudo docker compose up -d --build
sudo docker compose ps

# Restart tanpa build ulang
sudo docker compose restart

# Stop
sudo docker compose down
```

Container tidak mengekspos port HTTP. Healthcheck hanya memastikan SQLite dapat dibuka; status `healthy` bukan pengganti pengujian Telegram/API secara berkala.

## Backup dan restore

Database, session, dan log berada di host pada folder `data/` dan `logs/`. Backup sebelum update besar atau perubahan konfigurasi:

```bash
sudo docker compose stop
sudo tar -czf "hanna-backup-$(date +%F-%H%M).tar.gz" data logs .env
sudo docker compose start
```

Untuk restore, hentikan container terlebih dahulu, ekstrak backup ke folder project, lalu jalankan kembali:

```bash
sudo docker compose down
sudo tar -xzf hanna-backup-YYYY-MM-DD-HHMM.tar.gz
sudo docker compose up -d
```

Jangan menyimpan backup `.env` atau `data/hanna.db` di repository publik. Simpan backup di lokasi terenkripsi dengan permission terbatas, misalnya `chmod 600` untuk file secret.

## Keamanan dan batasan penting

- `.env`, database, session Pyrogram, WAL/SHM SQLite, cache, dan log dikecualikan dari Git serta Docker build context.
- Foto vision dibatasi 10 MiB secara default dan hanya diproses dari chat privat.
- Pesan error internal/provider tidak dikirim mentah ke pengguna; detailnya hanya ada di log server.
- Semua command admin menggunakan `ADMIN_ID`; jangan mengosongkannya.
- Bot ini ditujukan untuk chat privat. Handler image dan vision tidak memproses grup.
- API key provider tersimpan plaintext di SQLite agar fitur pergantian provider dari Telegram dapat bekerja. Lindungi volume `data/`, akses SSH, dan backup.
- Jangan mengekspos `logs/` melalui web server publik.
- Gunakan firewall VPS dan nonaktifkan login SSH berbasis password jika sudah memiliki akses key.
- Rotasikan/revoke token BotFather dan API key bila pernah tampil di chat, log, screenshot, atau backup tidak aman.

## Troubleshooting

### Container langsung restart

```bash
docker compose logs --tail=200 hanna
```

Biasanya penyebabnya adalah `BOT_TOKEN`, `API_ID`, `API_HASH`, atau `ADMIN_ID` belum diisi/formatnya salah. Pastikan `.env` berada di direktori yang sama dengan `docker-compose.yml`.

### `API Key ... belum diatur`

Isi `TOP_TOOLS_API_KEY` lalu rebuild/restart, atau masuk sebagai admin dan gunakan `/setkey <API_KEY>`. Pastikan `BASE_URL` sesuai API provider dan berakhir pada path yang benar, biasanya `/v1`.

### API error 401/403

Periksa provider aktif, key, base URL, dan apakah model tersebut tersedia untuk akun provider. Jangan menaruh key di source code. Setelah rotasi key, restart container atau set ulang lewat `/setkey`.

### Telegram tidak merespons

Periksa token BotFather, status container, waktu sistem VPS, koneksi outbound HTTPS, serta apakah token sedang dipakai oleh proses lain. Jangan menjalankan dua instance dengan bot token yang sama.

### Migrasi database setelah update

Pada start, aplikasi mendeteksi schema users lama dan memigrasikannya ke primary key gabungan `(user_id, bot_name)` untuk dukungan multi-bot. Tetap backup `data/hanna.db` sebelum update. Jika migrasi gagal, hentikan container dan pulihkan backup.

## Update UX dan kemampuan AI

Menu `/start` sekarang menampilkan nama lengkap Telegram dengan fallback yang rapi, sapaan berdasarkan waktu Asia/Jakarta (WIB), waktu dalam format monospace, serta quote harian. Teks lama yang tidak relevan dan angka saldo lokal dari halaman sambutan sudah dihapus. Tombol inline juga diringkas dan diterjemahkan agar fitur Chat AI, Pilih Model, Baca File, Vision, Balance, Bantuan, dan Pengaturan API lebih mudah ditemukan.

Bot dapat membaca file privat berformat TXT, MD, CSV, JSON, LOG, dan PDF. Ukuran file dibatasi 5 MB dan hasil ekstraksi dibatasi 20.000 karakter sebelum dikirim ke model. Isi file diperlakukan sebagai data untuk dianalisis, bukan sebagai instruksi sistem. File sementara dihapus setelah diproses.

Untuk mengaktifkan fitur ini setelah update, rebuild container agar dependency `pypdf` terpasang. Setelah bot aktif, tekan tombol `Baca File` atau langsung kirim file privat ke bot. Tambahkan caption berisi tugas, misalnya `Ringkas dalam 5 poin`. Untuk pengiriman dokumen keluar, gunakan `/export`; Hanna akan mengirim riwayat chat pengguna sebagai file TXT. Fitur ini tidak membutuhkan folder publik atau URL download.

Halaman Balance memisahkan `Provider Balance` dari `Local Estimasi`. Dokumentasi Top Tools AI menyediakan endpoint chat/image dan batas penggunaan, tetapi tidak mendokumentasikan endpoint publik khusus untuk saldo akun. Karena itu bot tidak akan mengklaim tracker SQLite sebagai saldo provider. Tombol `Refresh Balance` tetap mencoba endpoint yang tersedia; jika tidak ada respons resmi, gunakan dashboard Top Tools untuk saldo aktual.

Chat teks sekarang meminta mode SSE streaming. Hanna mengedit pesan Telegram secara berkala, bukan untuk setiap token, agar respons mulai terlihat lebih cepat tanpa memicu FloodWait. Jika provider tidak mendukung streaming atau gagal sebelum token pertama, bot otomatis memakai mode non-streaming. Jika stream terputus setelah sebagian teks diterima, bot tidak mengulang request secara otomatis agar tidak berisiko menggandakan biaya.

Setiap request chat juga menerima timestamp server terbaru dalam zona `Asia/Jakarta (WIB)`. Pertanyaan tentang jam, tanggal, dan hari dapat dijawab berdasarkan timestamp tersebut. Ini bukan akses internet umum: pertanyaan real-time seperti berita, cuaca, harga, atau event tetap membutuhkan sumber data/tool khusus dan tidak boleh dianggap live hanya karena fitur streaming aktif.

## Audit yang sudah dilakukan

- Validasi sintaks seluruh modul Python.
- Pemeriksaan dependency langsung terhadap `requirements.txt`.
- Fail-fast untuk environment wajib dan fail-closed untuk akses admin.
- Perbaikan schema SQLite multi-bot serta migrasi database lama.
- Perlindungan Docker context dengan `.dockerignore`.
- Pembatasan ukuran foto dan prompt.
- Filter private chat untuk image/vision.
- Pengurangan kebocoran error provider ke pengguna.
- Validasi model callback sebelum disimpan.
- Cleanup client Telegram saat startup/shutdown tidak sempurna.
- Pengujian handler baca file dengan allowlist format dan batas ukuran.
- Penyelarasan menu, sambutan WIB, format HTML, dan callback inline.

## Lisensi

Belum ditentukan. Tambahkan file `LICENSE` jika repository ini akan dibagikan atau digunakan oleh pihak lain.
