"""Your links (gear, game top-ups, sponsor codes) under YouTube and Facebook posts, each through a short link of
this app (/go/<code>) that counts the clicks, and your link-in-bio page (/c/<name>) with your latest clips."""
import hashlib
import html
import json
import re
import threading
import time

from . import config, ctx

_lock = threading.Lock()


def _file():
    return config.DATA_DIR / "golinks.json"


def _all() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(_file())


def lines(creator) -> list:
    out = []
    for line in str(creator.get("affiliate") or "").splitlines():
        if "|" in line:
            label, url = (x.strip() for x in line.split("|", 1))
            out.append((label, url))
    return out


def code_for(uid, cid, label, url) -> str:
    code = hashlib.sha256(f"{uid}|{cid}|{url}".encode()).hexdigest()[:9]
    with _lock:
        d = _all()
        if code not in d:
            d[code] = {"uid": uid, "cid": cid, "label": label, "url": url, "clicks": 0, "days": {}}
            _save(d)
        elif d[code]["label"] != label:
            d[code]["label"] = label
            _save(d)
    return code


def link(cid, label, url) -> str:
    if not (config.PUBLIC_URL or "").startswith("https://"):
        return url                     # nobody outside can reach this computer: post the real link
    return f"{config.PUBLIC_URL}/go/{code_for(ctx.uid(), cid, label, url)}"


def block(creator) -> str:
    ls = lines(creator)
    if not ls:
        return ""
    return "🔗 Links:\n" + "\n".join(f"{label}: {link(creator['id'], label, url)}" for label, url in ls)


def click(code: str):
    """The real link for a short code, counting the click. None for an unknown code."""
    if not re.fullmatch(r"[0-9a-f]{9}", code or ""):
        return None
    with _lock:
        d = _all()
        e = d.get(code)
        if not e:
            return None
        e["clicks"] += 1
        day = time.strftime("%Y-%m-%d")
        e["days"][day] = e["days"].get(day, 0) + 1
        e["days"] = dict(sorted(e["days"].items())[-60:])
        _save(d)
        return e["url"]


def stats() -> list:
    uid = ctx.uid()
    week = {time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400)) for i in range(7)}
    return sorted(({"code": k, "creator": v["cid"], "label": v["label"], "url": v["url"], "clicks": v["clicks"],
                    "week": sum(n for d, n in v["days"].items() if d in week)}
                   for k, v in _all().items() if v["uid"] == uid), key=lambda x: -x["clicks"])


# ------------------------------------------------------------------ link-in-bio page
def _pages_file():
    return config.DATA_DIR / "biopages.json"


def bio_pages() -> dict:
    try:
        return json.loads(_pages_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_bio(slug: str, title: str, about: str):
    slug = (slug or "").strip().lower()
    if slug and not re.fullmatch(r"[a-z0-9][a-z0-9_\-]{2,29}", slug):
        raise ValueError("Use 3 to 30 letters, numbers, - or _ for your page name.")
    uid = ctx.uid()
    with _lock:
        d = bio_pages()
        if slug and slug in d and d[slug]["uid"] != uid:
            raise ValueError("That page name is taken. Try another.")
        d = {k: v for k, v in d.items() if v["uid"] != uid}
        if slug:
            d[slug] = {"uid": uid, "title": str(title or "")[:60], "about": str(about or "")[:200]}
        tmp = _pages_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(_pages_file())
    return my_bio()


def my_bio() -> dict:
    uid = ctx.uid()
    for k, v in bio_pages().items():
        if v["uid"] == uid:
            return {"slug": k, "title": v["title"], "about": v["about"], "url": f"{config.PUBLIC_URL or ''}/c/{k}"}
    return {"slug": "", "title": "", "about": "", "url": ""}


def bio_html(slug: str):
    """The public page, or None. Only posted clips (their public links), your links and page names are shown."""
    e = bio_pages().get((slug or "").lower())
    if not e:
        return None
    from . import accounts, creators, posting
    with ctx.as_user(e["uid"]):
        posts = [p for p in posting._mine() if p.get("status") == "posted" and p.get("url")]
        posts.sort(key=lambda p: -(p.get("posted_at") or 0))
        seen, recent = set(), []
        for p in posts:
            if p["clip"] in seen:
                continue
            seen.add(p["clip"])
            recent.append(p)
            if len(recent) >= 12:
                break
        links = [(label, link(c["id"], label, url)) for c in creators.all_creators() for label, url in lines(c)]
        pages = [(a["label"], a["name"]) for a in accounts.list_accounts()]
    esc = html.escape
    li = "".join(f'<a class="b" href="{esc(u)}" rel="nofollow noopener">{esc(lbl)}</a>' for lbl, u in links[:10])
    cl = "".join(f'<a class="c" href="{esc(p["url"])}" rel="noopener"><b>{esc(p.get("title") or "Clip")}</b>'
                 f'<span>{esc(p.get("account_name", ""))}</span></a>' for p in recent)
    pg = " · ".join(esc(f"{k} {n}") for k, n in pages)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(e['title'] or slug)}</title><style>
body{{margin:0;font:16px/1.45 system-ui,sans-serif;background:#0d0f14;color:#eef0f4}}main{{max-width:520px;margin:0 auto;padding:32px 18px}}
h1{{font-size:26px;margin:0 0 6px}}p{{color:#a9afbd;margin:0 0 22px}}.b{{display:block;text-align:center;padding:14px;margin:0 0 10px;
border:1px solid #2a3040;border-radius:10px;color:#fff;text-decoration:none;font-weight:600;background:#161a23}}
h2{{font-size:15px;color:#a9afbd;margin:26px 0 10px;text-transform:uppercase;letter-spacing:.06em}}.c{{display:flex;justify-content:space-between;
gap:10px;padding:12px 0;border-bottom:1px solid #222736;color:#eef0f4;text-decoration:none}}.c span{{color:#7d8496;font-size:13px;white-space:nowrap}}
small{{display:block;margin-top:28px;color:#6b7284;font-size:12px}}</style></head><body><main>
<h1>{esc(e['title'] or slug)}</h1><p>{esc(e['about'])}</p>{li}<h2>Latest clips</h2>{cl or '<p>New clips soon.</p>'}
<small>{pg}</small></main></body></html>"""
