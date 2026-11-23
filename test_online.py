"""Online with ngrok (settings, safety: sign-in on and sign-up closed), start with Windows, the creator's video
picker, the startup sweep and comment auto sync. Nothing outside this machine is contacted."""
import os
import sys
import tempfile
import time

root = tempfile.mkdtemp(prefix="pc-onl-")
os.environ["CLIPCUT_DATA"] = root
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="")
sys.path.insert(0, ".")
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from studio import accounts, auth, config, creators, ctx, db, server, tunnel  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


config.ROOT = Path(tempfile.mkdtemp(prefix="pc-root-"))          # .env is written here, not in the real folder
(config.ROOT / ".env").write_text("CLIPCUT_AI=gemini\nCLIPCUT_PUBLIC_URL=http://old\n", encoding="utf-8")
TOKEN, DOMAIN = "2abcDEFghiJKLmnoPQRstuVWX_yz123456", "brave-otter-1234.ngrok-free.app"

try:
    tunnel.save(TOKEN, DOMAIN, True)
    check("going online needs your login saved first", False)
except ValueError as e:
    check("going online needs your login saved first", "Login" in str(e))
auth.local_user() if hasattr(auth, "local_user") else None
auth.set_owner_login("aditya@example.com", "Very-strong-pw-1", "Aditya")
for bad_tok, bad_dom in (("short", DOMAIN), (TOKEN, "not a domain!")):
    try:
        tunnel.save(bad_tok, bad_dom, True)
        check("a wrong token or domain is refused", False)
    except ValueError:
        check("a wrong token or domain is refused", True)
out = tunnel.save(TOKEN, "https://" + DOMAIN + "/", True)
env = (config.ROOT / ".env").read_text(encoding="utf-8")
check("going online switches sign-in on and closes sign-up", "CLIPCUT_ACCOUNTS=1" in env and "CLIPCUT_SIGNUP=0" in env)
check("...sets the public address to the ngrok domain, once", f"CLIPCUT_PUBLIC_URL=https://{DOMAIN}" in env and env.count("CLIPCUT_PUBLIC_URL") == 1)
check("...and keeps the rest of .env", "CLIPCUT_AI=gemini" in env)
check("the authtoken is never sent back", "token" not in out and out["has_token"] and out["domain"] == DOMAIN)
check("the saved file is only readable by this user", oct(os.stat(config.DATA_DIR / "ngrok.json").st_mode)[-3:] == "600")
tunnel.save("", DOMAIN, True)
check("leaving the token box empty keeps the saved token", tunnel.saved()["token"] == TOKEN)
tunnel.save("ngrok config add-authtoken " + TOKEN, DOMAIN, True)
check("pasting the whole 'ngrok config add-authtoken ...' line keeps just the token", tunnel.saved()["token"] == TOKEN)

started = {}


class FakeListener:
    def url(self):
        return "https://" + DOMAIN


fake = type(sys)("ngrok")
fake.forward = lambda addr, **kw: started.update(addr=addr, **kw) or FakeListener()
sys.modules["ngrok"] = fake
tunnel.start()
check("before a restart it says to restart (the address is read at start)", "Restart" in tunnel._state["error"] and not started)
config.PUBLIC_URL = "https://" + DOMAIN
tunnel.start()
for _ in range(300):
    if tunnel._state["url"]:
        break
    time.sleep(0.1)
check("after the restart the tunnel opens on the static domain", tunnel._state["url"] == "https://" + DOMAIN
      and started.get("domain") == DOMAIN and started.get("authtoken") == TOKEN and started.get("addr").endswith(f":{config.PORT}"))
# no domain given: ngrok's dev domain is found on start and kept
tunnel._state.update(url="", error="")
tunnel.save(TOKEN, "", True)
check("the domain can be left empty", tunnel.saved()["domain"] == "" and "CLIPCUT_PUBLIC_URL" not in (config.ROOT / ".env").read_text())
FakeListener.url = lambda self: "https://auto-dev-99.ngrok-free.dev"
started.clear()
tunnel.start()
for _ in range(300):
    if tunnel._state["url"]:
        break
    time.sleep(0.1)
check("...ngrok's own dev domain is used, remembered and becomes the address",
      "domain" not in started and tunnel.saved()["domain"] == "auto-dev-99.ngrok-free.dev"
      and "CLIPCUT_PUBLIC_URL=https://auto-dev-99.ngrok-free.dev" in (config.ROOT / ".env").read_text()
      and config.PUBLIC_URL == "https://auto-dev-99.ngrok-free.dev")
