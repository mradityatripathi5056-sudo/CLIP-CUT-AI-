"""Each user's connected social accounts and personal settings (alerts, posting pause).

Stored under users/<user>/accounts. People connect YouTube, Instagram, TikTok and Facebook with one click: they sign in on the
platform's own page and come back. For that, whoever runs the server registers one app with each platform once
(its id and secret), in .env or in the dashboard (Settings, Connected apps, Set up). Those belong to the server,
never to users."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from . import config, ctx

_lock = threading.RLock()
_states: dict = {}   # one-time values for the connect redirects: state -> (user id, when, platform)

SECRET_KEYS = ("discord_webhook", "telegram_token", "audd_token")
SETTING_DEFAULTS = {"discord_webhook": "", "telegram_token": "", "telegram_chat": "", "paused": False,
                    "digest_hour": 8, "last_digest": "", "tour_done": False,
                    # replies to comments (studio/replies.py): off, approve (drafts) or auto, with a daily limit
                    "reply_all": True,       # comments on all recent videos of the page, not only the app's posts
                    "reply_mode": "approve", "reply_cap": 30, "reply_tone": "", "reply_days": 3,
                    "tg_control": False,     # new clips and comment replies on Telegram with buttons (studio/telebot.py)
                    "weekly_report": True, "last_weekly": "",
                    "dm_rules": [],          # Instagram: a comment with a keyword gets a DM (studio/replies.py)
                    "two_step": False,       # signing in also needs a code sent by email (studio/mailsetup.py)
                    "backup_email": False,   # the weekly backup goes to your email too
                    "audd_token": "",        # AudD (audd.io) API token: finds songs in clips (studio/musiccheck.py)
                    "permission_template": "",   # your own message asking a streamer for permission (else the default)
                    "competitors": []}           # other clip pages to keep an eye on (studio/autopilot.py)

YT_SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
             "https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly "
             "https://www.googleapis.com/auth/yt-analytics-monetary.readonly")     # force-ssl: add to a playlist, post the first comment
YT_EXTRA = "youtube.force-ssl"
IG = "https://graph.instagram.com"
IG_UPLOAD = "https://rupload.facebook.com/ig-api-upload/v21.0"
IG_SCOPES = ("instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments,"
             "instagram_business_manage_messages")
TT = "https://open.tiktokapis.com/v2"
TT_SCOPES = "user.info.basic,video.publish"
# Facebook Login (for Business): one sign-in gives the person's Facebook Pages and the Instagram accounts linked to them.
FB_VER = "v21.0"
FB = f"https://graph.facebook.com/{FB_VER}"
FB_UPLOAD = f"https://rupload.facebook.com/video-upload/{FB_VER}"
FB_SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
             "instagram_basic,instagram_content_publish,"
             "pages_manage_engagement,pages_read_user_content,instagram_manage_comments,"   # replies to comments
             "instagram_manage_messages,pages_messaging")                                    # keyword DMs
PLATFORM_NAMES = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook",
                  "threads": "Threads", "bluesky": "Bluesky", "discord": "Discord", "telegram": "Telegram"}
KEY_PLATFORMS = ("threads", "bluesky", "discord", "telegram")    # connected by pasting a key, not by a Connect button
CONNECT_PLATFORMS = ("youtube", "instagram", "tiktok", "facebook")   # what a Connect button can start


def _dir() -> Path:
    d = config.user_dir(ctx.uid()) / "accounts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(name, default):
    f = _dir() / name
    if not f.exists():
        return default
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return default


def _write(name, data):
    with _lock:
        d = _dir()
        tmp = d / (name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        try:
            tmp.chmod(0o600)                 # these hold posting tokens: readable by the app only
        except OSError:
            pass
        tmp.replace(d / name)
        if name == "settings.json":
            _settings_mem[ctx.uid()] = {**SETTING_DEFAULTS, **data}
    ctx.bump()


# ------------------------------------------------------------------ the server's apps with each platform
# name -> (what the platform calls the id, what it calls the secret, .env names for both)
APPS = {"google": ("Client ID", "Client secret", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        "instagram": ("Instagram app ID", "Instagram app secret", "CLIPCUT_IG_APP_ID", "CLIPCUT_IG_APP_SECRET"),
        "tiktok": ("Client key", "Client secret", "CLIPCUT_TIKTOK_CLIENT_KEY", "CLIPCUT_TIKTOK_CLIENT_SECRET"),
        "meta": ("Meta app ID", "Meta app secret", "CLIPCUT_META_APP_ID", "CLIPCUT_META_APP_SECRET")}
APP_FOR = {"youtube": "google", "instagram": "instagram", "tiktok": "tiktok", "facebook": "meta"}
_apps_seen = {"at": None, "data": {}}


def _apps_file() -> Path:
    return config.DATA_DIR / "apps.json"


def _apps_saved() -> dict:
    f = _apps_file()
    try:
        at = f.stat().st_mtime_ns
    except OSError:
        at = 0
    if _apps_seen["at"] != at:
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if at else {}
        except (OSError, ValueError):
            data = {}
        _apps_seen.update(at=at, data=data if isinstance(data, dict) else {})
    return _apps_seen["data"]


def app_keys(name: str) -> tuple:
    """(id, secret) of the server's app with this platform: what the dashboard saved, or else .env."""
    saved = _apps_saved().get(name) or {}
    if saved.get("id") and saved.get("secret"):
        return saved["id"], saved["secret"]
    if name == "google":
        return config.google_client()
    _l1, _l2, id_env, secret_env = APPS[name]
    return (config.env(id_env) or "").strip(), (config.env(secret_env) or "").strip()


def meta_config_id() -> str:
    """The Configuration ID from Facebook Login for Business (optional). With one, Meta shows the permissions chosen in
    that configuration; without one, Clip Cut AI asks for the permissions it needs itself."""
    saved = (_apps_saved().get("meta") or {}).get("config", "")
    return str(saved or config.env("CLIPCUT_META_CONFIG_ID") or "").strip()


def can_connect(platform: str) -> bool:
    if platform not in APP_FOR:
        return False
    return all(app_keys(APP_FOR[platform]))


