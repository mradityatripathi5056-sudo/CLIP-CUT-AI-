"""Creator workspaces. Each user has their own: users/<user>/creators/<id>/{videos,live,creator.json,log.jsonl}."""
import copy
import json
import re
import threading
import time
from pathlib import Path

from . import config, ctx


def _root() -> Path:
    return config.user_dir(ctx.uid()) / "creators"

_lock = threading.RLock()

DEFAULTS = {"name": "", "channel": "", "style": "bounce", "layout": "blur", "captions": True, "min_len": 15, "max_len": 60,
            "max_clips": 6, "min_score": 80, "auto_watch": False, "buffer_min": 20, "live_per_hour": 4, "ai_every_min": 3, "ai_only_on_spike": True, "auto_jump_pct": 60,
            "plan": "free", "decide_mode": "both", "must_clip_min": 0, "min_gap_min": 2,
            "game": "", "hook_text": "", "description_text": "",
            "trigger_words": "clip that, clip it",
            "autopost": False, "accounts": [], "post_min_score": 75, "post_gap_min": 45, "daily_cap": 6,
            "privacy": "public", "post_footer": "", "rate_per_1k": 0.0, "channels": {},
            "post_times": "",          # fixed times of day to post at, like "10:00, 14:30, 19:00"; empty = spread by the gap
            "caption_style": "hype",   # hype: hooks, emojis and a question for comments; clean: the same without emojis
            "cta_text": "",            # a line asking for a follow or comment, added to every post
            "yt_category": "20",       # YouTube category (20 = Gaming)
            "yt_notify": True,         # tell subscribers about each new Short
            "yt_early": True,          # upload scheduled Shorts early; YouTube makes them public at the time
            "yt_playlist": "",         # add every Short to this playlist (id or link)
            "yt_comment": "",          # first comment under every Short
            "auto_uploads": False,     # clip their new uploads by themselves (studio/autofetch.py)
            "uploads_max_min": 120,    # ...unless longer than this many minutes
            "brand_on": False,         # the page's logo (creators/<id>/logo.png) and a credit line on every clip
            "credit_text": "",         # like "Clip: @streamer"
            "brand_pos": "tl",         # corner: tl, tr, bl, br
            "auto_times": False,       # set the posting times from the hours that get the most views
            "ab_titles": False,        # YouTube: try a second title when a Short starts slow
            "recycle": False,          # post the best clips again after a while
            "recycle_after_days": 21,
            "ig_story": False,         # also share each Reel to the Instagram Story
            "fx_zoom": False, "fx_replay": False, "fx_sfx": False, "fx_emoji": False, "fx_voice": False,   # studio/fx.py
            "rotate": False,           # each clip to the next account in turn, instead of all of them
            "auto_compilation": False, "last_compilation": "",   # a weekly top-clips video (studio/compilation.py)
            "rotate_next": 0,
            "trend_tags": False,       # add today's most-used hashtags for their game (studio/trends.py)
            "audience": "india",       # india: Hinglish titles and captions; global: plain English (brain.AUDIENCE_RULES)
            "ig_collab": "",           # Instagram usernames invited as collaborators on each Reel (up to 3)
            "permission": "unknown",   # did the streamer allow clipping? unknown, asked, allowed, denied
            "permission_note": "",
            "only_with_permission": False,   # post only when permission is "allowed"
            "music_on": False,         # background music from your own library (studio/musiclib.py)
            "reaction_on": False,      # your reaction sticker on the big moment
            "auto_length": False,      # learn the clip length that gets the most views
            "music_check": False,      # hold clips that contain a known song (studio/musiccheck.py)
            "affiliate": "",           # "Label | link" lines added to YouTube and Facebook descriptions
            # Autopilot (studio/autopilot.py). On by default: the ones that only protect or reorder.
            "style_learn": True, "smart_queue": True, "reach_guard": True, "copyright_guard": True,
            "no_duplicates": True, "best_cover": True,
            "hook_test": False, "viral_boost": False, "fast_live": False, "series": False, "fill_slots": False,
            "en_subs": False, "formats": False,
            # The YouTube strategy (studio/ytstrategy.py)
            "yt_seo": True,            # titles, descriptions, tags and hashtags from the YouTube SEO strategy
            "always_tags": "",         # your own hashtags on every post of this creator, e.g. "#trending #viral #edit"
            "post_mode": "fixed",      # fixed: your times; strategy: the channel's best hours; instant: as soon as made
            "lang": "en"}    # the language this creator speaks: picks the speech model, for live recordings too
