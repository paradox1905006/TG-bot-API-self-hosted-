#!/bin/sh
set -e

# Render injects PORT automatically at runtime -- the server MUST listen on it.
# Locally (docker run) it falls back to 8081.
PORT="${PORT:-8081}"

if [ -z "$TELEGRAM_API_ID" ] || [ -z "$TELEGRAM_API_HASH" ]; then
  echo "!!! TELEGRAM_API_ID / TELEGRAM_API_HASH env vars are not set."
  echo "!!! Get them from https://my.telegram.org -> API development tools"
  exit 1
fi

echo "Starting telegram-bot-api on port ${PORT} ..."

# telegram-bot-api reads TELEGRAM_API_ID / TELEGRAM_API_HASH from the
# environment automatically (see --help), so we don't need to pass
# --api-id / --api-hash explicitly here.
exec telegram-bot-api \
  --local \
  --dir=/data \
  --http-port="${PORT}" \
  --verbosity=2
