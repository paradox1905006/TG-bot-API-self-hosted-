# Self-hosted Telegram Bot API server, ready for Render.
#
# Base image: prebuilt telegram-bot-api binary (tdlib/telegram-bot-api),
# maintained by bots-house. No source compile needed => fast Render builds.
FROM ghcr.io/bots-house/docker-telegram-bot-api:latest

# python3 runs fileserver.py -- the public entrypoint that proxies normal
# Bot API calls to telegram-bot-api internally and serves /localfile/
# requests directly off disk (see fileserver.py for why that's needed).
RUN apk add --no-cache python3

# Working directory where the server caches/serves files.
# NOTE: Render's free web services have an EPHEMERAL filesystem -- this
# directory is wiped on every restart/deploy. That's fine here: every
# download re-triggers a fresh getFile from Telegram if the local cache
# is gone, rather than depending on it still being there.
WORKDIR /data

# fileserver.py is what Render's proxy actually reaches (see start.sh) --
# telegram-bot-api itself runs on an internal-only port.
EXPOSE 8081

COPY start.sh /start.sh
COPY fileserver.py /fileserver.py

ENTRYPOINT ["/bin/sh", "/start.sh"]
