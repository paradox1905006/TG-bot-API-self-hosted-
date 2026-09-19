#!/bin/sh
set -e

# Render injects PORT automatically at runtime -- something MUST listen on
# it publicly. That something is fileserver.py (see below), not
# telegram-bot-api directly, so it can also serve /localfile/ requests.
PORT="${PORT:-8081}"
# telegram-bot-api itself listens only on localhost, on this internal port.
TBA_PORT=8081

if [ -z "$TELEGRAM_API_ID" ] || [ -z "$TELEGRAM_API_HASH" ]; then
  echo "!!! TELEGRAM_API_ID / TELEGRAM_API_HASH env vars are not set."
  echo "!!! Get them from https://my.telegram.org -> API development tools"
  exit 1
fi

if [ -z "$LOCAL_FILE_SECRET" ]; then
  echo "!!! LOCAL_FILE_SECRET is not set."
  echo "!!! Pick any long random string and set the SAME value here and as"
  echo "!!! the LOCAL_FILE_SECRET secret on your Cloudflare Worker -- it's"
  echo "!!! what authorizes /localfile/ requests for large-file downloads."
  exit 1
fi

echo "Starting telegram-bot-api on internal port ${TBA_PORT} ..."

# telegram-bot-api reads TELEGRAM_API_ID / TELEGRAM_API_HASH from the
# environment automatically (see --help), so we don't pass --api-id /
# --api-hash explicitly here. Render only forwards external traffic to
# $PORT (which fileserver.py owns below), so this internal port is never
# reachable from outside the container regardless of which interface it
# binds on.
telegram-bot-api \
  --local \
  --dir=/data \
  --http-port="${TBA_PORT}" \
  --verbosity=2 &

# telegram-bot-api never deletes anything it downloads into /data --
# every large file streamed through /localfile/ stays on disk forever,
# which will eventually fill Render's disk and start failing new
# downloads. Sweep files older than 24h once an hour, in the background,
# for as long as this container runs (Render's ephemeral disk also wipes
# on every redeploy/restart regardless, but that can be hours or days
# away on a service that isn't redeployed often).
(
  while true; do
    sleep 3600
    find /data -type f -mmin +1440 -print -delete 2>/dev/null | while read -r f; do
      echo "[cleanup] removed old cached file: $f"
    done
  done
) &

echo "Starting public entrypoint (proxy + /localfile/) on port ${PORT} ..."
export TBA_PORT
exec python3 /fileserver.py "${PORT}"
