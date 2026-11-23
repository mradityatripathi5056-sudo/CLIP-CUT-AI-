"""A login that keeps everything, daily backups, and the YouTube extras (category, telling subscribers, YouTube
publishing scheduled Shorts by itself, playlist, first comment). Runs against the code directly with its own empty
data folder; nothing leaves this machine."""
import json
import os
import sys
import tempfile
import time
import zipfile

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-extras-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="0", CLIPCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import accounts, auth, backup, config, creators, ctx, db, jobs, posting, server  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
H = {"Origin": "http://127.0.0.1:8765"}
me = auth.local_user()
with ctx.as_user(me.id):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "GameXtra", "added": time.time(),
                   "access_token": "yt", "refresh_token": "r", "expires": time.time() + 3600})
    cr = creators.create({"name": "Pro", "yt_playlist": "https://www.youtube.com/playlist?list=PLabcdefghijklmnop",
                          "yt_comment": "Who wins? 👇", "yt_category": "24", "yt_notify": False})
    job = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=cr["id"])
    (jobs.job_dir(job["id"]) / "clips").mkdir(parents=True, exist_ok=True)
    (jobs.job_dir(job["id"]) / "clips" / "c1.mp4").write_bytes(b"\0" * 1000)
    clip = {"id": "c1", "status": "done", "file": "c1.mp4", "title": "Clutch 🔥", "description": "Wait for it 😱",
            "hashtags": ["gaming"], "score": 90}
    job["clips"].append(clip)
    jobs.save(job)

# ---- a login that keeps everything
r = cl.get("/api/owner-login")
check("no login is set at first", r.status_code == 200 and r.json()["ready"] is False, r.text)
r = cl.put("/api/owner-login", json={"email": "aditya@example.com", "password": "longpassword", "again": "different1"}, headers=H)
check("two different passwords are refused", r.status_code == 400 and "not the same" in r.text, r.text)
r = cl.put("/api/owner-login", json={"email": "aditya@example.com", "password": "short", "again": "short"}, headers=H)
check("a short password is refused", r.status_code == 400, r.text)
r = cl.put("/api/owner-login", json={"email": "aditya@example.com", "password": "longpassword", "again": "longpassword", "name": "Aditya"}, headers=H)
check("a login is saved", r.status_code == 200 and r.json()["email"] == "aditya@example.com", r.text)
check("a login change from another website is refused",
      cl.put("/api/owner-login", json={"email": "x@example.com", "password": "longpassword", "again": "longpassword"},
             headers={"Origin": "https://evil.example"}).status_code == 403)
u = auth.login("aditya@example.com", "longpassword")
check("signing in with it opens the same account that holds everything", u.id == me.id and u.is_admin)
with ctx.as_user(u.id):
    check("...with the creators, clips and connected accounts still in it",
          bool(creators.get(cr["id"])) and bool(jobs.get(job["id"])) and bool(accounts.get("yt_1")))
check("the page shows the login is ready", cl.get("/api/owner-login").json() == {"ready": True, "email": "aditya@example.com", "accounts_on": False})
other, _ = auth._create("anshik@example.com", "Anshik", password_hash="x")
try:
    auth.set_owner_login("anshik@example.com", "longpassword")
    check("an email another account uses is refused", False)
except auth.AuthError:
    check("an email another account uses is refused", True)
check("the owner stays the oldest account, even with others", auth.owner_id() == me.id)
me = auth.local_user()

# ---- backups
f = backup.make()
names = zipfile.ZipFile(f).namelist()
check("a backup holds the database, the post queue and each creator", "clipcut.db" in names
      and any(n.endswith("creator.json") for n in names) and any(n.endswith("accounts.json") for n in names), str(names))
check("...and the list of clips", any(n.endswith("job.json") for n in names))
check("...but no video files", not any(n.endswith(".mp4") for n in names))
r = cl.get("/api/backups")
check("backups are listed in Settings", r.status_code == 200 and r.json()["backups"][0]["name"] == f.name, r.text)
check("one can be downloaded", cl.get(f"/api/backups/{f.name}").status_code == 200)
check("only backup files can be downloaded", cl.get("/api/backups/..%2Fclipcut.db").status_code == 404
      and cl.get("/api/backups/secrets.zip").status_code == 404)
