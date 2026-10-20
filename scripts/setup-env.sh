#!/bin/sh
# Creates .env (git-ignored, readable only by you) with a random local API token.
# You then paste your Telegram bot token and chat ID into it yourself.
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  echo ".env already exists; leaving it unchanged."
  exit 0
fi
umask 077
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
cat > .env <<ENV
# Local secrets for the Reel Factory. This file is git-ignored; never share it.

# Generated automatically: n8n uses it to talk to the local Python API. Leave as is.
REELFACTORY_API_TOKEN=$TOKEN
REELFACTORY_API_URL=http://127.0.0.1:8765

# From @BotFather in Telegram ("Use this token to access the HTTP API: ...")
TELEGRAM_BOT_TOKEN=
# Your personal chat ID: the bot only obeys messages from this chat.
TELEGRAM_CHAT_ID=
TELEGRAM_API_BASE=https://api.telegram.org
ENV
chmod 600 .env
echo "Created .env. Now open it and fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