PLATFORMS = ("youtube", "twitch", "kick")


def clean_hook(v) -> str:
    """The big text a person typed for their clips: one line, as they wrote it (links and @names stay, a campaign
    may need them), and short enough to sit in the box on the video."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(v or "")).split())[:60]


def clean_description(v) -> str:
    """The description a person typed for their clips: as they wrote it, line breaks included, so a campaign's
    set text (links, @names, hashtags) is not changed. Control characters go, and it is cut at 2000 characters."""
    nl, cr, tab = chr(10), chr(13), chr(9)
    lines = ("".join(ch if ch.isprintable() or ch == tab else " " for ch in line).rstrip()
             for line in str(v or "").replace(cr + nl, nl).replace(cr, nl).split(nl))
    return nl.join(lines).strip()[:2000]


def clean_tags(v) -> str:
    """'#trending, viral #edit' -> '#trending #viral #edit' (letters, numbers and _ only, up to 10)."""
    raw = v if isinstance(v, list) else re.split(r"[\s,]+", str(v or ""))
    out = []
    for t in raw:
        t = re.sub(r"[^\w]", "", str(t).lstrip("#"), flags=re.UNICODE)[:40]
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return " ".join("#" + t for t in out[:10])


def clean_affiliate(v) -> str:
    """Up to 5 lines of "Label | https://link"."""
    out = []
    for line in str(v or "").splitlines():
        if "|" not in line:
            continue
        label, link = (x.strip() for x in line.split("|", 1))
        if not re.fullmatch(r"https://[^\s<>\"']{4,300}", link):
            raise ValueError(f"\"{link[:60]}\" is not a link. Each line: Label | https://...")
        out.append(f"{label[:60]} | {link}")
    return "\n".join(out[:5])


def clean_times(v) -> str:
    """Posting times typed as "10:00, 2:30pm, 19:00": checked, sorted, written back as 24-hour "HH:MM, HH:MM"."""
    out = set()
    for part in re.split(r"[,;\s]+(?![ap]m)", str(v or "").lower()):
        part = part.strip().replace(" ", "")
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?(am|pm)?", part)
        if not m:
            raise ValueError(f"\"{part}\" is not a time. Write times like 10:00, 14:30 or 7pm, separated by commas.")
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap:
            if not 1 <= h <= 12:
                raise ValueError(f"\"{part}\" is not a time.")
            h = h % 12 + (12 if ap == "pm" else 0)
        if h > 23 or mi > 59:
            raise ValueError(f"\"{part}\" is not a time.")
        out.add(f"{h:02d}:{mi:02d}")
    if len(out) > 24:
        raise ValueError("At most 24 posting times a day.")
    return ", ".join(sorted(out))


def times_of(c: dict) -> list:
    """The creator's posting times as (hour, minute) pairs, earliest first."""
    try:
        return [tuple(int(x) for x in t.split(":")) for t in clean_times(c.get("post_times", "")).split(", ") if t]
    except ValueError:
        return []


def platform_key(url: str) -> str:
    from urllib.parse import urlparse
    h = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return "youtube" if "youtube" in h or h == "youtu.be" else "twitch" if "twitch" in h else "kick" if "kick" in h else ""


def _fix(c: dict) -> dict:
    """One channel per platform in `channels`; `channel` is the one to record from and is always one of them."""
    ch = {k: v for k, v in (c.get("channels") or {}).items() if k in PLATFORMS and v}
    if c.get("channel") and platform_key(c["channel"]) and c["channel"] not in ch.values():
        ch.setdefault(platform_key(c["channel"]), c["channel"])
    c["channels"] = ch
    if not c.get("ai_every_min"):
        c["ai_every_min"] = 3       # "Auto" (0) is gone: jumps in loudness and chat are now always checked
    if c.get("channel") not in ch.values():
        c["channel"] = next((ch[k] for k in PLATFORMS if k in ch), "")
    return c
NUMERIC = {"min_len": (5, 120), "max_len": (10, 180), "max_clips": (1, 20), "min_score": (0, 100), "buffer_min": (5, 120), "live_per_hour": (1, 60), "ai_every_min": (1, 30), "auto_jump_pct": (20, 300), "must_clip_min": (0, 240), "min_gap_min": (0, 60),
           "post_min_score": (0, 100), "post_gap_min": (5, 1440), "daily_cap": (1, 50),
           "uploads_max_min": (5, 600), "recycle_after_days": (7, 180), "rotate_next": (0, 10000)}