def redirect_for(platform: str) -> str:
    return f"{config.PUBLIC_URL}/oauth/{platform}/callback"


def apps_public() -> dict:
    """For the setup panel: whether each app is set, never its secret."""
    out = {}
    for platform, name in APP_FOR.items():
        cid, secret = app_keys(name)
        out[platform] = {"ready": bool(cid and secret), "id_label": APPS[name][0], "secret_label": APPS[name][1],
                         "id_hint": cid[:6] + "…" if len(cid) > 10 else cid, "redirect": redirect_for(platform),
                         "https": config.PUBLIC_URL.startswith("https://"),
                         "from_dashboard": bool((_apps_saved().get(name) or {}).get("id"))}
        if platform == "facebook":
            cfg = meta_config_id()
            out[platform].update(config_label="Configuration ID", has_config=bool(cfg),
                                 config_hint=cfg[:4] + "…" if len(cfg) > 8 else cfg)
    return out


def save_app(platform: str, cid: str, secret: str, config_id=None) -> dict:
    """Save the server's app for a platform, from the dashboard. An empty secret keeps the saved one.
    For Facebook, a Configuration ID (Facebook Login for Business) may come too: empty keeps the saved one."""
    if platform not in APP_FOR:
        raise ValueError("Unknown platform.")
    name = APP_FOR[platform]
    cid, secret = str(cid or "").strip()[:200], str(secret or "").strip()[:300]
    old = _apps_saved().get(name) or {}
    if not cid and not secret:
        raise ValueError(f"Paste the {APPS[name][0]} and {APPS[name][1]}.")
    cid = cid or old.get("id", "")                # only a new secret typed: keep the saved id
    if not re.fullmatch(r"[\w.\-]{4,200}", cid):
        raise ValueError(f"Paste the {APPS[name][0]} exactly as the platform shows it.")
    secret = secret or (old.get("secret") if old.get("id") == cid else "")
    if not secret:
        raise ValueError(f"Paste the {APPS[name][1]} too.")
    entry = {"id": cid, "secret": secret}
    if name == "meta":
        cfg = str(config_id or "").strip()[:40]
        if cfg and not re.fullmatch(r"\d{6,40}", cfg):
            raise ValueError("The Configuration ID is a long number. Copy it from Facebook Login for Business, Configurations.")
        entry["config"] = cfg or old.get("config", "")
    with _lock:
        data = dict(_apps_saved())
        data[name] = entry
        tmp = _apps_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(_apps_file())
        _apps_seen["at"] = None
    return apps_public()


def _new_state(platform: str) -> str:
    state = secrets.token_urlsafe(16)
    for k in [k for k, v in list(_states.items()) if time.time() - v[1] > 900]:
        _states.pop(k, None)
    _states[state] = (ctx.uid(), time.time(), platform)
    return state


def _take_state(state: str, platform: str):
    got = _states.pop(state or "", None)
    if not got or got[0] != ctx.uid() or got[2] != platform or time.time() - got[1] > 900:
        raise ValueError("This sign-in has expired. Press Connect again.")


def connect_url(platform: str) -> str:
    """Where the Connect button sends the browser: the platform's own sign-in page."""
    if platform not in APP_FOR:
        raise ValueError("Unknown platform.")
    if not can_connect(platform):
        raise ValueError(f"Connecting {PLATFORM_NAMES[platform]} isn't set up on this server yet.")
    cid, _ = app_keys(APP_FOR[platform])
    state, redirect = _new_state(platform), redirect_for(platform)
    if platform == "youtube":
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": YT_SCOPES,
            "access_type": "offline", "prompt": "consent", "state": state})
    if platform == "instagram":
        return "https://www.instagram.com/oauth/authorize?" + urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": IG_SCOPES, "state": state})
    if platform == "facebook":
        q = {"client_id": cid, "redirect_uri": redirect, "response_type": "code", "state": state}
        cfg = meta_config_id()
        q.update({"config_id": cfg} if cfg else {"scope": FB_SCOPES})
        return f"https://www.facebook.com/{FB_VER}/dialog/oauth?" + urlencode(q)
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": cid, "redirect_uri": redirect, "response_type": "code", "scope": TT_SCOPES, "state": state})


def connect_finish(platform: str, code: str, state: str) -> dict:
    _take_state(state, platform)
    code = (code or "").split("#")[0]           # Instagram adds "#_" to the code
    if not code:
        raise ValueError("The platform did not send a sign-in code. Try again.")
    return {"youtube": _youtube_finish, "instagram": _instagram_finish, "tiktok": _tiktok_finish,
            "facebook": _facebook_finish}[platform](code)


# ------------------------------------------------------------------ links the platforms can fetch a clip from
# Instagram takes a video by address, not as an upload. Each address works for one clip, for one hour, and is
# signed, so it cannot be guessed or changed to reach anything else.
def _link_key() -> bytes:
    f = config.DATA_DIR / "link.key"
    if not f.exists():
        with _lock:
            if not f.exists():
                f.write_bytes(secrets.token_bytes(32))
                try:
                    f.chmod(0o600)
                except OSError:
                    pass
    return f.read_bytes()


def clip_link(job_id: str, file_name: str, seconds: int = 3600) -> str:
    body = json.dumps([ctx.uid(), job_id, file_name, int(time.time() + seconds)], separators=(",", ":")).encode()
    b = base64.urlsafe_b64encode(body).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(_link_key(), b.encode(), hashlib.sha256).digest()[:18]).decode().rstrip("=")
    return f"{config.PUBLIC_URL}/pub/{b}.{sig}.mp4"


def read_clip_link(token: str):
    """(user id, job id, file name) for a valid, unexpired link, else None."""
    try:
        b, sig = token.split(".")
        want = base64.urlsafe_b64encode(hmac.new(_link_key(), b.encode(), hashlib.sha256).digest()[:18]).decode().rstrip("=")
        if not hmac.compare_digest(sig, want):
            return None
        uid, job_id, name, until = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
        if time.time() > until or not re.fullmatch(r"[\w\-]+\.mp4", name):
            return None
        return uid, job_id, name
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ settings
_settings_mem: dict = {}


