"""One-click Connect for YouTube, Instagram and TikTok, and posting to each. The platforms are replaced by
stand-ins answering the way their documentation says, so nothing leaves this machine."""
import json, os, sys, tempfile, time
from urllib.parse import parse_qs, urlparse
os.environ["CLIPCUT_DATA"] = tempfile.mkdtemp(prefix="pc-connect-")
os.environ.update(DATABASE_URL="", CLIPCUT_ACCOUNTS="1", CLIPCUT_PUBLIC_URL="https://clips.example.com", CLIPCUT_VERIFY_EMAIL="0",
                  GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", GOOGLE_CLIENT_FILE="", CLIPCUT_IG_APP_ID="", CLIPCUT_IG_APP_SECRET="",
                  CLIPCUT_TIKTOK_CLIENT_KEY="", CLIPCUT_TIKTOK_CLIENT_SECRET="",
                  CLIPCUT_META_APP_ID="", CLIPCUT_META_APP_SECRET="", CLIPCUT_META_CONFIG_ID="")
sys.path.insert(0, ".")
from pathlib import Path
import sqlalchemy as sa
from fastapi.testclient import TestClient
from studio import accounts, auth, config, ctx, db, server
db.init()
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

BASE = "https://clips.example.com"
ORIGIN = {"Origin": BASE}
def person(email, admin=False):
    u, _ = auth._create(email, email.split("@")[0], password_hash="x")
    if admin:
        with db.engine.begin() as c:
            c.execute(db.users.update().where(db.users.c.id == u.id).values(is_admin=True))
    cl = TestClient(server.app, base_url=BASE, follow_redirects=False)
    cl.cookies.set(auth.COOKIE, auth.start_session(u.id))
    return u, cl
boss, a = person("boss@example.com", admin=True)
user, b = person("user@example.com")

# ---- nothing is set up: the buttons say so, and only an admin may set it up
st = b.get("/api/status").json()
check("nothing can be connected before setup", st["connect"], {"youtube": False, "instagram": False, "tiktok": False, "facebook": False})
check("a normal user cannot see the setup", b.get("/api/apps").status_code, 404)
check("...or change it", b.put("/api/apps", json={"platform": "tiktok", "client_id": "abcd", "client_secret": "x"}, headers=ORIGIN).status_code, 404)
r = b.get("/oauth/instagram/start")
check("Connect before setup comes back with a reason", (r.status_code, "connect_error" in r.headers.get("location", "")), (303, True))
check("setup from another website is refused", a.put("/api/apps", json={"platform": "tiktok", "client_id": "abcd1234", "client_secret": "s"},
                                                    headers={"Origin": "https://evil.example"}).status_code, 403)
check("a bad id is refused", a.put("/api/apps", json={"platform": "tiktok", "client_id": "a b<", "client_secret": "s"}, headers=ORIGIN).status_code, 400)
for pf, cid in (("youtube", "g-client-123.apps"), ("instagram", "1234567890"), ("tiktok", "awtiktokkey123")):
    r = a.put("/api/apps", json={"platform": pf, "client_id": cid, "client_secret": f"{pf}-secret-value"}, headers=ORIGIN)
    check(f"{pf} app saved", (r.status_code, r.json()[pf]["ready"]), (200, True))
apps = a.get("/api/apps").json()
check("secrets are never sent back", any("secret-value" in json.dumps(v) for v in apps.values()), False)
check("each platform shows the address to register", apps["tiktok"]["redirect"], BASE + "/oauth/tiktok/callback")
r = a.put("/api/apps", json={"platform": "tiktok", "client_id": "", "client_secret": "tiktok-secret-value2"}, headers=ORIGIN)
check("a new secret alone keeps the saved id", accounts.app_keys("tiktok"), ("awtiktokkey123", "tiktok-secret-value2"))
check("a Configuration ID must be a number", a.put("/api/apps", json={"platform": "facebook", "client_id": "99887766", "client_secret": "meta-secret-value",
                                                                     "config_id": "abc"}, headers=ORIGIN).status_code, 400)