def root(cid) -> Path:
    if not re.fullmatch(r"[\w\-]{1,60}", cid or ""):
        raise ValueError("bad creator id")
    return _root() / cid


def _clean(data: dict) -> dict:
    out = {}
    for k in DEFAULTS:
        if k == "captions":
            if k in data:
                if not isinstance(data[k], bool):
                    raise ValueError("Captions must be on or off.")
                out[k] = data[k]
            continue
        if k not in data or data[k] is None:
            continue
        v = data[k]
        if k in NUMERIC:
            lo, hi = NUMERIC[k]
            v = max(lo, min(hi, int(float(v))))
        elif k in ("auto_watch", "autopost", "ai_only_on_spike", "auto_uploads", "brand_on", "auto_times", "ab_titles",
                   "recycle", "ig_story", "fx_zoom", "fx_replay", "fx_sfx", "fx_emoji", "fx_voice", "rotate",
                   "auto_compilation", "trend_tags", "only_with_permission", "music_on", "reaction_on",
                   "auto_length", "music_check", "style_learn", "smart_queue", "reach_guard", "copyright_guard",
                   "no_duplicates", "best_cover", "hook_test", "viral_boost", "fast_live", "series", "fill_slots",
                   "en_subs", "formats", "yt_seo"):
            v = bool(v)
        elif k == "channels":
            v = {p: str(u).strip()[:300] for p, u in (v.items() if isinstance(v, dict) else []) if p in PLATFORMS and str(u).strip()}
        elif k == "accounts":
            v = [str(x) for x in v][:20] if isinstance(v, list) else []
        elif k == "hook_text":
            v = clean_hook(v)
        elif k == "description_text":
            v = clean_description(v)
        elif k == "rate_per_1k":
            v = max(0.0, min(1000.0, float(v or 0)))
        elif k == "plan":
            v = v if v in ("free", "pro", "max") else "free"
        elif k == "decide_mode":
            v = v if v in ("both", "either") else "both"
        elif k == "privacy":
            v = v if v in ("public", "unlisted", "private") else "public"
        elif k == "post_times":
            v = clean_times(v)
        elif k in ("yt_notify", "yt_early"):
            v = bool(v)
        elif k == "yt_category":
            from . import accounts
            v = str(v) if str(v) in accounts.YT_CATEGORIES else "20"
        elif k == "yt_playlist":
            from . import accounts
            v = str(v or "").strip()[:300]
            if v and not accounts.playlist_id(v):
                raise ValueError("That YouTube playlist link doesn't look right. Copy it from the playlist's page.")
        elif k == "credit_text":
            v = clean_hook(v)
        elif k == "always_tags":
            v = clean_tags(v)
        elif k == "post_mode":
            v = v if v in ("fixed", "strategy", "instant") else "fixed"
        elif k == "audience":
            v = v if v in ("india", "global") else "india"
        elif k == "ig_collab":
            names = [n.lstrip("@").lower() for n in re.split(r"[,\s]+", str(v or "")) if n.strip("@ ")]
            if any(not re.fullmatch(r"[\w.]{1,30}", n) for n in names):
                raise ValueError("Instagram usernames only have letters, numbers, dots and underscores.")
            v = ", ".join(names[:3])
        elif k == "permission":
            v = v if v in ("unknown", "asked", "allowed", "denied") else "unknown"
        elif k == "permission_note":
            v = clean_description(v)[:300]
        elif k == "affiliate":
            v = clean_affiliate(v)
        elif k == "brand_pos":
            v = v if v in ("tl", "tr", "bl", "br") else "tl"
        elif k == "yt_comment":
            v = clean_description(v)[:1000]
        elif k == "caption_style":
            v = v if v in ("hype", "clean") else "hype"
        elif k == "cta_text":
            v = clean_description(v)[:300]
        elif k == "lang":
            from . import fetch_model
            v = v if fetch_model.known(v) else "en"
        else:
            v = str(v).strip()[:300]
        out[k] = v
    return out


_mem: dict = {}   # user -> {creator id: creator}. The files stay the truth; this saves re-reading them on every page check.


def _mine() -> dict:
    u = ctx.uid()
    got = _mem.get(u)
    if got is None:
        got = {}
        for f in sorted(_root().glob("*/creator.json")):
            try:
                c = _fix({**DEFAULTS, **json.loads(f.read_text(encoding="utf-8"))})
                got[c.get("id") or f.parent.name] = c
            except Exception:  # noqa: BLE001
                pass
        with _lock:
            got = _mem.setdefault(u, got)
    return got