def settings() -> dict:
    u = ctx.uid()
    if u not in _settings_mem:
        _settings_mem[u] = {**SETTING_DEFAULTS, **_read("settings.json", {})}
    return dict(_settings_mem[u])


def save_settings(patch: dict) -> dict:
    with _lock:
        s = settings()
        for k, v in patch.items():
            if k not in SETTING_DEFAULTS:
                continue
            if k in ("paused", "tour_done", "tg_control", "weekly_report", "two_step", "backup_email", "reply_all"):
                v = bool(v)
            elif k == "dm_rules":
                v = _clean_dm_rules(v)
            elif k == "digest_hour":
                v = max(0, min(23, int(v)))
            elif k == "reply_mode":
                v = v if v in ("off", "approve", "auto") else "off"
            elif k == "reply_cap":
                v = max(1, min(200, int(float(v or 30))))
            elif k == "competitors":
                v = [u.strip() for u in (v if isinstance(v, list) else str(v or "").split()) if u.strip()][:8]
                if any(not re.fullmatch(r"https://(www\.)?youtube\.com/(@[\w.\-]+|channel/[\w\-]+)/?", u) for u in v):
                    raise ValueError("Add YouTube channel links like https://www.youtube.com/@page")
            elif k == "permission_template":
                v = str(v or "").strip()[:1500]
            elif k == "reply_days":
                v = max(1, min(14, int(float(v or 3))))
            else:
                v = str(v).strip()[:300]
                if k == "discord_webhook" and v and not v.startswith("https://discord.com/api/webhooks/"):
                    raise ValueError("That doesn't look like a Discord webhook link.")
                if k in SECRET_KEYS and v == "":
                    continue  # blank means "keep what is saved"
            s[k] = v
        _write("settings.json", s)
        return s


def _clean_dm_rules(v) -> list:
    """[{"word": "game", "text": "It's Valorant! ..."}]: up to 10 keywords, each with the message sent to whoever
    comments it."""
    out = []
    for r in (v if isinstance(v, list) else [])[:10]:
        if not isinstance(r, dict):
            continue
        word = re.sub(r"\s+", " ", str(r.get("word", ""))).strip().lower()[:40]
        text = str(r.get("text", "")).strip()[:900]
        if word and text:
            out.append({"word": word, "text": text})
    return out


def public_settings() -> dict:
    s = settings()
    return {k: (bool(v) if k in SECRET_KEYS else v) for k, v in s.items()}


# ------------------------------------------------------------------ accounts
def _all() -> list:
    return [a for a in _read("accounts.json", []) if a.get("platform") in PLATFORM_NAMES]


def get(aid):
    return next((a for a in _all() if a["id"] == aid), None)


def list_accounts() -> list:
    return [{"id": a["id"], "platform": a["platform"], "label": PLATFORM_NAMES[a["platform"]], "name": a["name"],
             "added": a["added"], "detail": a.get("detail", ""), "via": a.get("via", ""),
             "lang": a.get("lang", "auto"),
             "daily_limit": a["daily_limit"] if a.get("daily_limit") is not None else {"youtube": 3}.get(a["platform"], 0)}
            for a in _all()]


def set_limit(aid, n):
    """At most n posts a day on this account (0 = no limit). See studio/limits.py."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValueError("The daily limit is a number, like 3.")
    if not 0 <= n <= 50:
        raise ValueError("Pick a daily limit from 0 (no limit) to 50.")
    with _lock:
        a = get(aid)
        if not a:
            raise KeyError(aid)
        a["daily_limit"] = n
        _put(a)


def set_lang(aid, lang: str):
    """auto: the creator's audience decides; hinglish or english: this page always posts in that language."""
    if lang not in ("auto", "hinglish", "english"):
        raise ValueError("Pick auto, Hinglish or English.")
    with _lock:
        a = get(aid)
        if not a:
            raise KeyError(aid)
        a["lang"] = lang
        _put(a)


