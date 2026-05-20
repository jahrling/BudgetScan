# BudgetScan — Operator Runbook

Day-2 operations for the self-hosted BudgetScan home server.

---

## 1. First-time setup (Ubuntu 24.04, RTX 5070 Ti)

### 1.1 Host packages

```bash
sudo apt update && sudo apt install -y \
  ca-certificates curl gnupg git build-essential
```

### 1.2 NVIDIA driver + CUDA

The RTX 5070 Ti is **Blackwell** silicon. It requires:
- NVIDIA driver ≥ 555
- CUDA 12.8+
- Ollama ≥ 0.6

```bash
# Driver
sudo ubuntu-drivers autoinstall
# CUDA toolkit (12.8+)
sudo apt install -y nvidia-cuda-toolkit
nvidia-smi   # verify driver + GPU
```

### 1.3 Docker + NVIDIA Container Toolkit

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Reboot or re-login.

# NVIDIA Container Toolkit (so containers can see the GPU)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 1.4 Clone & configure

```bash
git clone https://github.com/jahrling/BudgetScan /opt/finance
cd /opt/finance
cp .env.example .env
# Edit .env — set DROPBOX_ACCESS_TOKEN, SECRET_KEY, APP_ENV=production
```

Generate a session key:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Get a Dropbox token from https://www.dropbox.com/developers/apps (Scoped
Access app, generate access token, "Full Dropbox" or app folder).

### 1.5 Bring it up

```bash
docker compose --profile prod up -d
docker compose ps   # all containers healthy
```

Uncomment the `deploy.resources.devices` block in `docker-compose.yml` for
the `ollama` service to enable GPU passthrough.

### 1.6 Pull the OCR model

```bash
docker compose exec ollama ollama pull qwen2.5vl:7b
docker compose exec ollama ollama pull qwen2.5:7b
# Verify the vision model works on GPU:
docker compose exec ollama ollama run qwen2.5vl:7b "hello"
```

If `ollama run` errors with CUDA capability mismatch, check that the host
has CUDA 12.8+ and that you're on Ollama ≥ 0.6 (`docker pull ollama/ollama:latest`).

---

## 2. Trusting Caddy's root CA on iPhone

Caddy's `tls internal` mints certificates from a local CA. To open the PWA
on iPhone Safari without certificate warnings (and to get camera capture
working, which requires HTTPS):

1. On iPhone Safari, navigate to `http://<server-ip>:2019/pki/ca/local/certificate`.
2. Safari downloads a `.crt` profile. Tap "Allow".
3. Open **Settings → General → VPN & Device Management → Downloaded Profile**.
4. Tap "Install" twice and enter your passcode.
5. Open **Settings → General → About → Certificate Trust Settings**.
6. Flip the toggle for the Caddy Local CA to **Enabled**.
7. Browse to `https://<server-ip>/` — should be padlocked.

When zero-trust ingress replaces Caddy, this step goes away: identity is
asserted by the edge proxy and the LAN cert path is no longer relevant.

---

## 3. Cron jobs

Install on the host:

```cron
# Retry pending Dropbox uploads + log purge dry-run (every hour)
0 * * * *  cd /opt/finance && ./scripts/sync_pending.sh >> /var/log/finance-sync.log 2>&1

# Daily SQLite snapshot → Dropbox (02:00 local)
0 2 * * *  cd /opt/finance && ./scripts/backup_db.sh >> /var/log/finance-backup.log 2>&1
```

Both scripts shell into the backend container and run the Python entrypoints
under `finance.scripts.*`.

---

## 4. Ollama model swaps

Models live in the `ollama-models` named volume and survive container
restarts. To swap:

```bash
docker compose exec ollama ollama pull <newmodel>
docker compose exec ollama ollama rm <oldmodel>
# Update OLLAMA_VISION_MODEL / OLLAMA_TEXT_MODEL in .env, then:
docker compose restart backend
```

---

## 5. Restoring the DB from a Dropbox backup

```bash
# List recent backups
dropbox-cli ls /finance-backups/db

# Download the snapshot
dropbox-cli get /finance-backups/db/finance-<ts>.db.gz /tmp/

# Stop the app, swap the DB
docker compose stop backend
gunzip -c /tmp/finance-<ts>.db.gz > /tmp/finance.db
docker cp /tmp/finance.db $(docker compose ps -q backend):/app/data/finance.db
docker compose start backend
```

Verify with `GET /api/admin/stats` afterwards.

---

## 6. Manually re-syncing receipts

If Dropbox was offline for a while:

```bash
./scripts/sync_pending.sh
```

This is identical to the hourly cron. It walks every `ocr_status=done`
receipt where `dropbox_path IS NULL` and `file_path` still exists,
uploads, verifies, and deletes locally.

---

## 7. Manually purging old receipts (>36 months)

The hourly cron only logs what *would* be deleted. To actually purge:

```bash
docker compose exec backend python -c '
from finance.services.dropbox_sync import purge_old_receipts
import json
print(json.dumps(purge_old_receipts(months=36, confirm=True), indent=2))
'
```

Review the output. The retention window is configurable on the call.

---

## 8. Updating the app

```bash
cd /opt/finance
git pull
docker compose --profile prod build
docker compose --profile prod up -d
# Apply DB migrations if any:
docker compose exec backend alembic upgrade head
```

The named volumes (`db-data`, `receipts`, `ollama-models`) persist across
rebuilds.

---

## 9. Zero-trust ingress (future)

`tls internal` is LAN-only. When you swap in a zero-trust edge (Cloudflare
Tunnel, Tailscale Funnel, Pomerium, etc.):

1. Replace the `caddy` service with the edge proxy of your choice.
2. The app itself does **not** change — it already trusts forwarded
   identity headers via the existing session cookie.
3. Update `APP_ENV=production` (already required) to keep `Secure +
   SameSite=Strict` cookies + CSRF enforcement on.
4. Optionally tighten `OLLAMA_TIMEOUT_SECONDS` to 60s once the model is
   pre-warmed at boot.

---

## 10. Health & observability

- `GET /api/health` — liveness, no auth.
- `GET /api/admin/stats` — auth-gated. Returns receipt totals, OCR
  success rate, pending Dropbox sync count, DB size, last backup time.
- All container stdout is JSON-formatted; ship to your preferred log
  collector.

---

## 11. Smoke test

```bash
./scripts/smoke_test.sh
```

Exercises login → category → budget → receipt upload → OCR poll →
Dropbox verify → local delete check → QIF export → logout. Exit 0 on pass.
