#!/usr/bin/env bash
# Clip Cut AI on a cloud server, in one go, so it keeps working while your computer is off.
#
# On a fresh Ubuntu 22.04 or 24.04 server (2+ CPU cores, 4+ GB RAM, 40+ GB disk is enough for one page),
# with a domain (or subdomain) whose A record points at the server, run as root:
#
#   curl -fsSL <link to this file> -o setup.sh && bash setup.sh
#
# or, inside a copy of Clip Cut AI on the server:  bash deploy/vps-setup.sh
#
# It installs Docker, asks for your domain and email, writes .env (sign-in on, HTTPS by Caddy), and starts
# everything. Run it again any time: it keeps your .env and data.
set -euo pipefail

REPO="${CLIPCUT_REPO:-}"   # your GitHub repository, e.g. https://github.com/you/clip-cut-ai.git (or run this inside the folder)
DIR="${CLIPCUT_DIR:-/opt/clipcut}"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then echo "Run this as root (or with sudo)."; exit 1; fi

say "Installing Docker (if it isn't already)"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
fi
command -v git >/dev/null 2>&1 || { apt-get update -y && apt-get install -y git; }

say "Getting Clip Cut AI into $DIR"
if [ -f "./docker-compose.yml" ] && [ -d "./studio" ]; then
  DIR="$(pwd)"
elif [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || true
else
  if [ -z "$REPO" ]; then
    echo "Run this script inside the Clip Cut AI folder, or set CLIPCUT_REPO to your GitHub repository address."; exit 1
  fi
  git clone "$REPO" "$DIR"
fi
cd "$DIR"

if [ ! -f .env ]; then
  say "A few questions (this is asked once)"
  read -rp "Your domain for Clip Cut AI (like clips.example.com): " DOMAIN
  read -rp "Your email (for the HTTPS certificate and your admin account): " EMAIL
  PG="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 28)"
  cp .env.example .env
  {
    echo ""
    echo "# written by deploy/vps-setup.sh"
    echo "CLIPCUT_DOMAIN=$DOMAIN"
    echo "POSTGRES_PASSWORD=$PG"
    echo "COMPOSE_PROFILES=own-https"
    echo "CLIPCUT_ACCOUNTS=1"
    echo "CLIPCUT_ADMIN_EMAIL=$EMAIL"
  } >> .env
  chmod 600 .env
else
  say "Keeping your existing .env"
  EMAIL="$(grep -E '^CLIPCUT_ADMIN_EMAIL=' .env | tail -1 | cut -d= -f2- || true)"
  DOMAIN="$(grep -E '^CLIPCUT_DOMAIN=' .env | tail -1 | cut -d= -f2- || true)"
fi
mkdir -p secrets

say "Starting (the first time takes a few minutes: it builds the app and downloads the speech model)"
docker compose up -d --build

say "Opening the firewall for the website (if ufw is on)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q active; then ufw allow 80/tcp && ufw allow 443/tcp; fi

cat <<MSG

  Clip Cut AI is starting at:  https://${DOMAIN:-your-domain}

  1. Open it, and sign up with ${EMAIL:-your email}.
  2. Make that account the admin, here on the server:
       cd $DIR && docker compose exec app python -m studio.admin grant ${EMAIL:-you@example.com}
  3. Moving from your computer? In Clip Cut AI on your computer: Settings, Storage, Backups, Download.
     Copy the file here and run:
       cd $DIR && docker compose cp <backup.zip> app:/data/restore.zip && docker compose stop app &&
       docker compose run --rm app python -m studio.backup restore -y /data/restore.zip --to ${EMAIL:-you@example.com} &&
       docker compose up -d
     (Videos are not in backups; your settings, creators, logins, connected accounts and posts are.)
  4. Register https://${DOMAIN:-your-domain}/oauth/.../callback addresses with YouTube, Meta and TikTok again
     (Settings, Connected apps shows each one), because the address changed.

MSG