def connect_key(platform: str, f: dict) -> dict:
    """Threads (an access token from the Threads API), Bluesky (handle + app password) or a Discord channel
    (webhook link). The key is checked once before it is saved."""
    import uuid
    f = {k: str(v or "").strip() for k, v in (f or {}).items()}
    if platform == "discord":
        if not re.fullmatch(r"https://(discord|discordapp)\.com/api/webhooks/\d+/[\w\-]+", f.get("webhook", "")):
            raise ValueError("Paste the webhook link from Discord: channel settings, Integrations, Webhooks.")
        r = _check(httpx.get(f["webhook"], timeout=20), "Discord")
        acc = {"name": "#" + (r.json().get("name") or "discord"), "webhook": f["webhook"]}
    elif platform == "bluesky":
        handle = f.get("handle", "").lstrip("@")
        if not re.fullmatch(r"[\w.\-]+\.[a-z]{2,}", handle) or len(f.get("password", "")) < 8:
            raise ValueError("Enter your Bluesky handle (like name.bsky.social) and an app password (Settings, App passwords).")
        s = _check(httpx.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                              json={"identifier": handle, "password": f["password"]}, timeout=20), "Bluesky").json()
        acc = {"name": "@" + s.get("handle", handle), "handle": handle, "app_password": f["password"], "did": s.get("did", "")}
    elif platform == "threads":
        token = f.get("token", "")
        if len(token) < 20:
            raise ValueError("Paste a Threads access token (Meta app with the Threads API, threads_content_publish).")
        me_ = _check(httpx.get("https://graph.threads.net/v1.0/me", params={"fields": "id,username", "access_token": token},
                               timeout=20), "Threads").json()
        acc = {"name": "@" + me_.get("username", "threads"), "token": token, "uid": me_["id"]}
    elif platform == "telegram":
        token, chat = f.get("token", ""), f.get("chat", "")
        if not re.fullmatch(r"\d{5,}:[\w\-]{30,}", token):
            raise ValueError("Paste the bot token from @BotFather (like 123456:ABC...).")
        if not re.fullmatch(r"@[\w]{5,}|-100\d{6,}", chat):
            raise ValueError("Write the channel as @yourchannel (and add the bot to it as an admin).")
        r = httpx.get(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": chat}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError("Telegram couldn't find that channel, or the bot isn't in it.")
        acc = {"name": (r.json().get("result") or {}).get("title") or chat, "token": token, "chat": chat}
    else:
        raise ValueError("Unknown kind of account.")
    acc.update(id=uuid.uuid4().hex[:12], platform=platform, added=time.time(), detail="")
    _put(acc)
    return {k: acc[k] for k in ("id", "platform", "name")}


def threads_upload(acc, path: Path, text: str, job_id: str):
    """Threads fetches the video from a link, so this works only on a public site (PUBLIC_URL with https)."""
    if not (config.PUBLIC_URL or "").startswith("https://"):
        raise RuntimeError("Threads needs the app on a public https address (PUBLIC_URL) to fetch the video.")
    base, tok = f"https://graph.threads.net/v1.0/{acc['uid']}", {"access_token": acc["token"]}
    box = _check(httpx.post(f"{base}/threads", data={"media_type": "VIDEO", "video_url": clip_link(job_id, path.name),
                                                     "text": text[:500], **tok}, timeout=60), "Threads").json()
    for _ in range(60):
        st = httpx.get(f"https://graph.threads.net/v1.0/{box['id']}", params={"fields": "status", **tok}, timeout=30).json()
        if st.get("status") == "FINISHED":
            break
        if st.get("status") == "ERROR":
            raise RuntimeError("Threads couldn't process the video.")
        time.sleep(5)
    pub = _check(httpx.post(f"{base}/threads_publish", data={"creation_id": box["id"], **tok}, timeout=60), "Threads").json()
    return pub["id"], f"https://www.threads.net/@{acc['name'].lstrip('@')}"


def bluesky_upload(acc, path: Path, text: str):
    s = _check(httpx.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                          json={"identifier": acc["handle"], "password": acc["app_password"]}, timeout=20), "Bluesky").json()
    h = {"Authorization": f"Bearer {s['accessJwt']}"}
    if path.stat().st_size > 50_000_000:
        raise RuntimeError("Bluesky takes videos up to 50 MB.")
    blob = _check(httpx.post("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", content=path.read_bytes(),
                             headers={**h, "Content-Type": "video/mp4"}, timeout=300), "Bluesky").json()["blob"]
    rec = {"$type": "app.bsky.feed.post", "text": text[:300], "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "embed": {"$type": "app.bsky.embed.video", "video": blob, "aspectRatio": {"width": 9, "height": 16}}}
    r = _check(httpx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", headers=h, timeout=60,
                          json={"repo": s["did"], "collection": "app.bsky.feed.post", "record": rec}), "Bluesky").json()
    return r["uri"], f"https://bsky.app/profile/{s['handle']}/post/{r['uri'].rsplit('/', 1)[-1]}"


def discord_upload(acc, path: Path, text: str):
    """The clip as a file in the channel (Discord webhooks take files up to 10 MB; bigger ones get a link)."""
    if path.stat().st_size <= 10_000_000:
        with open(path, "rb") as fh:
            r = httpx.post(acc["webhook"] + "?wait=true", data={"payload_json": json.dumps(
                {"content": text[:1900], "allowed_mentions": {"parse": []}})}, files={"file": (path.name, fh, "video/mp4")},
                timeout=120)
    else:
        r = httpx.post(acc["webhook"] + "?wait=true", json={"content": text[:1900], "allowed_mentions": {"parse": []}}, timeout=30)
    m = _check(r, "Discord").json()
    return str(m.get("id", "")), ""


def _put(acc):
    with _lock:
        rest = [a for a in _all() if a["id"] != acc["id"]]
        _write("accounts.json", rest + [acc])


def remove(aid):
    with _lock:
        _write("accounts.json", [a for a in _all() if a["id"] != aid])


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"{what} failed ({r.status_code}): {r.text[:300]}")
    return r


# ------------------------------------------------------------------ YouTube
def youtube_ready() -> bool:
    return can_connect("youtube")


def _youtube_finish(code: str) -> dict:
    cid, secret = app_keys("google")
    tok = _check(httpx.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect_for("youtube"), "grant_type": "authorization_code"}, timeout=30), "Google sign-in").json()
    if "refresh_token" not in tok:
        raise ValueError("Google did not return a long-lived sign-in. Remove Clip Cut AI's access in your Google account and connect again.")
    ch = _check(httpx.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30), "Reading the channel").json()
    if not ch.get("items"):
        raise ValueError("That Google account has no YouTube channel. Create one on YouTube, then connect again.")
    item = ch["items"][0]
    acc = {"id": f"yt_{item['id']}", "platform": "youtube", "name": item["snippet"]["title"], "added": time.time(),
           "refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
           "expires": time.time() + tok.get("expires_in", 3600) - 60, "scope": str(tok.get("scope", YT_SCOPES)),
           "detail": "" if YT_EXTRA in str(tok.get("scope", YT_SCOPES)) else "Tick every box when connecting to allow playlists and the first comment"}
    _put(acc)
    return acc


def _yt_token(acc) -> str:
    if acc.get("expires", 0) > time.time():
        return acc["access_token"]
    cid, secret = app_keys("google")
    tok = _check(httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": secret,
        "refresh_token": acc["refresh_token"], "grant_type": "refresh_token"}, timeout=30),
        "Refreshing the YouTube sign-in").json()
    acc.update(access_token=tok["access_token"], expires=time.time() + tok.get("expires_in", 3600) - 60)
    _put(acc)
    return acc["access_token"]


YT_CATEGORIES = {"20": "Gaming", "24": "Entertainment", "23": "Comedy", "22": "People & Blogs", "17": "Sports",
                 "10": "Music", "1": "Film & Animation", "26": "Howto & Style", "27": "Education",
                 "28": "Science & Technology", "25": "News & Politics", "2": "Autos & Vehicles", "15": "Pets & Animals",
                 "19": "Travel & Events", "29": "Nonprofits & Activism"}


