#!/usr/bin/env bash
# Quick tunnel + Telegram notify. Dijalankan pm2, auto-restart kalau mati/reboot.
set -uo pipefail

cd "$(dirname "$0")"

LOG=/tmp/cloudflared-quick.log
CF="$HOME/.local/bin/cloudflared"

# Telegram creds dari .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
if [ -f .env ]; then set -a; . ./.env; set +a; fi

notify() {
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "[notify skipped] $1"
    return
  fi
  curl -s -m 15 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" -d disable_web_page_preview=true --data-urlencode text="$1" >/dev/null
  echo "[notified] $1"
}

rm -f "$LOG"
"$CF" tunnel --url http://localhost:8000 --no-autoupdate --logfile "$LOG" --loglevel info &
CF_PID=$!

# tunggu URL muncul di log
URL=""
for _ in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 2
done

if [ -z "$URL" ]; then
  notify "❌ Tunnel gagal start. Cek log: $LOG"
  wait $CF_PID
  exit 1
fi

# tunggu sampai benar-benar bisa diakses (bukan cuma URL keluar)
code=""
for _ in $(seq 1 45); do
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$URL/")
  [ "$code" = "200" ] && break
  sleep 3
done

echo "$URL" > "$(dirname "$0")/.tunnel-url"

if [ "$code" = "200" ]; then
  notify "✅ YT Downloader online: $URL"
else
  notify "⚠️ Tunnel up tapi belum reachable (HTTP $code): $URL"
fi

wait $CF_PID