r = a.put("/api/apps", json={"platform": "facebook", "client_id": "99887766", "client_secret": "meta-secret-value", "config_id": "1234567890123"}, headers=ORIGIN)
check("Meta app saved with its Configuration ID", (r.status_code, r.json()["facebook"]["ready"], r.json()["facebook"]["has_config"]), (200, True, True))
check("the Meta secret is never sent back", "meta-secret-value" in json.dumps(a.get("/api/apps").json()), False)
a.put("/api/apps", json={"platform": "facebook", "client_id": "99887766", "client_secret": ""}, headers=ORIGIN)
check("saving again without a Configuration ID keeps the saved one", accounts.meta_config_id(), "1234567890123")
check("everyone can connect now", b.get("/api/status").json()["connect"], {"youtube": True, "instagram": True, "tiktok": True, "facebook": True})

# ---- YouTube cookies, for servers YouTube refuses
from studio import media
COOK = ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tsecret-cookie-value\n"
check("a normal user cannot save YouTube cookies", b.put("/api/youtube-cookies", json={"text": COOK}, headers=ORIGIN).status_code, 404)
check("something that is not a cookies file is refused", a.put("/api/youtube-cookies", json={"text": "hello"}, headers=ORIGIN).status_code, 400)
r = a.put("/api/youtube-cookies", json={"text": COOK}, headers=ORIGIN)
check("cookies saved", (r.status_code, r.json()["saved"]), (200, True))
check("the cookies are never sent back", "secret-cookie-value" in a.get("/api/youtube-cookies").text, False)
check("downloads use them", media.cookie_opts(), {"cookiefile": str(config.YT_COOKIES)})
a.put("/api/youtube-cookies", json={"remove": True}, headers=ORIGIN)
check("...until they are removed", (config.YT_COOKIES.exists(), media.cookie_opts()), (False, {}))

# ---- the platforms, as stand-ins
class R:
    def __init__(self, code, data=None, headers=None, text=None):
        self.status_code, self._d, self.headers = code, data, headers or {}
        self.text = text if text is not None else json.dumps(data)
    def json(self):
        if self._d is None:
            raise ValueError
        return self._d