def _rfc3339(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def youtube_upload(acc, path: Path, title: str, description: str, tags: list, privacy: str,
                   category: str = "20", notify: bool = True, publish_at: float = 0):
    """A Short. With publish_at (a time in the future), YouTube keeps it private and makes it public by itself at
    that time, so the computer does not need to be on then."""
    token = _yt_token(acc)
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at and publish_at > time.time() + 60:
        status.update(privacyStatus="private", publishAt=_rfc3339(publish_at))
    meta = {"snippet": {"title": re.sub(r"[<>]", "", title)[:100] or "Clip", "description": re.sub(r"[<>]", "", description)[:4900],
                        "tags": tags[:15], "categoryId": category if category in YT_CATEGORIES else "20"},
            "status": status}
    size = path.stat().st_size
    start = _check(httpx.post("https://www.googleapis.com/upload/youtube/v3/videos",
                              params={"uploadType": "resumable", "part": "snippet,status",
                                      "notifySubscribers": "true" if notify else "false"}, json=meta,
                              headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                       "X-Upload-Content-Length": str(size)}, timeout=60), "Starting the YouTube upload")
    with path.open("rb") as f:
        done = _check(httpx.put(start.headers["Location"], content=f.read(),
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, timeout=900),
                      "Uploading to YouTube").json()
    return done["id"], f"https://www.youtube.com/shorts/{done['id']}"


def youtube_thumbnail(acc, video_id: str, jpg: Path):
    """A custom thumbnail (the channel must be allowed custom thumbnails: a verified phone number on YouTube)."""
    _check(httpx.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": video_id},
                      content=jpg.read_bytes(), headers={"Authorization": f"Bearer {_yt_token(acc)}", "Content-Type": "image/jpeg"},
                      timeout=60), "Setting the thumbnail")


def playlist_id(v: str) -> str:
    """A playlist id, from the id itself or a playlist link (…?list=PL…)."""
    v = str(v or "").strip()
    m = re.search(r"[?&]list=([\w\-]{10,64})", v)
    v = m.group(1) if m else v
    return v if re.fullmatch(r"[\w\-]{10,64}", v) else ""


def youtube_playlist_add(acc, playlist: str, video_id: str):
    pid = playlist_id(playlist)
    if not pid:
        raise ValueError("That playlist link is not one YouTube recognises.")
    _check(httpx.post("https://www.googleapis.com/youtube/v3/playlistItems", params={"part": "snippet"},
                      json={"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                      headers={"Authorization": f"Bearer {_yt_token(acc)}"}, timeout=30), "Adding to the playlist")


def youtube_comment(acc, video_id: str, text: str):
    _check(httpx.post("https://www.googleapis.com/youtube/v3/commentThreads", params={"part": "snippet"},
                      json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text[:1000]}}}},
                      headers={"Authorization": f"Bearer {_yt_token(acc)}"}, timeout=30), "Posting the first comment")


def youtube_status(acc, ids: list) -> dict:
    """{video id: {uploadStatus, rejectionReason, privacyStatus}} (a blocked or rejected Short shows here)."""
    out = {}
    for i in range(0, len(ids), 50):
        r = _check(httpx.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "status", "id": ",".join(ids[i:i + 50])},
                             headers={"Authorization": f"Bearer {_yt_token(acc)}"}, timeout=30), "Reading YouTube status").json()
        for it in r.get("items", []):
            out[it["id"]] = it.get("status", {})
    return out


def telegram_upload(acc, path: Path, text: str):
    """The clip as a video in your Telegram channel (the bot must be an admin there; videos up to 50 MB)."""
    if path.stat().st_size > 50_000_000:
        raise RuntimeError("Telegram bots can send videos up to 50 MB.")
    with open(path, "rb") as fh:
        r = httpx.post(f"https://api.telegram.org/bot{acc['token']}/sendVideo",
                       data={"chat_id": acc["chat"], "caption": text[:1000], "supports_streaming": "true"},
                       files={"video": (path.name, fh, "video/mp4")}, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram said {r.status_code}: {r.json().get('description', '')[:150] if r.headers.get('content-type', '').startswith('application/json') else ''}")
    m = r.json()["result"]
    ch = acc["chat"].lstrip("@")
    return str(m["message_id"]), (f"https://t.me/{ch}/{m['message_id']}" if not ch.lstrip("-").isdigit() else "")


def youtube_views(acc, ids: list) -> dict:
    out = {}
    for i in range(0, len(ids), 50):
        r = _check(httpx.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                             headers={"Authorization": f"Bearer {_yt_token(acc)}"}, timeout=30), "Reading YouTube views").json()
        for it in r.get("items", []):
            out[it["id"]] = int(it["statistics"].get("viewCount", 0))
    return out


# ------------------------------------------------------------------ Instagram (Instagram Login, professional accounts)
def _instagram_finish(code: str) -> dict:
    cid, secret = app_keys("instagram")
    short = _check(httpx.post("https://api.instagram.com/oauth/access_token", data={
        "client_id": cid, "client_secret": secret, "grant_type": "authorization_code",
        "redirect_uri": redirect_for("instagram"), "code": code}, timeout=30), "Instagram sign-in").json()
    if isinstance(short.get("data"), list) and short["data"]:
        short = short["data"][0]
    if "instagram_business_content_publish" not in str(short.get("permissions", "instagram_business_content_publish")):
        raise ValueError("Clip Cut AI needs permission to publish. Connect again and leave every box ticked.")
    long = _check(httpx.get(f"{IG}/access_token", params={"grant_type": "ig_exchange_token", "client_secret": secret,
                                                         "access_token": short["access_token"]}, timeout=30),
                  "Keeping the Instagram sign-in").json()
    return _instagram_save(long["access_token"])


def _instagram_save(token: str) -> dict:
    me = _check(httpx.get(f"{IG}/me", params={"fields": "user_id,username,account_type"},
                          headers={"Authorization": f"Bearer {token}"}, timeout=30), "Reading the Instagram account").json()
    kind = str(me.get("account_type") or "")
    acc = {"id": f"ig_{me['user_id']}", "platform": "instagram", "name": "@" + me["username"], "added": time.time(),
           "user_id": str(me["user_id"]), "token": token, "token_time": time.time(),
           "detail": {"BUSINESS": "Business account", "MEDIA_CREATOR": "Creator account"}.get(kind.upper(), "")}
    _put(acc)
    return acc


