"""The weekly compilation: a creator's best clips of the last days joined into one 16:9 video for YouTube, best
last, each with a "#5" card in front, plus a thumbnail and chapters in the description.

It is saved as a video of that creator with one clip (marked long), so it shows in All videos and is posted from
the clip editor like any other clip. On YouTube it goes up as a normal video, not a Short, with its thumbnail.
Long videos are what YouTube's Partner Programme counts watch hours from."""
import shutil
import tempfile
import threading
import time
from pathlib import Path

from . import alerts, config, creators, ctx, jobs, posting
from .media import run

W, H = 1920, 1080
CARD_SEC = 1.6


def pick(cid: str, days: int = 7, count: int = 10) -> list:
    """[(job, clip)] of the creator's best finished clips from the last days: by views where posted, else score."""
    since = time.time() - days * 86400
    views = {}
    for p in posting._mine():
        if p.get("creator") == cid and p["status"] == "posted":
            k = (p["job"], p["clip"])
            views[k] = max(views.get(k, 0), p.get("views") or 0)
    found = []
    for j in jobs.list_jobs():
        if j.get("creator") != cid or j.get("source", {}).get("type") == "compilation":
            continue
        for c in j["clips"]:
            made = c.get("made_at") or j.get("created") or 0
            f = Path(j["dir"]) / "clips" / (c.get("file") or "")
            if c.get("status") == "done" and made >= since and c.get("file") and f.is_file() and not c.get("long"):
                found.append((views.get((j["id"], c["id"]), 0), c.get("score", 0), j, c))
    found.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(j, c) for _v, _s, j, c in found[:count]]


def _font(work: Path) -> str:
    for f in sorted(config.FONTS_DIR.glob("Anton*.ttf")) + sorted(config.FONTS_DIR.glob("*.ttf")):
        shutil.copyfile(f, work / "font.ttf")
        return "font.ttf"
    return ""


def _esc(t: str) -> str:
    """Text for ffmpeg's drawtext: no characters that end or break the filter."""
    t = "".join(ch for ch in t if ch.isprintable() and ord(ch) < 0x2000)
    return t.replace("\\", " ").replace("'", "’").replace(":", " -").replace("%", " pct").replace(",", " ")[:60]


def _segment(work: Path, i: int, rank: int, title: str, src: Path, font: str) -> Path:
    """A "#rank" card, then the vertical clip in the middle of a blurred copy of itself, all 1920x1080."""
    out = work / f"s{i:02d}.mp4"
    txt = (f"drawtext=fontfile={font}:text='#{rank}':fontsize=260:fontcolor=0xFF8B33:x=(w-tw)/2:y=h*0.22,"
           f"drawtext=fontfile={font}:text='{_esc(title)}':fontsize=72:fontcolor=white:x=(w-tw)/2:y=h*0.62") if font else "null"
    fc = (f"color=c=0x1E1612:s={W}x{H}:d={CARD_SEC}:r=30,{txt},format=yuv420p,setsar=1[cv];"
          f"anullsrc=r=48000:cl=stereo,atrim=0:{CARD_SEC}[ca];"
          f"[0:v]fps=30,split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,"
          f"eq=brightness=-0.18[bg];[b]scale=-2:{H}[fg];[bg][fg]overlay=(W-w)/2:0,format=yuv420p,setsar=1[vv];"
          f"[0:a]aresample=48000,aformat=channel_layouts=stereo[va];"
          f"[cv][ca][vv][va]concat=n=2:v=1:a=1[v][au]")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-map", "[au]",
         "-c:v", "libx264", "-crf", "21", "-preset", "veryfast", "-r", "30", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", out.name], cwd=work, timeout=1800)
    return out