calls, uploads, tt, fbs = [], [], {"audited": False, "status": 0}, []
def post(url, data=None, json=None, headers=None, params=None, timeout=None, content=None):
    calls.append(("POST", url, data or json, headers or {}))
    if url == "https://oauth2.googleapis.com/token":
        return R(200, {"access_token": "yt-access", "refresh_token": "yt-refresh", "expires_in": 3600})
    if url == "https://api.instagram.com/oauth/access_token":
        if data["code"] != "igcode":
            return R(400, {"error_message": "bad code"})
        return R(200, {"data": [{"access_token": "ig-short", "user_id": "17841", "permissions": "instagram_business_basic,instagram_business_content_publish"}]})
    if url.endswith("/oauth/token/"):
        if data.get("grant_type") == "refresh_token":
            return R(200, {"access_token": "tt-access-2", "refresh_token": "tt-refresh-2", "expires_in": 7200, "open_id": "oid", "scope": "user.info.basic,video.publish"})
        return R(200, {"access_token": "tt-access", "refresh_token": "tt-refresh", "expires_in": 7200, "open_id": "oid", "scope": "user.info.basic,video.publish"})
    if url.endswith("/creator_info/query/"):
        return R(200, {"data": {"creator_username": "streamerclips", "creator_nickname": "Streamer Clips",
                                "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"]}, "error": {"code": "ok"}})
    if url.endswith("/post/publish/video/init/"):
        lv = json["post_info"]["privacy_level"]
        tt["init"] = json
        if lv != "SELF_ONLY" and not tt["audited"]:
            return R(403, {"error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "private only"}})
        return R(200, {"data": {"publish_id": "v_pub_1", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=1"}, "error": {"code": "ok"}})
    if url.endswith("/post/publish/status/fetch/"):
        tt["status"] += 1
        if tt["status"] < 2:
            return R(200, {"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}})
        return R(200, {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300] if tt["audited"] else []}, "error": {"code": "ok"}})
    if url.endswith("/17841/media"):
        return R(200, {"id": "container1"})
    if url.endswith("/555/video_reels"):
        fbs.append(data)
        return R(200, {"video_id": "fbvid1", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/fbvid1"} if data.get("upload_phase") == "start" else {"success": True})
    if url.startswith("https://rupload.facebook.com/video-upload/"):
        fbs.append({"uploaded": len(content or b""), "auth": (headers or {}).get("Authorization")})
        return R(200, {"success": True})
    if url.endswith("/v21.0/1784199/media"):
        return R(200, {"id": "container2"})
    if url.endswith("/v21.0/1784199/media_publish"):
        return R(200, {"id": "media2"})
    if url.endswith("/17841/media_publish"):
        return R(200, {"id": "media1"})
    return R(404, {})
def get(url, params=None, headers=None, timeout=None):
    calls.append(("GET", url, params, headers or {}))
    if url == "https://graph.facebook.com/v21.0/oauth/access_token":
        if params.get("code") and params["code"] != "fbcode":
            return R(400, {"error": {"code": 100, "message": "bad code"}})
        return R(200, {"access_token": "fb-long" if params.get("grant_type") == "fb_exchange_token" else "fb-short"})
    if url == "https://graph.facebook.com/v21.0/me/accounts":
        return R(200, {"data": [{"id": "555", "name": "GameXtra Page", "access_token": "page-token",
                                 "instagram_business_account": {"id": "1784199", "username": "gamextra00"}}]})
    if url == "https://graph.facebook.com/v21.0/fbvid1":
        return R(200, {"status": {"video_status": "ready"}})
    if url == "https://graph.facebook.com/v21.0/container2":
        return R(200, {"status_code": "FINISHED"})
    if url == "https://graph.facebook.com/v21.0/media2":
        return R(200, {"permalink": "https://www.instagram.com/reel/fb2/"})
    if url.endswith("/youtube/v3/channels"):
        return R(200, {"items": [{"id": "UC123", "snippet": {"title": "My Channel"}}]})
    if url == "https://graph.instagram.com/access_token":
        return R(200, {"access_token": "ig-long", "token_type": "bearer", "expires_in": 5183944})
    if url == "https://graph.instagram.com/me":
        return R(200, {"user_id": "17841", "username": "clipper", "account_type": "MEDIA_CREATOR"})
    if url.endswith("/container1"):
        return R(200, {"status_code": "FINISHED"})
    if url.endswith("/media1"):
        return R(200, {"permalink": "https://www.instagram.com/reel/abc/"})
    return R(404, {})
def put(url, content=None, headers=None, timeout=None):
    uploads.append((url, len(content), headers))
    return R(201, None, text="")
accounts.httpx.post, accounts.httpx.get, accounts.httpx.put = post, get, put
accounts.time.sleep = lambda s: None

# ---- connecting: the button goes to the platform's own page, and back
def connect(cl, pf, code="code1"):
    r = cl.get(f"/oauth/{pf}/start")
    loc = urlparse(r.headers["location"])
    state = parse_qs(loc.query)["state"][0]
    back = cl.get(f"/oauth/{pf}/callback", params={"code": code, "state": state})
    return loc, back
loc, back = connect(b, "youtube")
check("YouTube: Google's page, asking to upload", (loc.netloc, "youtube.upload" in parse_qs(loc.query)["scope"][0]), ("accounts.google.com", True))
check("YouTube: back on Connected apps, connected", (back.status_code, back.headers["location"].startswith("/app/settings/apps?connected=youtube")), (303, True))
loc, back = connect(b, "instagram", "igcode#_")
q = parse_qs(loc.query)
check("Instagram: Instagram's own page, with publishing permission", (loc.netloc, q["client_id"][0], "instagram_business_content_publish" in q["scope"][0]),
      ("www.instagram.com", "1234567890", True))
check("Instagram: connected, with the #_ Instagram adds to the code removed", "connected=instagram" in back.headers["location"])
loc, back = connect(b, "tiktok")
q = parse_qs(loc.query)
check("TikTok: TikTok's own page, asking to post", (loc.netloc, q["client_key"][0], q["scope"][0]), ("www.tiktok.com", "awtiktokkey123", "user.info.basic,video.publish"))
check("TikTok: connected", "connected=tiktok" in back.headers["location"])
loc, back = connect(b, "facebook", "fbcode")
q = parse_qs(loc.query)
check("Facebook: Facebook's own page, with the Configuration ID", (loc.netloc, q["client_id"][0], q["config_id"][0], "scope" in q),
      ("www.facebook.com", "99887766", "1234567890123", False))
check("Facebook: connected", "connected=facebook" in back.headers["location"])
check("Facebook: the message names the Page and the Instagram account", "gamextra00" in back.headers["location"])
fbacc = [x for x in b.get("/api/accounts").json() if x["platform"] == "facebook" or x.get("via") == "facebook"]
check("Facebook: the Page and its Instagram account are both added", sorted((x["platform"], x["name"]) for x in fbacc),
      [("facebook", "GameXtra Page"), ("instagram", "@gamextra00")])
check("page tokens never reach the page", "page-token" in b.get("/api/accounts").text, False)
accs = {x["platform"]: x for x in b.get("/api/accounts").json() if not x.get("via")}
check("all three accounts are listed with their names", (accs["youtube"]["name"], accs["instagram"]["name"], accs["tiktok"]["name"]),
      ("My Channel", "@clipper", "@streamerclips"))
check("tokens never reach the page", any(t in b.get("/api/accounts").text for t in ("ig-long", "tt-access", "yt-refresh")), False)
check("someone else's accounts are not mine", a.get("/api/accounts").json(), [])
r = b.get("/oauth/tiktok/callback", params={"code": "x", "state": "made-up"})
check("a made-up return is refused", "connect_error" in r.headers["location"])
r = b.get("/oauth/tiktok/callback", params={"error": "access_denied"})
check("cancelling on the platform says so", "cancelled" in r.headers["location"])
loc = urlparse(a.get("/oauth/tiktok/start").headers["location"])
r = b.get("/oauth/tiktok/callback", params={"code": "c", "state": parse_qs(loc.query)["state"][0]})
check("one person's sign-in cannot be finished by another", "connect_error" in r.headers["location"])
check("an unknown platform does not exist", b.get("/oauth/myspace/start").status_code, 404)

# ---- the one-hour links Instagram fetches clips from
with ctx.as_user(user.id):
    jd = config.user_dir(user.id) / "jobs" / "job-12345678" / "clips"
jd.mkdir(parents=True)
(jd.parent / "job.json").write_text(json.dumps({"id": "job-12345678", "user": user.id, "dir": str(jd.parent), "clips": [], "status": "done",
                                                "creator": None, "created": time.time(), "options": {}, "source": {"type": "file"}}), encoding="utf-8")
(jd / "clip01.mp4").write_bytes(b"\x00" * 6_000)
from studio import jobs
jobs.load_user(user.id)
with ctx.as_user(user.id):
    link = accounts.clip_link("job-12345678", "clip01.mp4")
anon = TestClient(server.app, base_url=BASE)
path = urlparse(link).path
check("a signed link serves the clip to anyone, no sign-in", (anon.get(path).status_code, len(anon.get(path).content)), (200, 6000))
bad = path.replace(".mp4", "x.mp4")
check("a changed link does not", anon.get(bad).status_code, 404)
check("a made-up link does not", anon.get("/pub/abc.def.mp4").status_code, 404)
with ctx.as_user(user.id):
    old = accounts.clip_link("job-12345678", "clip01.mp4", seconds=-5)
check("an expired link does not", anon.get(urlparse(old).path).status_code, 404)

# ---- posting
with ctx.as_user(user.id):
    ig, ttacc = accounts.get(accs["instagram"]["id"]), accounts.get(accs["tiktok"]["id"])
    calls.clear()
    rid, url = accounts.instagram_upload(ig, jd / "clip01.mp4", "My caption", "job-12345678")
    made = next(c for c in calls if c[1].endswith("/17841/media"))
    check("Instagram: a Reel from the signed link", (made[2]["media_type"], made[2]["video_url"].startswith(BASE + "/pub/")), ("REELS", True))
    check("Instagram: published, with its link", (rid, url), ("media1", "https://www.instagram.com/reel/abc/"))

    uploads.clear(); tt.update(audited=False, status=0)
    rid, url = accounts.tiktok_upload(ttacc, jd / "clip01.mp4", "My caption #fyp", "public")
    check("TikTok: an app not yet reviewed posts privately instead of failing", (tt["init"]["post_info"]["privacy_level"], url), ("SELF_ONLY", ""))
    check("TikTok: the whole file in one piece, with the right range", (len(uploads), uploads[0][2]["Content-Range"]), (1, "bytes 0-5999/6000"))
    check("TikTok: the account says why posts are private", "private" in accounts.get(ttacc["id"]).get("detail", ""))
    tt.update(audited=True, status=0)
    rid, url = accounts.tiktok_upload(ttacc, jd / "clip01.mp4", "My caption", "public")
    check("TikTok: once reviewed, public, with the video's link", (tt["init"]["post_info"]["privacy_level"], url),
          ("PUBLIC_TO_EVERYONE", "https://www.tiktok.com/@streamerclips/video/7300"))
    check("TikTok: big files go in pieces, the last taking the rest", accounts._tt_chunks(150_000_123), (10_000_000, 15))
    acc = accounts.get(ttacc["id"]); acc["expires"] = 0; accounts._put(acc)
    accounts._tt_token(accounts.get(ttacc["id"]))
    check("TikTok: an old sign-in is renewed, and the new refresh token kept", accounts.get(ttacc["id"])["refresh_token"], "tt-refresh-2")

with ctx.as_user(user.id):
    page = accounts.get("fb_555")
    fbs.clear()
    rid, url = accounts.facebook_upload(page, jd / "clip01.mp4", "Caption 🔥", "Title")
    check("Facebook: a Reel is started, the file sent straight to Facebook, then published",
          ([x.get("upload_phase") for x in fbs if "upload_phase" in x], [x.get("uploaded") for x in fbs if "uploaded" in x], fbs[1]["auth"]),
          (["start", "finish"], [6000], "OAuth page-token"))
    check("Facebook: the caption goes with it, emojis included", fbs[-1]["description"], "Caption 🔥")
    check("Facebook: its link", (rid, url), ("fbvid1", "https://www.facebook.com/reel/fbvid1"))
    igfb = accounts.get("ig_1784199")
    calls.clear()
    rid, url = accounts.instagram_upload(igfb, jd / "clip01.mp4", "Caption", "job-12345678")
    made = next(c for c in calls if c[1].endswith("/1784199/media"))
    check("Instagram through Facebook: posted with Facebook's address and the Page's token",
          (made[1].startswith("https://graph.facebook.com/"), made[3]["Authorization"], rid, url),
          (True, "Bearer page-token", "media2", "https://www.instagram.com/reel/fb2/"))

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil; db.engine.dispose(); shutil.rmtree(os.environ["CLIPCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