def instagram_add(token: str) -> dict:
    """An account added with a token pasted from the Meta app dashboard (older way; Connect is the normal one)."""
    return _instagram_save(token.strip())


def _ig_token(acc) -> str:
    if acc.get("via") == "facebook":
        return acc["token"]     # a Page's token from Facebook Login: it does not run out while the person keeps access
    if time.time() - acc.get("token_time", 0) > 7 * 86400:  # tokens last 60 days; refresh weekly
        try:
            r = _check(httpx.get(f"{IG}/refresh_access_token", params={"grant_type": "ig_refresh_token"},
                                 headers={"Authorization": f"Bearer {acc['token']}"}, timeout=30), "Refreshing").json()
            acc.update(token=r["access_token"], token_time=time.time())
            _put(acc)
        except Exception:  # noqa: BLE001 - keep using the current token until it truly expires
            pass
    return acc["token"]


def instagram_upload(acc, path: Path, caption: str, job_id: str = "", kind: str = "REELS", cover_ms: int = 1200,
                     collaborators: str = ""):
    """A Reel. On a public site Instagram fetches the clip from a one-hour signed link; on a computer it cannot
    reach, the file is sent instead (only possible for some app types)."""
    token = _ig_token(acc)
    auth = {"Authorization": f"Bearer {token}"}
    uid = acc["user_id"]
    host = FB if acc.get("via") == "facebook" else IG      # connected through Facebook Login, or Instagram Login
    # A Reel shows the frame at cover_ms in the grid: the same moment as the clip's cover, with its big text on it.
    extra = ({"caption": caption[:2200], "share_to_feed": "true", "thumb_offset": str(int(cover_ms))} if kind == "REELS" else {})
    names = [n.strip() for n in (collaborators or "").split(",") if n.strip()]
    if names and kind == "REELS":       # a Collab: the invite shows up for them; once they accept, it is on both pages
        extra["collaborators"] = json.dumps(names[:3])
    # Instagram fetches the video from a public address when there is one, except through ngrok, whose free plan has
    # 1 GB a month: then the file is sent straight from this computer (resumable upload), which costs ngrok nothing.
    if config.PUBLIC_URL.startswith("https://") and job_id and ".ngrok" not in config.PUBLIC_URL:
        box = _check(httpx.post(f"{host}/{uid}/media", data={"media_type": kind, "video_url": clip_link(job_id, path.name), **extra},
                                headers=auth, timeout=60), "Starting the Instagram post").json()
    else:
        box = _check(httpx.post(f"{host}/{uid}/media", data={"media_type": kind, "upload_type": "resumable", **extra},
                                headers=auth, timeout=60), "Starting the Instagram upload").json()
        with path.open("rb") as f:
            _check(httpx.post(f"{IG_UPLOAD}/{box['id']}", content=f.read(),
                              headers={"Authorization": f"OAuth {token}", "offset": "0",
                                       "file_size": str(path.stat().st_size)}, timeout=900),
                   "Uploading to Instagram (posting from a computer needs a public https address)")
    for _ in range(90):
        st = _check(httpx.get(f"{host}/{box['id']}", params={"fields": "status_code,status"}, headers=auth, timeout=30),
                    "Checking the Instagram upload").json()
        if st.get("status_code") in ("FINISHED", "PUBLISHED"):
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram rejected the video: {st.get('status', st['status_code'])}")
        time.sleep(6)
    else:
        raise RuntimeError("Instagram took too long to process the video.")
    pub = _check(httpx.post(f"{host}/{uid}/media_publish", data={"creation_id": box["id"]}, headers=auth, timeout=60),
                 "Publishing on Instagram").json()
    link = ""
    try:
        link = httpx.get(f"{host}/{pub['id']}", params={"fields": "permalink"}, headers=auth, timeout=30).json().get("permalink", "")
    except Exception:  # noqa: BLE001
        pass
    return pub["id"], link


def instagram_views(acc, media_id: str):
    host = FB if acc.get("via") == "facebook" else IG
    r = httpx.get(f"{host}/{media_id}/insights", params={"metric": "views"},
                  headers={"Authorization": f"Bearer {_ig_token(acc)}"}, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json().get("data", [])
    return int(data[0]["values"][0]["value"]) if data else None


# ------------------------------------------------------------------ Facebook Login: Facebook Pages, and Instagram through them
# One sign-in with Facebook adds every Facebook Page the person chose, and the Instagram professional account linked
# to each Page. This is the way to go when the Meta app was made with Facebook Login for Business (it gives a
# Configuration ID), and it is the only way to post to a Facebook Page.
def _fb(r, what):
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        err = data.get("error") if isinstance(data, dict) and isinstance(data.get("error"), dict) else {}
        raise RuntimeError(f"{what} failed ({err.get('code') or r.status_code}): {err.get('message') or r.text[:200]}")
    return data


def _facebook_finish(code: str) -> dict:
    cid, secret = app_keys("meta")
    short = _fb(httpx.get(f"{FB}/oauth/access_token", params={
        "client_id": cid, "client_secret": secret, "redirect_uri": redirect_for("facebook"), "code": code}, timeout=30),
        "Facebook sign-in")
    long = _fb(httpx.get(f"{FB}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": cid, "client_secret": secret,
        "fb_exchange_token": short["access_token"]}, timeout=30), "Keeping the Facebook sign-in")
    user_token = long.get("access_token") or short["access_token"]
    return _facebook_pages(user_token)


