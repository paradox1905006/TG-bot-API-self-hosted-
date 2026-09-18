# Self-hosted Telegram Bot API server, ready for Render.
#
# Base image: prebuilt telegram-bot-api binary (tdlib/telegram-bot-api),
# maintained by bots-house. No source compile needed => fast Render builds.
FROM ghcr.io/bots-house/docker-telegram-bot-api:latest

# Working directory where the server caches/serves files.
# NOTE: Render's free web services have an EPHEMERAL filesystem -- this
# directory is wiped on every restart/deploy. That's fine for occasional
# proxy use; if you need files to survive restarts, attach a Render Disk
# (paid feature) and mount it at /data instead.
WORKDIR /data

# Telegram Bot API server's default port. We don't rely on this directly --
# start.sh below rebinds it to Render's injected $PORT at container start.
EXPOSE 8081

COPY start.sh /start.sh

ENTRYPOINT ["/bin/sh", "/start.sh"]
