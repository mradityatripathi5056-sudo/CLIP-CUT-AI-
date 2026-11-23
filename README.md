# Clip Cut AI

Developed by **Aditya** and **Anshik**. Open source under the MIT licence (see [LICENSE](LICENSE)).

Turn long videos and live streams into captioned vertical clips, ready to post. Free and open source: run it on
your own computer or server, with your own AI key.

Paste a YouTube, Twitch or Kick link (or upload a file) and Clip Cut AI finds the moments worth clipping, cuts them to
9:16, adds word-by-word captions and a hook, and can post them to your connected accounts. It can also record a
creator's live stream and clip the highlights while the stream is still running.

## What it does

- **Clips from any video.** Transcribes the audio, asks an AI which moments would hold a stranger's attention, and
  renders each one with captions in one of three styles.
- **Live clipping.** Records a stream into a rolling buffer and clips as it happens, using loudness, chat activity
  and the transcript.
- **Workspaces per creator.** Channels, clip settings, posting rules and an activity log for each creator you clip.
- **Posting.** Connect YouTube, Instagram, Facebook Pages and TikTok in one click, then queue or auto-post finished
  clips, with spacing, daily caps and fixed posting times (see
  [DEPLOY.md](DEPLOY.md#connecting-youtube-instagram-facebook-and-tiktok) for the one-time setup).
- **Scheduling and calendar.** Schedule a clip for an exact date and time, set a creator's daily posting times, and
  see every planned and finished post on a month calendar where you can move, cancel or retry them.
- **Autopilot.** New uploads from a creator's channels are clipped by themselves; effects (zoom on the big moment,
  instant replay, sound effects, emojis on captions, an AI voice intro); your logo and a creator credit on clips;
  Telegram buttons to post from your phone; AI replies to comments and keyword DMs; best posting hours from your
  views; a second title for slow Shorts; hits posted again; weekly compilations for YouTube; trending videos and
  hashtags; analytics with AI tips; campaign reports; a team workspace; backups; an installable phone app with
  swipe review; and one-command cloud setup (see [DEPLOY.md](DEPLOY.md)).
- **Captions that get comments.** The AI writes a hook, what happens and a question for the comments, with fitting
  emojis; switch a creator to a clean style without emojis, and add a follow line to every post.
- **No sign-in on your own computer.** It opens straight into the dashboard. On a shared server, switch accounts on
  (`CLIPCUT_ACCOUNTS=1`) for email or Google sign-in and an admin dashboard.
- **Your own AI.** Gemini, OpenAI, Grok, Groq, OpenRouter, Claude, a local model through Ollama, or anything that
  speaks the OpenAI chat format. No key at all also works: clips are then picked by loudness.

### YouTube growth strategy

Titles, descriptions, tags and hashtags follow the SEO and packaging rules of
[The YouTube agent skill](https://github.com/Jakeschincariol/youtube-agent-skill) by Jake Schincariol (MIT; its
21 hook formulas are in `studio/ytskill/` with their licence). Also from it: viral outliers ranked by each
channel's own median, posting at the channel's best hours (or instantly), comment piles with a pin suggestion,
and a channel check that ends in ONE fix. See `studio/ytstrategy.py`.

### Also in Clip Cut AI

- **Add a YouTube channel in one step** (Home): paste the channel, pick India or Worldwide. The app turns on new
  uploads, ticks every connected account and sets how many Reels a day (2 to 5, from how much the channel uploads)
  and at what times (India: 12:30, 15:30, 18:30, 21:00, 22:30; worldwide: US and Europe evenings, in India time).
- **India = Hinglish, everyone else = English**: each creator has an audience; a page can also be set to always
  post English (the Hinglish text is translated once per clip).
- **Email login that can't be lost**: Settings, Login. Gmail with an app password sends a code to check your email
  before your login is saved, optional two-step sign-in codes, and the weekly backup by email.
- **Background music** from your own library, a **reaction sticker** on the big moment, **song check** (AudD) that
  holds clips with copyrighted songs, and the **best clip length** learned from your views.
- **Permission** per streamer with a ready "can I clip you?" message (Hinglish or English).
- **Instagram Collab** posts, **Threads, Bluesky and Discord** posting.
- **Money** page: YouTube earnings and the road to monetization (YPP rules, including the February 2027 change),
  brand deals, counted affiliate links and a **link-in-bio page** (/c/your-name).
- **Phone alerts** (web push, no Telegram needed) and **team roles** (manager or editor).

## Quick start

You need Python 3.10 or newer and `ffmpeg`. On Windows: `winget install Gyan.FFmpeg`. On a Mac: `brew install ffmpeg`.
On Linux: `sudo apt install ffmpeg`. Clip Cut AI finds it by itself and tells you in the dashboard if it is missing.

Put Clip Cut AI in a short folder that stays put: `C:\clipcut` on Windows, `~/clipcut` on a Mac or Linux. Not inside a
temporary folder or an AI assistant's workspace: those get cleaned up, and on Windows a folder that deep stops the
speech model from loading (Windows can't open files whose full path is over 260 characters). If an AI assistant
installs it for you, it should ask you where to put it first ([AGENTS.md](AGENTS.md) tells it to).

On Windows:

```bash
git clone <this repository> C:\clipcut
```

```bash
cd C:\clipcut
```

On a Mac or Linux:

```bash
git clone <this repository> ~/clipcut
```

```bash
cd ~/clipcut
```

```bash
pip install -r requirements.txt
```

Start the server:

```bash
python -m studio.server
```

The first start downloads the speech model by itself (about 480 MB, once).

Open http://127.0.0.1:8765. There is no sign-in: it opens straight into the dashboard. Go to **Settings, AI**, choose
your AI service, paste your key and press **Save and test** (see [Choose your AI](#choose-your-ai)).

## Choose your AI

Clip Cut AI needs a chat model that can return JSON. The easy way is in the dashboard: **Settings, AI**. Pick the
service, paste your key, press **Find models** to choose from the service's own list, then **Save and test**. The
key is kept in the data folder on your machine and is never shown again.

If you prefer a file (or run a server), the same three things can go in `.env`. What is saved in the dashboard wins:

```ini
CLIPCUT_AI_PROVIDER=gemini
CLIPCUT_AI_MODELS=gemini-2.5-flash
CLIPCUT_AI_KEY=your-key-here
```

| `CLIPCUT_AI_PROVIDER` | Service | Where to get a key |
|---|---|---|
| `gemini` | Google Gemini | https://aistudio.google.com/apikey |
| `openai` | OpenAI | https://platform.openai.com/api-keys |
| `xai` | Grok (xAI) | https://console.x.ai |
| `groq` | Groq | https://console.groq.com/keys |
| `openrouter` | OpenRouter (many models, one key) | https://openrouter.ai/keys |
| `anthropic` | Claude | https://console.anthropic.com |
| `ollama` | A model on your own machine, no key | https://ollama.com |
| `custom` | Any OpenAI-compatible address: also set `CLIPCUT_AI_BASE_URL` | |

- `CLIPCUT_AI_MODELS` is the model id exactly as the service names it. Model names change often, so check the
  service's current list. Several ids separated by commas are tried in order, which gives you a fallback.
- A fast, inexpensive model is the right choice. A one-hour video is read in about four requests.
- You pay the AI service directly for what you use. The **AI usage** page in the app shows how many requests and
  tokens each video took.
- Speech to text does not use the AI service. It runs on your own machine, so audio never leaves it.

### Videos in Arabic

Clip Cut AI hears English by default. To clip videos in Arabic, add the Arabic speech model once in
**Settings → Speech models** (about 107 MB), or choose **Arabic** under Options when adding a video and Clip Cut AI
offers to download it. Set a creator's language on their Setup page so their live recordings use it too.
It understands Modern Standard Arabic and everyday dialects, and the AI turns English words said in between
back into English. Captions on the clips are in English.

## Settings

Everything is set through environment variables, normally in a `.env` file next to this README.
[`.env.example`](.env.example) lists every setting with a short explanation. The ones that matter first:

| Setting | What it is for |
|---|---|
| `CLIPCUT_AI_PROVIDER`, `CLIPCUT_AI_MODELS`, `CLIPCUT_AI_KEY` | The AI that picks clips and writes titles (or set it in the dashboard) |
| `CLIPCUT_ACCOUNTS` | `1` makes everyone sign in. Use it on any server other people can reach |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Optional: Sign in with Google, and connecting YouTube |
| `CLIPCUT_SMTP_*`, `CLIPCUT_MAIL_FROM` | Optional: confirmation and password emails |
| `CLIPCUT_DATA` | Where videos, clips and the database are kept (default `./data`) |

`.env`, the `secrets/` folder and all user data are ignored by git. Keep keys there, never in the code.

## Admins

This only matters with accounts switched on (`CLIPCUT_ACCOUNTS=1`); without them you are the owner and can do
everything. An account is an admin only when the database says so. No email address is special in the code and no web request
can change a role. Do it on the machine that runs Clip Cut AI:

```bash
python -m studio.admin grant you@example.com
```

`revoke` and `list` work the same way. The admin dashboard is at `/admin` and answers "not found" to everyone else.

## How it is built

| Part | What it is |
|---|---|
| `studio/` | The server: FastAPI, the clip pipeline, live recording, accounts |
| `studio/ai.py` | The only file that talks to an AI service. Add a provider here |
| `web/` | The pages: landing, sign-in, the app, the admin dashboard (plain HTML, CSS and JavaScript, no build step) |
| `tests/` | Tests that run against a throwaway copy of the app |
| `deploy/`, `Dockerfile`, `docker-compose.yml` | One-server deployment with PostgreSQL and automatic HTTPS |

Video work is done with `ffmpeg` and `yt-dlp`. Speech is transcribed with `sherpa-onnx` and NVIDIA's Parakeet
model (English) and FastConformer Arabic model, both released by NVIDIA under the Creative Commons Attribution 4.0
licence (CC-BY-4.0). The Arabic model was converted for sherpa-onnx with `tools/export_arabic_model.py`.
Data is kept per user: accounts in the database (SQLite on your own computer, PostgreSQL on a server), videos and
clips in each user's own folder. [AGENTS.md](AGENTS.md) is a short map of the code for contributors and AI coding
assistants.

## Where your videos and clips are kept

Everything Clip Cut AI keeps is in one folder: videos, clips, recordings, creators, settings and the speech model. By
default it is the `data` folder inside Clip Cut AI. **Settings, Storage** shows the folder and how much room its drive
has, opens it in one click, and lets you move it to another drive: choose the new folder, and Clip Cut AI moves
everything there the next time it starts. If the drive is nearly full, Clip Cut AI says so and stops taking new videos
until there is room. (`CLIPCUT_DATA` in `.env` still works and takes priority.)

## Updating

Clip Cut AI checks GitHub once a minute while it runs. When a newer version is out, the dashboard shows a notice
within a minute or two (no restart needed), with what changed
and how to update: ask your AI coding assistant to do it (the notice has a sentence to paste), or run
`git pull && pip install -r requirements.txt` in the Clip Cut AI folder and restart it (with Docker:
`git pull && docker compose up -d --build`). Your `.env`, keys and clips are not touched. Only the two commit ids
are sent to GitHub; set `CLIPCUT_UPDATE_CHECK=0` to turn the check off.

## Deploy

[DEPLOY.md](DEPLOY.md) walks through a single server with Docker: the app, PostgreSQL, and Caddy for HTTPS.

```bash
docker compose up -d --build
```

## How it behaves under load

- The page asks the server one small question every few seconds. When nothing has changed, the answer comes
  straight from memory.
- Each person's videos wait in their own line and the lines take turns, so one person cannot hold everyone up.
- The server measures its own processor, memory and disk every second. Extra videos and recordings start only
  while there is room, wait briefly when it is nearly full, and continue the moment it frees up.
- There are no limits on upload size, video length, recordings, creators or storage unless you set them in
  `.env`. Five videos can be sent at once. Request sizes are always capped, so junk can't fill the memory.

## Tests

```bash
python tests/run.py
```

This starts a copy of the app on a spare port with an empty temporary data folder, runs the permission, abuse and
queue tests against it, then removes it. It needs no keys and never touches real data.

## Security

- With sign-in off, Clip Cut AI listens on this computer only (`127.0.0.1`), refuses changes sent by other websites,
  and only answers to its own address. Do not expose it to the internet that way: turn accounts on.
- Passwords are stored only as salted scrypt hashes. Sessions are random tokens stored hashed; cookies are HTTP-only.
- Every route works out who is asking from the session, never from the request, so users only reach their own data.
- Only known video sites are fetched, and text from videos is treated as data when it is shown to the AI.
- Found a problem? Please report it privately through the repository's security advisories instead of opening a
  public issue.

## Using it responsibly

Clip videos you made, or have permission to use. You are responsible for the rights to what you download, clip and
post, and for following the terms of the sites you fetch from and post to.

## Licence

[MIT](LICENSE). Caption fonts in `studio/fonts/` (Anton, Archivo Black, Poppins) are under the SIL Open Font
License; the licence texts are in the same folder.
