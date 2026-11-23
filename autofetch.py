"""New uploads from a creator's channels, clipped by themselves.

With "Clip their new uploads" on, every 20 minutes Clip Cut AI looks at the creator's YouTube channel (its videos
and its past live streams) and Twitch channel (its past broadcasts). Anything new since the switch was turned on is
added as a video for that creator, so its clips are made, and posted too if the creator auto-posts. What was
already on the channel when it was switched on is left alone: only new uploads are clipped.

Seen videos are kept per creator in creators/<id>/uploads.json."""
import json
import threading
import re
import time

from . import alerts, auth, config, creators, ctx, jobs, media

EVERY = 20 * 60
PER_ROUND = 3              # at most this many new videos per creator per round
_lock = threading.RLock()


def _file(cid):
    return creators.root(cid) / "uploads.json"


def _state(cid) -> dict:
    try:
        d = json.loads(_file(cid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("seen", [])
    d.setdefault("since", 0)
    d.setdefault("last", 0)
    d.setdefault("problem", "")
    return d


def _save(cid, d):
    d["seen"] = d["seen"][-500:]
    f = _file(cid)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(f)


def feeds(c) -> list:
    """The list pages to read for this creator: YouTube videos and past streams, Twitch past broadcasts."""
    out = []
    for pf, url in (c.get("channels") or {}).items():
        u = url.rstrip("/")
        if pf == "youtube" and "/watch" not in u:
            base = u.split("/videos")[0].split("/streams")[0].split("/shorts")[0]
            out += [base + "/videos", base + "/streams"]
        elif pf == "twitch":
            out.append(u.split("/videos")[0] + "/videos?filter=archives&sort=time")
    return out


def list_feed(url: str, n: int = 10) -> list:
    """The newest videos on a channel page: [{id, url, title, duration, live}], newest first. Nothing is downloaded."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "logger": media._Quiet(), "extract_flat": "in_playlist",
            "playlistend": n, "socket_timeout": 20, **media.cookie_opts()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        i = ydl.extract_info(url, download=False)
    out = []
    for e in (i or {}).get("entries") or []:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        link = e.get("url") or e.get("webpage_url") or ""
        if link and not link.startswith("http"):
            link = f"https://www.youtube.com/watch?v={e['id']}"
        live = str(e.get("live_status") or "")
        out.append({"id": str(e["id"]), "url": link, "title": e.get("title") or "", "duration": float(e.get("duration") or 0),
                    "live": live in ("is_live", "is_upcoming", "post_live")})
    return out


LIST_LINK = re.compile(r"^https?://(www\.|m\.)?(youtube\.com/(@[\w.\-]+|c/[\w.\-]+|channel/[\w\-]+|user/[\w.\-]+)(/(videos|streams|shorts|featured|live)?)?/?(\?.*)?$"
                       r"|youtube\.com/playlist\?|twitch\.tv/[\w]+/?(videos/?)?(\?.*)?$|kick\.com/[\w\-]+/?(videos/?)?(\?.*)?$)", re.I)


def is_list_link(url: str) -> bool:
    """A channel, its videos/streams tab or a playlist: not one video."""
    return bool(LIST_LINK.match((url or "").strip()))


def newest_video(url: str) -> dict:
    """The newest finished video (not a live stream going on now) behind a channel or playlist link."""
    u = (url or "").strip().split("?")[0].rstrip("/")
    if "youtube.com" in u and not re.search(r"/(videos|streams|shorts)$", u) and "playlist" not in url:
        u = re.sub(r"/(featured|live)$", "", u) + "/videos"
    if "twitch.tv" in u and not u.endswith("/videos"):
        u += "/videos"
    if "playlist" in url:
        u = url
    for v in list_feed(u, 8):
        if not v.get("live") and v.get("url"):
            return v
    raise ValueError("No finished video found on that channel.")


def turned_on(cid):
    """The switch was just turned on: remember what is already there, so only later uploads are clipped."""
    def run():
        c = creators.get(cid)
        if not c:
            return
        d = _state(cid)
        d["since"] = time.time()
        for f in feeds(c):
            try:
                d["seen"] += [v["id"] for v in list_feed(f, 30) if v["id"] not in d["seen"]]
            except Exception as e:  # noqa: BLE001
                d["problem"] = f"Couldn't read {f}: {str(e)[-150:]}"
        d["last"] = time.time()
        _save(cid, d)
    threading.Thread(target=ctx.bind(run), daemon=True).start()


def check_creator(c) -> int:
    """Add this creator's new uploads as videos. Returns how many were added."""
    with _lock:
        d = _state(c["id"])
        if not d["since"]:                       # never set up (turned on by an older version): start from now
            d["since"] = time.time()
            for f in feeds(c):
                try:
                    d["seen"] += [v["id"] for v in list_feed(f, 30)]
                except Exception:  # noqa: BLE001
                    pass
            _save(c["id"], d)
            return 0
        added, problems = 0, []
        max_sec = int(c.get("uploads_max_min", 120)) * 60
        for f in feeds(c):
            if media.is_youtube(f) and media.youtube_paused():
                continue
            try:
                vids = list_feed(f)
            except Exception as e:  # noqa: BLE001
                problems.append(f"Couldn't read the channel: {str(e)[-120:]}")
                continue
            for v in reversed(vids):              # oldest new one first
                if v["id"] in d["seen"]:
                    continue
                if v["live"]:
                    continue                      # still live: the live recorder handles it; look again later
                d["seen"].append(v["id"])
                if (v["duration"] and v["duration"] > max_sec) or (v["duration"] and v["duration"] < 60):
                    creators.log(c["id"], f"New upload skipped ({int(v['duration'] // 60)} min): {v['title'][:80]}")
                    continue
                if added >= PER_ROUND or not v["url"]:
                    d["seen"].remove(v["id"])     # next round
                    continue
                job = jobs.create({"type": "url", "url": v["url"], "name": v["title"] or v["url"]}, {}, creator=c["id"])
                job.update(title=v["title"] or job["title"], duration=v["duration"])
                jobs.save(job)
                added += 1
                creators.log(c["id"], f"New upload found, making clips: {v['title'][:80]}")
        if added:
            alerts.notify(f"{c['name']}: {added} new upload{'s' if added > 1 else ''} found, making clips.")
        d.update(last=time.time(), problem=" ".join(problems)[:300])
        _save(c["id"], d)
        return added


def status(cid) -> dict:
    d = _state(cid)
    return {"since": d["since"], "last": d["last"], "problem": d["problem"]}


def _user(uid):
    with ctx.as_user(uid):
        for c in creators.all_creators():
            if c.get("auto_uploads") and feeds(c):
                try:
                    check_creator(c)
                except Exception as e:  # noqa: BLE001
                    creators.log(c["id"], f"Checking for new uploads failed: {str(e)[-150:]}")


def loop():
    time.sleep(90)
    while True:
        for uid in auth.user_ids():
            try:
                _user(uid)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(EVERY)


def start():
    if config.env("CLIPCUT_AUTO_UPLOADS", "1") != "0":
        threading.Thread(target=loop, daemon=True).start()