def _business_pages(user_token: str) -> list:
    """Pages in the person's Business portfolios (Meta Business Suite), with a Page token for each."""
    h = {"Authorization": f"Bearer {user_token}"}
    out, seen = [], set()
    try:
        biz = httpx.get(f"{FB}/me/businesses", params={"fields": "id,name", "limit": 50}, headers=h, timeout=30).json().get("data") or []
    except Exception:  # noqa: BLE001
        return []
    for b in biz:
        for edge in ("owned_pages", "client_pages"):
            try:
                rows = httpx.get(f"{FB}/{b['id']}/{edge}", params={
                    "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 100},
                    headers=h, timeout=30).json().get("data") or []
            except Exception:  # noqa: BLE001
                rows = []
            for pg in rows:
                if pg.get("id") not in seen:
                    seen.add(pg.get("id"))
                    out.append(pg)
    return out


def _facebook_pages(user_token: str) -> dict:
    """Every Page the token can post to, and the Instagram professional account linked to each, as accounts."""
    pages = _fb(httpx.get(f"{FB}/me/accounts", params={
        "fields": "id,name,access_token,tasks,instagram_business_account{id,username}", "limit": 100},
        headers={"Authorization": f"Bearer {user_token}"}, timeout=30), "Reading your Facebook Pages").get("data") or []
    if not pages:                     # Pages owned by a Business portfolio don't always show in /me/accounts
        pages = _business_pages(user_token)
    if not pages:
        raise ValueError("No Facebook Page came back. In Graph API Explorer press Generate Access Token again, choose "
                         "\"Edit previous settings\" / \"Opt in to all current and future Pages\" and tick your Page and its "
                         "Instagram. If you have no Facebook Page yet, make one and link your Instagram to it first.")
    added = []
    for pg in pages:
        if not pg.get("access_token"):
            continue
        fb_acc = {"id": f"fb_{pg['id']}", "platform": "facebook", "name": pg.get("name") or "Facebook Page",
                  "added": time.time(), "page_id": str(pg["id"]), "token": pg["access_token"], "detail": "Facebook Page"}
        _put(fb_acc)
        added.append(fb_acc)
        ig = pg.get("instagram_business_account") or {}
        if ig.get("id"):
            ig_acc = {"id": f"ig_{ig['id']}", "platform": "instagram", "via": "facebook",
                      "name": "@" + (ig.get("username") or ig["id"]), "added": time.time(), "user_id": str(ig["id"]),
                      "token": pg["access_token"], "token_time": time.time(), "page_id": str(pg["id"]),
                      "detail": f"Through the Facebook Page {pg.get('name') or ''}".strip()}
            _put(ig_acc)
            added.append(ig_acc)
    if not added:
        raise ValueError("Facebook did not allow posting to any Page. Connect again and allow every permission.")
    pages_n = sum(1 for a in added if a["platform"] == "facebook")
    igs = [a["name"] for a in added if a["platform"] == "instagram"]
    name = f"{pages_n} Facebook Page{'s' if pages_n != 1 else ''}" + (f" and Instagram {', '.join(igs)}" if igs else "")
    return {**added[0], "name": name}


def facebook_by_token(token: str) -> dict:
    """Connect Facebook by pasting a token, without the Connect button's app setup: a User token (from Graph API
    Explorer, ideally extended to 60 days) adds every Page and linked Instagram; a Page token adds that Page."""
    token = re.sub(r"\s+", "", token or "")
    if not re.fullmatch(r"EA[A-Za-z0-9]{40,}", token):
        raise ValueError("Paste a Facebook access token (it starts with EA). See the steps below the box.")
    if all(app_keys("meta")):         # the Meta app is saved: swap the token for a long-lived one first
        cid, secret = app_keys("meta")
        try:
            long = httpx.get(f"{FB}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": cid,
                             "client_secret": secret, "fb_exchange_token": token}, timeout=30)
            if long.status_code < 400 and long.json().get("access_token"):
                token = long.json()["access_token"]
        except Exception:  # noqa: BLE001 - the token as pasted still works for now
            pass
    me_ = _fb(httpx.get(f"{FB}/me", params={"fields": "id,name", "metadata": "1"},
                        headers={"Authorization": f"Bearer {token}"}, timeout=30), "Checking the token")
    kind = ((me_.get("metadata") or {}).get("type") or "").lower()
    if kind != "page":                          # a person's token (asking a User for "category" is an error): their Pages
        try:
            return _facebook_pages(token)
        except RuntimeError as e:
            if kind == "user" or "nonexist" not in str(e).lower():
                raise                           # (a Page token has no Pages list: fall through to the Page itself)
    page = _fb(httpx.get(f"{FB}/{me_['id']}", params={"fields": "id,name,instagram_business_account{id,username}"},
                         headers={"Authorization": f"Bearer {token}"}, timeout=30), "Reading the Page")
    fb_acc = {"id": f"fb_{page['id']}", "platform": "facebook", "name": page.get("name") or "Facebook Page",
              "added": time.time(), "page_id": str(page["id"]), "token": token, "detail": "Facebook Page (token)"}
    _put(fb_acc)
    ig = page.get("instagram_business_account") or {}
    if ig.get("id"):
        _put({"id": f"ig_{ig['id']}", "platform": "instagram", "via": "facebook", "name": "@" + (ig.get("username") or ig["id"]),
              "added": time.time(), "user_id": str(ig["id"]), "token": token, "token_time": time.time(),
              "page_id": str(page["id"]), "detail": f"Through the Facebook Page {page.get('name') or ''}".strip()})
        return {**fb_acc, "name": f"{fb_acc['name']} and Instagram @{ig.get('username') or ig['id']}"}
    return fb_acc


def facebook_upload(acc, path: Path, caption: str, title: str = ""):
    """A Reel on a Facebook Page: start, send the file straight to Facebook (no public address needed), publish."""
    token, page = acc["token"], acc["page_id"]
    start = _fb(httpx.post(f"{FB}/{page}/video_reels", data={"upload_phase": "start", "access_token": token}, timeout=60),
                "Starting the Facebook post")
    vid = start["video_id"]
    with path.open("rb") as f:
        _fb(httpx.post(start.get("upload_url") or f"{FB_UPLOAD}/{vid}", content=f.read(), timeout=900,
                       headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(path.stat().st_size)}),
            "Uploading to Facebook")
    _fb(httpx.post(f"{FB}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                     "description": caption[:2200], "title": title[:100],
                                                     "access_token": token}, timeout=60), "Publishing on Facebook")
    for _ in range(90):
        st = _fb(httpx.get(f"{FB}/{vid}", params={"fields": "status", "access_token": token}, timeout=30),
                 "Checking the Facebook post").get("status") or {}
        if st.get("video_status") in ("ready", "published") or (st.get("publishing_phase") or {}).get("status") == "complete":
            break
        if st.get("video_status") == "error" or (st.get("processing_phase") or {}).get("status") == "error":
            raise RuntimeError("Facebook could not process the video: " + str((st.get("processing_phase") or {}).get("error") or "no reason given")[:200])
        time.sleep(6)
    else:
        raise RuntimeError("Facebook took too long to process the video.")
    return str(vid), f"https://www.facebook.com/reel/{vid}"


