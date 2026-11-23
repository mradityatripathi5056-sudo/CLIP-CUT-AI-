"""Backups of everything that is hard to make again: accounts and logins, creators and their settings, connected
apps, the post queue and calendar, AI settings, and the list of videos and clips with their titles and captions.
Video files are not included (they are big, and can be made again); the speech model is not either.

A backup is made by itself once a day while Clip Cut AI runs, and can be made by hand in Settings, Storage. The last
14 are kept in the "backups" folder inside the data folder. To put one back, close Clip Cut AI and run:

    python -m studio.backup restore backups/clipcut-2026-11-21.zip

Moving to another machine (like a cloud server)? Sign up there first, then give everything to that account:

    python -m studio.backup restore clipcut-2026-11-21.zip --to you@example.com

Before restoring, a backup of how things are now is made, so a restore can itself be undone."""
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import config

KEEP = 14
SKIP_DIRS = {"tmp", "fonts", "models", "backups", "lib", "live", "parts"}
KEEP_SUFFIXES = {".json", ".jsonl", ".key", ".txt"}
NAME = re.compile(r"clipcut-\d{4}-\d{2}-\d{2}(?:-\d{6})?\.zip")
_lock = threading.Lock()


def folder() -> Path:
    d = config.DATA_DIR / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _files():
    """Every small settings file in the data folder, as (path on disk, path in the backup)."""
    root = config.DATA_DIR
    for f in root.rglob("*"):
        rel = f.relative_to(root)
        if not f.is_file() or any(p in SKIP_DIRS for p in rel.parts[:-1]) or f.suffix.lower() not in KEEP_SUFFIXES:
            continue
        if f.name.endswith(".tmp") or f.stat().st_size > 20_000_000:
            continue
        yield f, rel.as_posix()


def _sqlite_copy(dest: Path) -> bool:
    """A consistent copy of the SQLite database, even while Clip Cut AI is using it."""
    if not config.DATABASE_URL.startswith("sqlite"):
        return False
    src = config.DATA_DIR / "clipcut.db"
    if not src.exists():
        return False
    with sqlite3.connect(str(src)) as a, sqlite3.connect(str(dest)) as b:
        a.backup(b)
    return True


