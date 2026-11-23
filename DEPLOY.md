# Putting Clip Cut AI on a server

Clip Cut AI runs as three containers on one Linux server: the app, PostgreSQL, and Caddy (which handles HTTPS).

## What you need

- A Linux server with Docker. Clipping is CPU work: plan on **8+ CPU cores, 16 GB RAM and 200+ GB of disk** if
  several people will use it. Transcription runs at roughly 10x real time per video on 4 cores.
- A domain name pointing at the server (an `A` record).
- An AI key (see "Choose your AI" in the README). Optional: a Google "Web application" OAuth client, and an SMTP
  service for emails.

## Steps

1. Copy this folder to the server (or `git clone` it there).
2. `cp .env.example .env` and fill it in: the AI lines, `CLIPCUT_DOMAIN`, `POSTGRES_PASSWORD`, and
   `COMPOSE_PROFILES=own-https` if the server is Clip Cut AI's alone. Put key files, if you use files, in `./secrets/`.
3. `docker compose up -d --build`
   The first start downloads the speech model (about 480 MB) and creates the database tables.
4. Open `https://your-domain` and sign up. With Docker, accounts are on (`CLIPCUT_ACCOUNTS=1`), so everyone signs in.
   Every new account is a normal user.
5. Make yourself an admin, on the server: `docker compose exec app python -m studio.admin grant you@example.com`
   The admin dashboard is then at `https://your-domain/admin`. It answers "not found" for everyone who is not an
   admin, and no page or web request can make someone an admin: only that command can.
6. Sign in as that admin, open **Settings, AI**, and add your AI key there (or put it in `.env`).

## Connecting YouTube, Instagram, Facebook and TikTok

People connect their accounts with one click in **Settings, Connected apps**: they press Connect, sign in on the
platform's own page, and come back. For that, the server needs one app registered with each platform. An admin can
do it right there: press **Set up** on a platform, follow the steps shown, and paste the app's id and secret (or put
them in `.env`, see `.env.example`). The redirect address to register is shown in the panel, with a Copy button.

- **YouTube** (Google Cloud): an OAuth client of type Web application, with YouTube Data API v3 turned on. Until
  Google verifies the app, people see a warning screen and uploads stay private.
- **Instagram** (Meta for Developers): a Business app with Instagram (API setup with Instagram login). Works with
  Creator and Business accounts. Until Meta reviews the app, only accounts added as testers can connect. Instagram
  fetches each clip from a one-hour signed link on your site, so the site needs a public https address.
- **Facebook and Instagram (Meta)** (Meta for Developers): a Business app with **Facebook Login for Business**. Under
  Configurations, make one (User access token) with `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
  `business_management`, `instagram_basic` and `instagram_content_publish` (and, for replies to comments,
  `pages_manage_engagement`, `pages_read_user_content` and `instagram_manage_comments`), then paste the App ID, App secret and
  the **Configuration ID** in the panel. One Connect adds every Facebook Page the person picks, and the Instagram
  professional account linked to each Page. Clips are posted to the Page as Reels (the file is sent straight to
  Facebook) and to Instagram as Reels. Without a Configuration ID, Clip Cut AI asks for those permissions itself.
- **TikTok** (TikTok for Developers): an app with Login Kit and the Content Posting API (Direct Post), scopes
  `user.info.basic` and `video.publish`. Until TikTok audits the app, clips are posted as private (Clip Cut AI does
  this by itself and says so on the account).

Instagram, Facebook and TikTok only accept https redirect addresses.

## Scheduling posts

- **A picked time:** in a clip, tick the accounts and press **Schedule**, then choose the date and time.
- **Fixed times every day:** in a creator's Setup, fill in *Post at fixed times every day* (for example
  `10:00, 14:00, 19:30`). Queued and auto-posted clips then go out at the next free time on that list, keeping to
  the daily cap. Left empty, clips are spread out by the minutes between posts, as before.
- **Calendar:** the Calendar page shows every post of the month, planned and done. Pick a day to change a post's
  time, cancel it, or retry one that failed.
- **Captions:** the AI writes captions made to stop the scroll: a hook, what happens, and a question for the
  comments, with a few fitting emojis. Set a creator's *Caption style* to Clean to post the same text without
  emojis, and add a *Line asking viewers to act* (a follow line) to put under every caption.

Clip Cut AI posts from the computer or server it runs on, so it must be running at the scheduled time.

## Replies to comments

The **Comments** page lets the AI answer comments on the clips you posted, on YouTube, Instagram and Facebook.
Choose *Write replies, I approve each one* (the replies wait for you to read, change and send) or *Reply
automatically* (sent straight away, up to the daily limit you set). New comments are read every 10 minutes on posts
from the last 3 days. Spam, abuse, links and requests to take a clip down never get a reply. It needs an AI key, and
accounts connected with the comment permissions: YouTube (`youtube.force-ssl`), Instagram Login
(`instagram_business_manage_comments`) or Facebook Login (the three above). Accounts connected before this was added
must be connected again.

## Backups and your login

- **Settings, Storage, Backups:** a backup of logins, creators, connected accounts, the post queue and the clip list is
  made every day (no video files); the last 14 are kept. To put one back, close the app and run
  `python -m studio.backup restore <file>`.
- **Settings, Login** (while sign-in is off): save an email and password for the account that holds everything. After
  switching sign-in on (`CLIPCUT_ACCOUNTS=1`), signing in with them opens that same account, so nothing goes missing.

## Cloud mode: keep it running while your computer is off

On a fresh Ubuntu server (2+ cores, 4+ GB RAM, 40+ GB disk is enough for one page) with a domain pointing at it,
run `bash deploy/vps-setup.sh` as root from a copy of Clip Cut AI (or download that one file and run it). It installs
Docker, asks for your domain and email, writes `.env` with sign-in on and HTTPS, and starts everything. To bring what
you made on your computer: Settings, Storage, Backups, Download there; then on the server follow the steps the script
prints (`python -m studio.backup restore -y <file> --to you@example.com` hands everything to your new account).
Register the new https callback addresses with YouTube, Meta and TikTok afterwards.

## The AI Manager

Switch it on in **Manager**. Every hour it retries posts that failed for a passing reason (up to three times), warns
you once a day about accounts that need connecting again, posts good clips nobody looked at for two hours (at or above
the creator's minimum score, to that creator's accounts), reminds you when posting is paused, and sends a daily report.
You can talk to it in the Manager page or by writing to your Telegram bot ("aaj kitne views aaye?", "roz 5 post kar
do"). It works only through a fixed set of tools: it cannot delete anything, disconnect accounts or change logins.

## The phone app

Open Clip Cut AI in Chrome on Android (or Safari on iPhone: Share, Add to Home Screen) and choose **Install the app**:
it gets its own icon and opens full screen. **Review** shows new clips one at a time: swipe right to post, left to
skip.

## Using Clip Cut AI from your phone

The pages work on a phone. To reach Clip Cut AI from one, it needs an https address (a domain, or a tunnel such as
Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8765`), with `CLIPCUT_PUBLIC_URL` set to it.
**Before you open it to the internet, turn sign-in on** with `CLIPCUT_ACCOUNTS=1`: everyone then signs in with
their email and a password (or Google), and you make your own account an admin with
`python -m studio.admin grant you@example.com`. Without sign-in, anyone with the address could use your Clip Cut AI.