def _duration(f: Path) -> float:
    try:
        return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _thumb(cover: Path, out: Path, line1: str, line2: str):
    """A 1280x720 thumbnail: the best clip's cover on a blurred copy, with big text."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    base = Image.new("RGB", (1280, 720), (30, 22, 18))
    try:
        im = Image.open(cover).convert("RGB")
        bg = im.resize((1280, int(1280 * im.height / im.width))).filter(ImageFilter.GaussianBlur(18))
        base.paste(bg, (0, (720 - bg.height) // 2))
        fg = im.resize((int(720 * im.width / im.height), 720))
        base.paste(fg, (1280 - fg.width - 40, 0))
    except Exception:  # noqa: BLE001
        pass
    d = ImageDraw.Draw(base)
    fonts = sorted(config.FONTS_DIR.glob("Anton*.ttf"))
    big = ImageFont.truetype(str(fonts[0]), 150) if fonts else ImageFont.load_default()
    small = ImageFont.truetype(str(fonts[0]), 78) if fonts else ImageFont.load_default()
    for (txt, font, y, fill) in ((line1, big, 150, (255, 139, 51)), (line2, small, 330, (255, 255, 255))):
        d.text((60, y), txt, font=font, fill=fill, stroke_width=8, stroke_fill=(0, 0, 0))
    base.save(out, "JPEG", quality=90)


def make(cid: str, days: int = 7, count: int = 10, log=print) -> dict:
    """Make the compilation now. Returns the new video (job)."""
    c = creators.get(cid)
    if not c:
        raise ValueError("No such creator.")
    chosen = pick(cid, days, count)
    if len(chosen) < 3:
        raise ValueError(f"Only {len(chosen)} finished clip{'s' if len(chosen) != 1 else ''} from the last {days} days. A compilation needs at least 3.")
    n = len(chosen)
    title = f"Top {n} {c['name']} moments this week 🔥"
    job = jobs.create({"type": "compilation", "name": title}, {}, enqueue=False, creator=cid)
    job.update(status="running", stage="Making the compilation", title=title, uploader=c["name"])
    jobs.save(job)
    work = Path(tempfile.mkdtemp(prefix="cmp"))
    try:
        font = _font(work)
        parts, chapters, at = [], [], 0.0
        for i, (j, k) in enumerate(reversed(chosen)):      # the best one last
            rank = n - i
            src = Path(j["dir"]) / "clips" / k["file"]
            seg = _segment(work, i, rank, k.get("title") or k.get("hook") or "", src, font)
            parts.append(seg)
            chapters.append(f"{int(at // 60)}:{int(at % 60):02d} #{rank} {k.get('title') or k.get('hook') or 'Clip'}")
            at += _duration(seg)
            job.update(progress=round((i + 1) / n * 0.9, 2), stage=f"Joining clip {i + 1} of {n}")
            jobs.save(job)
        (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        out_dir = Path(job["dir"]) / "clips"
        out_dir.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
             "-movflags", "+faststart", "comp.mp4"], cwd=work, timeout=1800)
        shutil.move(str(work / "comp.mp4"), str(out_dir / "comp.mp4"))
        best_j, best_c = chosen[0]
        _thumb(Path(best_j["dir"]) / "clips" / (best_c.get("cover") or ""), out_dir / "comp.jpg",
               f"TOP {n}", f"{c['name'][:22].upper()} MOMENTS")
        desc = (f"The best {c['name']} moments of the week, counted down. Which one was your favourite? 👇\n\n"
                + "\n".join(chapters))
        tags = list(dict.fromkeys(t for _j, k in chosen for t in (k.get("hashtags") or [])))[:8]
        clip = {"id": "comp", "status": "done", "file": "comp.mp4", "cover": "comp.jpg", "title": title[:100],
                "hook": f"TOP {n}", "description": desc, "hashtags": tags, "score": 100, "category": "other",
                "start": 0.0, "end": round(at, 2), "long": True, "version": 1, "made_at": time.time(),
                "fixed_description": True, "reason": "Weekly compilation."}
        job.update(clips=[clip], status="done", stage="Done", progress=1.0, duration=round(at, 2), thumb=False)
        jobs.save(job)
        creators.log(cid, f"Weekly compilation ready: {title}")
        alerts.notify(f"{c['name']}: weekly compilation ready ({n} clips, {int(at // 60)} min).", kind="clip")
        return job
    except Exception as e:
        job.update(status="error", error=f"The compilation could not be made: {str(e)[-200:]}")
        jobs.save(job)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def make_in_background(cid: str, days: int = 7, count: int = 10):
    def go():
        try:
            make(cid, days, count)
        except Exception as e:  # noqa: BLE001
            creators.log(cid, f"Weekly compilation not made: {str(e)[:200]}")
    threading.Thread(target=ctx.bind(go), daemon=True).start()


def weekly():
    """Sunday evening: a compilation for each creator who asked for one every week."""
    lt = time.localtime()
    if lt.tm_wday != 6 or lt.tm_hour < 18:
        return
    week = time.strftime("%Y-W%W")
    for c in creators.all_creators():
        if c.get("auto_compilation") and c.get("last_compilation") != week:
            creators.update(c["id"], {"last_compilation": week})
            try:
                make(c["id"])
            except Exception as e:  # noqa: BLE001
                creators.log(c["id"], f"Weekly compilation not made: {str(e)[:200]}")