def forget(uid: str):
    """Files were changed from outside this module (old data moved in): read them again next time."""
    _mem.pop(uid, None)
    ctx.bump(uid)


def all_creators() -> list:
    return [copy.deepcopy(c) for c in list(_mine().values())]


def get(cid):
    if not cid or not re.fullmatch(r"[\w\-]{1,60}", str(cid)):
        return None
    c = _mine().get(str(cid))
    return copy.deepcopy(c) if c else None


def _write(c):
    with _lock:
        d = root(c["id"])
        for sub in ("videos", "live"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        tmp = d / "creator.json.tmp"
        tmp.write_text(json.dumps(c, indent=1), encoding="utf-8")
        tmp.replace(d / "creator.json")
        _mine()[c["id"]] = copy.deepcopy(c)
    ctx.bump()


def create(data: dict) -> dict:
    c = _fix({**DEFAULTS, **_clean(data)})
    if not c["name"]:
        raise ValueError("Give the creator a name.")
    slug = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-")[:40] or "creator"
    cid, n = slug, 2
    while root(cid).exists():
        cid, n = f"{slug}-{n}", n + 1
    c.update(id=cid, created=time.time())
    _write(c)
    log(cid, f"Workspace created for {c['name']}")
    return c


def update(cid, data: dict) -> dict:
    c = get(cid)
    if not c:
        raise KeyError(cid)
    new = _clean(data)
    if "channels" in new and "channel" not in new and c["channel"] not in new["channels"].values():
        c["channel"] = ""  # the recording channel was removed: fall back to another one
    if "channel" in new and new["channel"] and "channels" not in new:
        new["channels"] = {**c["channels"], platform_key(new["channel"]): new["channel"]}
    c.update(new)
    _fix(c)
    if new.get("post_mode") == "strategy":     # yt-plan: post when the channel's own numbers say
        c["auto_times"] = True
        if not c.get("post_times"):            # until there are enough views: the audience's prime-time plan
            from . import quickadd
            c["post_times"] = ", ".join(quickadd.plan(c.get("audience", "india"), max(1, min(5, int(c.get("daily_cap") or 3))))["times"])
    elif new.get("post_mode") == "fixed":
        c["auto_times"] = False
    if c["min_len"] >= c["max_len"]:
        raise ValueError("Shortest clip must be shorter than longest clip.")
    _write(c)
    return c


def set_profiles(cid, profiles: dict, extra: dict = None):
    """Each channel's public profile and live state, written by profiles.refresh. `profile` is the recording
    channel's one, used for the creator's picture."""
    with _lock:
        c = get(cid)
        if not c:
            return
        before = json.dumps([c.get("profiles"), {k: c.get(k) for k in (extra or {})}], sort_keys=True, default=str)
        c["profiles"] = {k: v for k, v in profiles.items() if k in c["channels"]}
        main = platform_key(c["channel"]) if c["channel"] else ""
        c["profile"] = c["profiles"].get(main) or next(iter(c["profiles"].values()), {})
        c.update(extra or {})
        same = re.sub(r'"live_at": [\d.]+', "", before) == re.sub(
            r'"live_at": [\d.]+', "", json.dumps([c["profiles"], {k: c.get(k) for k in (extra or {})}], sort_keys=True, default=str))
        if same:       # only "checked just now" moved on: remember it, but there is nothing new to save or show
            _mine()[c["id"]] = copy.deepcopy(c)
            return
        _write(c)


def log(cid, msg: str):
    if not cid or ctx.uid_or_none() is None or not root(cid).exists():
        return
    path = root(cid) / "log.jsonl"
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "msg": msg}) + "\n")
        try:
            if path.stat().st_size > LOG_MAX_BYTES:         # a stream that runs for weeks must not grow this for ever
                keep = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-LOG_KEEP_LINES:]
                path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass
    ctx.bump()


LOG_MAX_BYTES, LOG_KEEP_LINES, LOG_TAIL_BYTES = 1_000_000, 500, 64 * 1024


def read_log(cid, n=40) -> list:
    """The newest n lines, newest first. Only the end of the file is read: the page asks for this all the time."""
    f = root(cid) / "log.jsonl"
    try:
        size = f.stat().st_size
        with f.open("rb") as h:
            h.seek(max(0, size - LOG_TAIL_BYTES))
            raw = h.read()
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="ignore").splitlines()
    if size > LOG_TAIL_BYTES:
        lines = lines[1:]                                   # the first one starts in the middle of a line
    out = []
    for x in reversed(lines[-n:]):
        try:
            out.append(json.loads(x))
        except ValueError:
            pass
    return out