r = cl.post("/api/backups", headers=H)
check("a backup can be made by hand", r.status_code == 200 and len(r.json()["backups"]) == 2, r.text)
for i in range(20):
    (backup.folder() / f"clipcut-2020-01-{i + 1:02d}.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    os.utime(backup.folder() / f"clipcut-2020-01-{i + 1:02d}.zip", (1_600_000_000 + i, 1_600_000_000 + i))
backup._prune()
check("only the last 14 are kept", len(backup.listing()) == 14)
with ctx.as_user(me.id):
    cj = creators.root(cr["id"]) / "creator.json"
good = cj.read_text(encoding="utf-8")
cj.write_text("{broken", encoding="utf-8")
safety = backup.restore(f)
check("a broken file is put back from a backup", cj.read_text(encoding="utf-8") == good)
check("...after saving how things were first", safety.exists() and safety != f)

# ---- YouTube
check("a playlist link gives its id", accounts.playlist_id("https://www.youtube.com/playlist?list=PLabcdefghijklmnop") == "PLabcdefghijklmnop")
with ctx.as_user(me.id):
    try:
        creators.update(cr["id"], {"yt_playlist": "not a playlist!"})
        check("a playlist link that is not one is refused", False)
    except ValueError:
        check("a playlist link that is not one is refused", True)
    check("an unknown category falls back to Gaming", creators.update(cr["id"], {"yt_category": "999"})["yt_category"] == "20")
    creators.update(cr["id"], {"yt_category": "24"})


class R:
    def __init__(self, code, data=None, headers=None):
        self.status_code, self._d, self.headers, self.text = code, data, headers or {}, json.dumps(data)

    def json(self):
        return self._d


sent = []


def post(url, params=None, json=None, headers=None, timeout=None, data=None):
    sent.append(("POST", url, params, json))
    if url.endswith("/upload/youtube/v3/videos"):
        return R(200, {}, {"Location": "https://upload.example/session"})
    if url.endswith("/playlistItems"):
        return R(200, {"id": "pi"})
    if url.endswith("/commentThreads"):
        return R(403, {"error": {"message": "Request had insufficient authentication scopes."}}) if sent_scope_fail[0] else R(200, {"id": "ct"})
    return R(404, {})


def put(url, content=None, headers=None, timeout=None):
    return R(200, {"id": "vid123"})


sent_scope_fail = [False]
accounts.httpx.post, accounts.httpx.put = post, put

with ctx.as_user(me.id):
    acc = accounts.get("yt_1")
    accounts.youtube_upload(acc, jobs.job_dir(job["id"]) / "clips" / "c1.mp4", "T", "D", [], "public",
                            category="24", notify=False, publish_at=time.time() + 7200)
    meta = next(x for x in sent if x[1].endswith("/videos"))
    check("a scheduled Short goes up private, with YouTube's own publish time",
          meta[3]["status"]["privacyStatus"] == "private" and meta[3]["status"]["publishAt"].endswith("Z"), str(meta[3]["status"]))
    check("...in the creator's category, without telling subscribers", meta[3]["snippet"]["categoryId"] == "24" and meta[2]["notifySubscribers"] == "false")
    sent.clear()
    accounts.youtube_upload(acc, jobs.job_dir(job["id"]) / "clips" / "c1.mp4", "T", "D", [], "public")
    meta = next(x for x in sent if x[1].endswith("/videos"))
    check("a Short posted now is public straight away", meta[3]["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False})

    sent.clear()
    p = posting.enqueue(job, clip, ["yt_1"], at=time.time() + 3 * 3600)[0]
    check("a Short due in 3 hours can be uploaded now", posting._early(p))
    creators.update(cr["id"], {"yt_early": False})
    check("...unless the creator turned that off", not posting._early(p))
    creators.update(cr["id"], {"yt_early": True})
    p["status"] = "posting"
    posting._post(p)
    check("uploaded early: it counts as posted at its time, and YouTube publishes it then",
          p["status"] == "posted" and p["publish_at"] == p["due_at"] and p["posted_at"] == p["due_at"], str(p))
    check("added to the playlist straight away", any(x[1].endswith("/playlistItems") and x[3]["snippet"]["playlistId"] == "PLabcdefghijklmnop" for x in sent))
    check("the first comment waits until the Short is public", not any(x[1].endswith("/commentThreads") for x in sent) and p["comment_due"] >= p["due_at"])
    posting._comment(p)
    check("then the first comment is posted", any(x[1].endswith("/commentThreads") and x[3]["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Who wins? 👇" for x in sent))
    check("...once only", "comment_due" not in p and "comment" not in p)

    sent_scope_fail[0] = True
    p2 = posting.enqueue(job, dict(clip, id="c2"), ["yt_1"], now=True)
    job["clips"].append(dict(clip, id="c2"))
    jobs.save(job)
    p2 = p2[0]
    p2["status"] = "posting"
    posting._post(p2)
    posting._comment(p2)
    check("an old YouTube sign-in without comment permission: posted anyway, with a note on what to do",
          p2["status"] == "posted" and "connect YouTube again" in p2.get("note", ""), str(p2.get("note")))
    cal = posting.calendar(time.time() - 86400, time.time() + 86400)
    check("the calendar says when YouTube makes it public", any(x.get("publish_at") for x in cal))

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402
db.engine.dispose()
shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
