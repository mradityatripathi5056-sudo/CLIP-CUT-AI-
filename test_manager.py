"""The AI Manager: its hourly round (retry passing failures, warn about accounts to connect again, post good clips
nobody looked at, the daily report) and chat with tools, from the page and from Telegram. The AI is a stand-in."""
import json
import os
import sys
import tempfile
import time

os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-manager-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="0", CLIPCUT_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402

from studio import accounts, alerts, auth, config, creators, ctx, db, jobs, manager, posting, server, telebot  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


me = auth.local_user()
cl = TestClient(server.app, base_url="http://127.0.0.1:8765")
H = {"Origin": "http://127.0.0.1:8765"}
sent = []
alerts.notify = lambda text, **kw: sent.append(text)
alerts.send = lambda text: sent.append(text) or []
alerts.configured = lambda: True
config.ai_ready = lambda: True

with ctx.as_user(me.id):
    accounts._put({"id": "yt_1", "platform": "youtube", "name": "GameXtra", "added": time.time(), "access_token": "a", "refresh_token": "r", "expires": time.time() + 3600})
    accounts._put({"id": "ig_1", "platform": "instagram", "name": "@gamextra00", "added": time.time(), "user_id": "1", "token": "t", "token_time": time.time()})
    c = creators.create({"name": "Valorant Pro", "accounts": ["yt_1"], "post_min_score": 75})
    j = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c["id"])
    old = time.time() - 3 * 3600
    j["clips"] += [{"id": "good", "status": "done", "file": "g.mp4", "title": "Ace 🔥", "score": 88, "made_at": old},
                   {"id": "weak", "status": "done", "file": "w.mp4", "title": "Meh", "score": 40, "made_at": old},
                   {"id": "fresh", "status": "done", "file": "f.mp4", "title": "New", "score": 95, "made_at": time.time()}]
    jobs.save(j)
    for pid, err in (("f1", "YouTube took too long to process the video."), ("f2", "Instagram refused (401): token expired"), ("f3", "Something odd")):
        posting._posts.append({"id": pid, "user": me.id, "job": j["id"], "clip": "x", "creator": c["id"], "account": "ig_1" if pid == "f2" else "yt_1",
                               "account_name": "@gamextra00" if pid == "f2" else "GameXtra", "platform": "youtube", "status": "failed",
                               "due_at": old, "created": old, "title": f"Post {pid}", "error": err, "tries": 3, "views": None, "url": "", "remote_id": ""})

r = cl.get("/api/manager")
check("the Manager starts off", r.status_code == 200 and r.json()["on"] is False)
with ctx.as_user(me.id):
    check("while off, the hourly round does nothing", manager.round_once() == {"on": False})
manager.threading.Thread = lambda target=None, daemon=None, args=(): type("T", (), {"start": lambda self: None})()
r = cl.put("/api/manager", json={"on": True}, headers=H)
check("it can be switched on", r.json()["on"] is True)
check("switching from another website is refused", cl.put("/api/manager", json={"on": False}, headers={"Origin": "https://evil.example"}).status_code == 403)

with ctx.as_user(me.id):
    accounts.save_settings({"paused": True, "digest_hour": 0})
    out = manager.round_once()
    st = {p["id"]: p["status"] for p in posting._mine()}
    check("a post that failed for a passing reason is retried", st["f1"] == "scheduled" and out["retried"] == 1, str(out))
    check("one refused for its sign-in is not retried", st["f2"] == "failed")
    check("...and you are told to connect that account again, once", out["reconnect"] == ["@gamextra00"] and any("connect again" in s for s in sent))
    queued = {p["clip"] for p in posting._mine() if p["status"] == "scheduled"}
    check("a good clip nobody looked at for two hours is posted", "good" in queued and out["queued"] == 1)
    check("a weak clip, or one just made, is left for you", "weak" not in queued and "fresh" not in queued)
    check("a paused page gets a reminder", any("paused" in s for s in sent))
    check("the daily report goes out with what it did", any(s.startswith("🤖 Manager report") and "Retried" in s for s in sent))
    n = len(sent)
    again = manager.round_once()
    check("the next round doesn't repeat itself", again["queued"] == 0 and again["reconnect"] == [] and len(sent) == n, str(again))
    for _ in range(3):
        for p in posting._mine():
            if p["id"] == "f1":
                p.update(status="failed", error="timeout")
        manager.round_once()
    check("retries stop after three", next(p for p in posting._mine() if p["id"] == "f1")["status"] == "failed")

# ---------------------------------------------------------------- chat with tools
script = []


def fake_ai(prompt, schema=None, purpose="", timeout=None):
    script.append(prompt)
    last = [l for l in prompt.split("</conversation>")[0].splitlines() if l.startswith("Owner:")][-1]
    if "kitne views" in last and "<tool_results>" not in prompt:
        return {"reply": "", "actions": [{"tool": "status", "args": "{}"}]}, "m", 1
    if "roz 5 post" in last and "<tool_results>" not in prompt:
        return {"reply": "", "actions": [{"tool": "update_creator", "args": json.dumps({"creator": "valorant", "settings": {"daily_cap": 5, "password": "x"}})}]}, "m", 1
    if "delete" in last and "<tool_results>" not in prompt:
        return {"reply": "", "actions": [{"tool": "delete_everything", "args": "{}"}]}, "m", 1
    if "<tool_results>" in prompt:
        return {"reply": "Done 👍 " + prompt.split("<tool_results>")[-1][:80], "actions": []}, "m", 1
    return {"reply": "Hi!", "actions": []}, "m", 1


manager.brain.ask_ai = fake_ai
r = cl.post("/api/manager/chat", json={"text": "aaj kitne views aaye?"}, headers=H)
check("a question is answered after looking it up", r.status_code == 200 and "summary" in script[-1] and r.json()["reply"].startswith("Done"), r.text[:300])
r = cl.post("/api/manager/chat", json={"text": "Valorant Pro ke liye roz 5 post kar do"}, headers=H)
with ctx.as_user(me.id):
    cr = creators.get(c["id"])
check("asked to change a setting, it changes it (and only what it is allowed to)", cr["daily_cap"] == 5 and "password" not in cr)
check("...and writes it in its log", any("update_creator" in x["text"] for x in r.json()["log"]))
r = cl.post("/api/manager/chat", json={"text": "delete my account"}, headers=H)
check("there is no tool for deleting: it says so instead", r.status_code == 200 and "No such tool" in script[-1])
check("the conversation is kept", [m["role"] for m in r.json()["chat"]][-2:] == ["you", "manager"])
check("an empty message is refused", cl.post("/api/manager/chat", json={"text": " "}, headers=H).status_code == 400)
check("the AI's text from the pages can't close the results early", script[-1].count("</tool_results>") == script[-1].count("<tool_results>"))

# ---------------------------------------------------------------- the same from Telegram
tg = []
telebot._send = lambda method, data, files=None: tg.append((method, data))
with ctx.as_user(me.id):
    accounts.save_settings({"telegram_token": "123:abc", "telegram_chat": "999", "tg_control": True})
    telebot.handle({"update_id": 1, "message": {"chat": {"id": 999}, "text": "hello manager"}})
    check("a message to the Telegram bot gets the Manager's answer", tg and tg[-1][1]["text"] == "Hi!")
    telebot.handle({"update_id": 2, "message": {"chat": {"id": 5}, "text": "pause everything"}})
    check("...only from your own chat", len(tg) == 1)
    check("it is in the same conversation", manager._data()["chat"][-2]["via"] == "telegram")

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402
db.engine.dispose()
shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
