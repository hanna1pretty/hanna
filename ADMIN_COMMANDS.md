# Ringkasan Command Admin Hanna AI

Semua command pada dokumen ini hanya dapat digunakan oleh Telegram ID yang tercantum di `ADMIN_ID`. Jangan mengirim API key ke grup atau channel. Gunakan hanya di chat pribadi dengan bot.

## Diagnostik dan monitoring

| Command | Fungsi |
|---|---|
| `/ping` | Mengukur latency Telegram API, latency database, CPU, memory, disk, uptime, ukuran database, provider aktif, dan jumlah user premium aktif. |
| `/status` | Alias `/ping`. |
| `/adminhelp` | Menampilkan ringkasan command admin di Telegram. |
| `/admin_help` | Alias `/adminhelp`. |

`/ping` mengukur resource pada machine/container tempat bot berjalan. Angka Telegram API adalah waktu request `getMe`, bukan waktu respons AI provider.

## Premium dan user berlangganan

| Command | Contoh | Fungsi |
|---|---|---|
| `/premium` | `/premium` | Menampilkan paket premium dan status premium akun yang menjalankan command. |
| `/grantpremium` | `/grantpremium 123456789 30` | Mengaktifkan atau menambah masa premium user selama 30 hari setelah pembayaran diverifikasi manual. |
| `/premiumusers` | `/premiumusers` | Menampilkan user premium yang masih aktif dan waktu berakhir dalam UTC. |
| `/revokepremium` | `/revokepremium 123456789` | Mencabut akses premium user. |

Paket awal yang ditampilkan bot:

- Rp5.000 untuk 7 hari.
- Rp15.000 untuk 30 hari.
- Rp35.000 untuk 90 hari.

Harga tersebut hanya konfigurasi awal. Pembayaran belum otomatis dan belum terhubung ke Stripe. Admin wajib memverifikasi pembayaran sebelum menjalankan `/grantpremium`.

## Provider dan saldo

| Command | Contoh | Fungsi |
|---|---|---|
| `/api` | `/api` | Membuka pengaturan provider, mode akses, dan provider aktif. |
| `/apikey` | `/apikey` | Alias `/api`. |
| `/balance` | `/balance` | Menampilkan saldo provider live jika endpoint provider mendukung, pemakaian lokal, model aktif, dan token. Admin-only. |
| `/saldo` | `/saldo` | Alias `/balance`. |
| `/limits` | `/limits` | Alias `/balance`. |
| `/setkey` | `/setkey sk-...` | Mengganti API key provider aktif. Pesan akan dihapus jika Telegram mengizinkan. Jangan dipakai di grup. |
| `/seturl` | `/seturl https://provider.example/v1` | Mengganti base URL provider aktif. Gunakan HTTPS dan URL resmi provider. |
| `/setprovider` | `/setprovider nama https://... KEY` | Menyimpan provider baru sekaligus mengaktifkannya. Jangan kirim command ini di chat publik. |

## Model dan tracker lokal

| Command | Contoh | Fungsi |
|---|---|---|
| `/addmodel` | `/addmodel id | Pay as you go | Nama | 1.0 | 5.0` | Menambahkan model custom dengan harga input/output per 1 juta token. |
| `/delmodel` | `/delmodel model-id` | Menghapus model custom. Pastikan tidak sedang digunakan user. |
| `/setbalance` | `/setbalance 220` | Mengatur ulang acuan credit tracker lokal dan menghapus usage log. Ini bukan pengubah saldo provider. Gunakan hati-hati. |

## Akses bot

Mode akses diubah melalui menu `/api`:

- **Admin saja**: hanya admin dapat menggunakan bot.
- **Publik**: user biasa dapat menggunakan bot dengan limit harian.

Default limit publik:

- 40 request per user per hari.
- 100.000 token per user per hari.

User premium dan admin melewati limit internal tersebut. Mereka tetap tunduk pada saldo dan limit provider AI.

## Operasional melalui machine

Gunakan command berikut di terminal machine:

```bash
cd ~/hanna
docker compose ps
docker compose logs --tail=100 hanna
docker compose restart
```

Update kode:

```bash
cd ~/hanna
cp data/hanna.db data/hanna.db.backup-$(date +%F-%H%M)
git pull --ff-only
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 hanna
```

Backup lengkap:

```bash
cd ~/hanna
docker compose stop
tar -czf "hanna-backup-$(date +%F-%H%M).tar.gz" data logs .env
docker compose start
```

Jangan menghapus `data/hanna.db`, folder `data/`, atau file `.env` tanpa backup. Database berisi riwayat, model user, status premium, dan konfigurasi provider.