def make(label: str = "") -> Path:
    """Make a backup now. Returns the file."""
    with _lock:
        day = time.strftime("%Y-%m-%d")
        name = f"clipcut-{day}{'-' + time.strftime('%H%M%S') if label else ''}.zip"
        out = folder() / name
        tmp = out.with_suffix(".part")
        with tempfile.TemporaryDirectory() as td:
            dbf = Path(td) / "clipcut.db"
            has_db = _sqlite_copy(dbf)
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for f, rel in _files():
                    try:
                        z.write(f, rel)
                    except OSError:
                        pass            # a file being written right now: it is in tomorrow's backup
                if has_db:
                    z.write(dbf, "clipcut.db")
                z.writestr("BACKUP.txt", f"Clip Cut AI backup made {time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                                         "Settings, accounts, creators, posts and the list of clips. No video files.\n")
        tmp.replace(out)
        _prune()
        return out


def _prune():
    files = sorted((f for f in folder().glob("clipcut-*.zip")), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[KEEP:]:
        f.unlink(missing_ok=True)


def listing() -> list:
    return [{"name": f.name, "size": f.stat().st_size, "made": int(f.stat().st_mtime)}
            for f in sorted(folder().glob("clipcut-*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)]


def path_of(name: str):
    """The backup file with this name, or None. Only names Clip Cut AI makes are accepted."""
    if not NAME.fullmatch(name or ""):
        return None
    f = folder() / name
    return f if f.is_file() else None


def daily_loop():
    """Once a day, a backup. The first one a few minutes after starting, so starting stays quick."""
    time.sleep(180)
    while True:
        try:
            if not (folder() / f"clipcut-{time.strftime('%Y-%m-%d')}.zip").exists():
                f = make()
                if time.localtime().tm_wday == 0:
                    _email_backup(f)
        except Exception as e:  # noqa: BLE001 - a failed backup must never stop Clip Cut AI
            print(f"  Backup failed: {e}", flush=True)
        time.sleep(3600)


def _email_backup(f: Path):
    """Mondays: the backup goes to the owner's email too, when they asked for that and email is set up."""
    from . import accounts, auth, ctx, mailsetup
    uid = auth.owner_id()
    u = auth.get_user(uid)
    if not u or not auth.EMAIL_RE.match(u.email or "") or f.stat().st_size > 20_000_000:
        return
    with ctx.as_user(uid):
        if not accounts.settings().get("backup_email"):
            return
    mailsetup.send_file(u.email, f"Clip Cut AI backup {time.strftime('%d %b %Y')}",
                        "Your weekly Clip Cut AI backup is attached: logins, creators, connected accounts, posts and "
                        "the list of clips (no videos). Keep this email. To put it back, see Settings, Storage.", f)


def start():
    if config.env("CLIPCUT_BACKUP", "1") != "0":
        threading.Thread(target=daily_loop, daemon=True).start()


def restore(zip_path: Path, owner: str = ""):
    """Put a backup back. Run only while Clip Cut AI is closed.

    owner: when moving to another machine (a cloud server), the id of the account there that should get
    everything. The backup's own database is then not used (the new machine has its own, with that account in it)."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        bad = [n for n in names if n.startswith("/") or ".." in Path(n).parts or "\\" in n]
        if bad:
            raise ValueError("That backup contains paths that are not allowed.")
        safety = make(label="before-restore")
        sqlite_here = config.DATABASE_URL.startswith("sqlite")
        for src_name in names:
            n = "clipcut.db" if src_name == config._OLD[:-1].lower() + ".db" else src_name   # a backup from an older copy
            if n == "BACKUP.txt" or n.endswith("/"):
                continue
            if n == "clipcut.db" and (owner or not sqlite_here):
                continue
            dest = config.DATA_DIR / n
            dest.parent.mkdir(parents=True, exist_ok=True)
            if n == "clipcut.db":
                for extra in ("clipcut.db-wal", "clipcut.db-shm"):
                    (config.DATA_DIR / extra).unlink(missing_ok=True)
            with z.open(src_name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        if owner:
            _hand_over({Path(n).parts[1] for n in names if n.startswith("users/") and len(Path(n).parts) > 2}, owner)
    return safety


def _hand_over(old_ids: set, owner: str):
    """Everything the backup's account(s) had now belongs to `owner`: their folders are joined into the owner's,
    and the post queue says so."""
    import json
    users = config.DATA_DIR / "users"
    for old in old_ids - {owner}:
        src = users / old
        if not src.is_dir():
            continue
        dst = users / owner
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            target = dst / item.relative_to(src)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(target))
        shutil.rmtree(src, ignore_errors=True)
    f = config.DATA_DIR / "posts.json"
    if f.exists():
        try:
            posts = json.loads(f.read_text(encoding="utf-8"))
            for p in posts:
                if p.get("user") in old_ids:
                    p["user"] = owner
            f.write_text(json.dumps(posts, indent=1), encoding="utf-8")
        except ValueError:
            pass
    for jf in (config.DATA_DIR / "users" / owner).rglob("job.json"):
        try:
            j = json.loads(jf.read_text(encoding="utf-8"))
            if j.get("user") in old_ids:
                j["user"] = owner
                jf.write_text(json.dumps(j, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("-y", "--yes")]
    sure = len(args) != len(sys.argv[1:])           # -y: no question (for scripts, where nobody can type)
    if args[:1] == ["make"]:
        print("Backup made:", make(label="by-hand"))
    elif len(args) in (2, 4) and args[0] == "restore" and (len(args) == 2 or args[2] == "--to"):
        owner = ""
        if len(args) == 4:
            from . import auth, db
            db.init()
            with db.engine.connect() as c:
                row = c.execute(auth.sa.select(db.users.c.id).where(db.users.c.email == args[3].strip().lower())).first()
            if not row:
                sys.exit(f"No account with the email {args[3]} here. Sign up with it first, then run this again.")
            owner = row[0]
        p = Path(args[1])
        if not p.is_file():
            p = folder() / args[1]
        if not p.is_file():
            sys.exit(f"No backup file at {args[1]}.")
        if not sure and input(f"Close Clip Cut AI first. Put back {p.name}? Type yes: ").strip().lower() != "yes":
            sys.exit("Nothing was changed.")
        safe = restore(p, owner)
        print(f"Restored. How things were just before is saved as {safe.name}, in case you want it back.")
    else:
        print(__doc__)