## Google setup (sign-in and YouTube)

In Google Cloud, create an OAuth client of type **Web application** with these redirect URIs:

- `https://your-domain/auth/google/callback`
- `https://your-domain/oauth/youtube/callback`

Enable **YouTube Data API v3** in the same project. Posting publicly to YouTube needs Google's API audit;
until then uploads from the API stay private.

## Email

Set the `CLIPCUT_SMTP_*` lines and `CLIPCUT_MAIL_FROM` to send password-reset and confirmation emails through any
SMTP service. On a public site also set `CLIPCUT_VERIFY_EMAIL=1`, so people confirm their address before clipping.
Without SMTP on an HTTPS site, no reset emails can be sent.

## Good to know

- **Data**: everything lives in two Docker volumes, `pgdata` (accounts, AI usage) and `data` (videos, clips).
  Back both up. `docker compose exec db pg_dump -U clipcut clipcut > backup.sql` dumps the database.
- **Capacity**: `CLIPCUT_JOB_WORKERS` is how many videos are processed at once; `CLIPCUT_MAX_LIVE` is how many live
  streams are recorded at once. Raise them only as far as the CPU allows.
- **One server only**: jobs and live recordings run inside the app process. Do not start a second copy of the app
  against the same data.
- **YouTube downloads from data centres** are sometimes refused by YouTube ("confirm you're not a bot"). If links
  fail on the server but work at home, the server's address is the cause. Clip Cut AI then pauses YouTube links for a
  few minutes and says so; uploads and Twitch or Kick links keep working.
- **Updates**: `git pull && docker compose up -d --build`. A restart pauses videos in progress (they pick up
  where they stopped) and live recordings (clips already found are finished from the saved stream).
- **Open sign-up**: anyone who can reach the site can make an account and use your AI key. On a public address,
  keep the limits in `.env` sensible, or put the site behind your own access control.

## A server that already runs other sites

Leave `COMPOSE_PROFILES=own-https` out of `.env`. Clip Cut AI then listens only on `127.0.0.1:8765` and the web
server that is already there forwards the domain to it: see `deploy/nginx-clipcut.conf`, or
`deploy/docker-compose.traefik.yml` for Traefik.

## Cloudflare CDN in front

With the record proxied (orange cloud):

- Set `CLIPCUT_CLIENT_IP_HEADER=CF-Connecting-IP` in `.env`, so rate limits see each visitor, not Cloudflare. The
  header is only believed for connections that really come from Cloudflare's address ranges.
- Images, videos and scripts under `/brand/` and `/assets/` are cached by Cloudflare automatically. Signed-in
  pages, clips and the API send `private` or `no-store` and are never cached by Cloudflare.
- Use SSL/TLS mode Full (strict) with a Cloudflare origin certificate in `secrets/` and
  `CLIPCUT_CADDYFILE=Caddyfile.origin`.
- Cloudflare's standard plans refuse requests over 100 MB. Clip Cut AI sends big uploads in pieces
  (`CLIPCUT_UPLOAD_PART_MB`, 40 by default), so large files still work.

## Speech to text on a graphics card

Optional. A second machine with an NVIDIA card can do most of the transcription much faster:
`deploy/gpu/docker-compose.yml` runs it, and `CLIPCUT_ASR_URL` plus `CLIPCUT_ASR_TOKEN` on the main server point
at it. Keep its port closed to the internet. If it is unreachable, the main server carries on with its own
processor.