def facebook_views(acc, video_id: str):
    r = httpx.get(f"{FB}/{video_id}/video_insights", params={"metric": "blue_reels_play_count", "access_token": acc["token"]}, timeout=30)
    if r.status_code != 200:
        return None
    try:
        data = r.json().get("data", [])
        return int(data[0]["values"][0]["value"]) if data else None
    except (ValueError, KeyError, IndexError, TypeError):
        return None


# ------------------------------------------------------------------ TikTok (Login Kit + Content Posting API)
def _tt(r, what):
    """TikTok answers with an "error" object even on success; anything but "ok" is a failure."""
    try:
        data = r.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    if r.status_code >= 400 or (err and err.get("code") not in (None, "ok")) or (isinstance(data.get("error"), str)):
        code = err.get("code") or data.get("error") or r.status_code
        msg = err.get("message") or data.get("error_description") or r.text[:200]
        e = RuntimeError(f"{what} failed ({code}): {msg}")
        e.code = code
        raise e
    return data


def _tt_tokens(form: dict) -> dict:
    cid, secret = app_keys("tiktok")
    return _tt(httpx.post(f"{TT}/oauth/token/", data={"client_key": cid, "client_secret": secret, **form},
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30), "TikTok sign-in")


def _tiktok_finish(code: str) -> dict:
    tok = _tt_tokens({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_for("tiktok")})
    if "video.publish" not in str(tok.get("scope", "")):
        raise ValueError("Clip Cut AI needs permission to post videos. Connect again and allow posting.")
    acc = {"id": f"tt_{tok['open_id']}", "platform": "tiktok", "name": "TikTok account", "added": time.time(),
           "open_id": tok["open_id"], "access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
           "expires": time.time() + int(tok.get("expires_in", 7200)) - 120}
    try:
        info = _tiktok_creator(acc)
        acc["name"] = "@" + info["creator_username"] if info.get("creator_username") else info.get("creator_nickname") or acc["name"]
    except Exception:  # noqa: BLE001 - the name is only for showing
        pass
    _put(acc)
    return acc


def _tt_token(acc) -> str:
    if acc.get("expires", 0) > time.time():
        return acc["access_token"]
    tok = _tt_tokens({"grant_type": "refresh_token", "refresh_token": acc["refresh_token"]})
    # every refresh hands out a new refresh token and retires the old one: keep the new one straight away
    acc.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token", acc["refresh_token"]),
               expires=time.time() + int(tok.get("expires_in", 7200)) - 120)
    _put(acc)
    return acc["access_token"]


def _tt_post(acc, path_, body, what):
    return _tt(httpx.post(f"{TT}{path_}", json=body, timeout=60,
                          headers={"Authorization": f"Bearer {_tt_token(acc)}", "Content-Type": "application/json; charset=UTF-8"}),
               what).get("data") or {}


def _tiktok_creator(acc) -> dict:
    return _tt_post(acc, "/post/publish/creator_info/query/", {}, "Reading the TikTok account")


# Clip Cut AI's visibility setting -> what TikTok calls it, best first
TT_PRIVACY = {"public": ["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS"],
              "unlisted": ["MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"], "private": ["SELF_ONLY"]}


def _tt_chunks(size: int) -> tuple:
    """(chunk size, how many). Up to 64 MB goes in one piece; bigger files in 10 MB pieces, the last one taking the rest."""
    if size <= 64_000_000:
        return size, 1
    return 10_000_000, size // 10_000_000


def tiktok_upload(acc, path: Path, caption: str, privacy: str = "public"):
    info = _tiktok_creator(acc)
    options = info.get("privacy_level_options") or ["SELF_ONLY"]
    level = next((p for p in TT_PRIVACY.get(privacy, ["SELF_ONLY"]) if p in options), "SELF_ONLY" if "SELF_ONLY" in options else options[0])
    size = path.stat().st_size
    chunk, count = _tt_chunks(size)

    def init(lv):
        return _tt_post(acc, "/post/publish/video/init/", {
            "post_info": {"title": caption[:2200], "privacy_level": lv, "disable_duet": False, "disable_comment": False,
                          "disable_stitch": False, "video_cover_timestamp_ms": 1000},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}},
            "Starting the TikTok post")
    note = ""
    try:
        box = init(level)
    except RuntimeError as e:
        # A TikTok app that has not passed TikTok's review can only post privately: post privately, and say so.
        if "unaudited" not in str(getattr(e, "code", "")) or level == "SELF_ONLY" or "SELF_ONLY" not in options:
            raise
        level, note = "SELF_ONLY", "Posted as private: this server's TikTok app hasn't passed TikTok's review yet."
        box = init(level)
    with path.open("rb") as f:
        for n in range(count):
            first = n * chunk
            last = size - 1 if n == count - 1 else first + chunk - 1
            part = f.read(last - first + 1)
            r = httpx.put(box["upload_url"], content=part, timeout=900, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(part)), "Content-Range": f"bytes {first}-{last}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"Uploading to TikTok failed ({r.status_code}): {r.text[:200]}")
    for _ in range(120):
        st = _tt_post(acc, "/post/publish/status/fetch/", {"publish_id": box["publish_id"]}, "Checking the TikTok post")
        if st.get("status") == "PUBLISH_COMPLETE":
            break
        if st.get("status") == "FAILED":
            raise RuntimeError(f"TikTok did not publish the video: {st.get('fail_reason') or 'no reason given'}")
        time.sleep(5)
    else:
        raise RuntimeError("TikTok took too long to publish the video.")
    ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
    user = info.get("creator_username") or ""
    url = f"https://www.tiktok.com/@{user}/video/{ids[0]}" if ids and user else ""
    if note:
        acc["detail"] = "Posts are private until this server's TikTok app is reviewed"
        _put(acc)
    return str(ids[0]) if ids else box["publish_id"], url