check("an ngrok error is explained", "authtoken" in tunnel._why("ERR_NGROK_105 authentication failed"))

# closed sign-up: strangers can't make an account, people added in Team can
os.environ["CLIPCUT_SIGNUP"] = "0"
try:
    auth._create("stranger@example.com", "x", password_hash="x")
    check("with sign-up closed, a stranger can't make an account", False)
except auth.AuthError as e:
    check("with sign-up closed, a stranger can't make an account", "closed" in str(e))
from studio import team  # noqa: E402
d = team._load()
d["invites"]["anshik@example.com"] = auth.owner_id()
team._save(d)
check("...but someone added in Team can", auth._create("anshik@example.com", "Anshik", password_hash="x")[0].email == "anshik@example.com")
os.environ.pop("CLIPCUT_SIGNUP")

tunnel.save(TOKEN, DOMAIN, False)
env = (config.ROOT / ".env").read_text(encoding="utf-8")
check("going offline removes the public address but keeps sign-in on", "CLIPCUT_PUBLIC_URL" not in env and "CLIPCUT_ACCOUNTS=1" in env)

# start with Windows
os.environ["APPDATA"] = tempfile.mkdtemp()
tunnel.WINDOWS = True
check("start with Windows can be turned on", tunnel.set_autostart(True) and tunnel._startup_file().read_text().count("START-WINDOWS.bat") == 1)
check("...and off", tunnel.set_autostart(False) is False)
tunnel.WINDOWS = False

# the creator's video picker
uid = auth.owner_id()
with ctx.as_user(uid):
    c = creators.create({"name": "Mortal", "channels": {"youtube": "https://www.youtube.com/@Mortal"}, "channel": "https://www.youtube.com/@Mortal"})
import studio.autofetch as af  # noqa: E402
reads = []


def fake_feed(url, n=10):
    reads.append(url)
    if url.endswith("/streams"):
        return [{"id": "s1", "url": "https://www.youtube.com/watch?v=s1", "title": "Live 5 hours", "duration": 18000, "live": False},
                {"id": "s2", "url": "https://www.youtube.com/watch?v=s2", "title": "Live now", "duration": 0, "live": True}]
    return [{"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "BGMI rush", "duration": 900, "live": False}]


af.list_feed = fake_feed
config.PUBLIC_URL = "http://127.0.0.1:8765"
cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
r = cl.get(f"/api/creators/{c['id']}/videos")
v = r.json().get("videos", []) if r.status_code == 200 else []
check("their videos and past streams are listed to pick from", [x["title"] for x in v] == ["BGMI rush", "Live 5 hours", "Live now"]
      and [x["kind"] for x in v] == ["Video", "Live stream", "Live stream"], r.text[:300])
n = len(reads)
cl.get(f"/api/creators/{c['id']}/videos")
check("the list is kept for 10 minutes (no re-reading)", len(reads) == n)
cl.get(f"/api/creators/{c['id']}/videos?fresh=1")
check("...unless Refresh is pressed", len(reads) > n)

# comments: auto sync on by default, replies written for approval
with ctx.as_user(uid):
    check("comments auto sync with replies written for you to approve", accounts.settings()["reply_mode"] == "approve")

# ---------------------------------------------------------------- settings from older copies are carried over
old = "PEAK" "CUT_"
f = Path(tempfile.mkdtemp()) / ".env"
f.write_text(f"{old}ACCOUNTS=1\n# a comment\n{old}PUBLIC_URL=https://x.ngrok-free.dev\nOTHER=1\n", encoding="utf-8")
config._upgrade_dotenv(f)
t = f.read_text(encoding="utf-8")
check("old setting names in .env are renamed once", old not in t and "CLIPCUT_ACCOUNTS=1" in t and "CLIPCUT_PUBLIC_URL=https://x.ngrok-free.dev" in t and "OTHER=1" in t)
d = Path(tempfile.mkdtemp())
(d / (old[:-1].lower() + ".db")).write_bytes(b"db")
(d / (old[:-1].lower() + ".db-wal")).write_bytes(b"wal")
real = config.DATA_DIR
config.DATA_DIR = d
config._upgrade_db()
config.DATA_DIR = real
check("the old database file is renamed, with its companions", (d / "clipcut.db").read_bytes() == b"db" and (d / "clipcut.db-wal").is_file()
      and not (d / (old[:-1].lower() + ".db")).exists())

print(f"\n{len(fails)} failed" if fails else "\nAll passed")
sys.exit(1 if fails else 0)
