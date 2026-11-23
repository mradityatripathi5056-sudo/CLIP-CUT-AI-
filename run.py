"""Run the test suite against a throwaway copy of the app.

    python tests/run.py

Starts Clip Cut AI on a spare port with an empty, temporary data folder, runs the tests against it, then stops it and
deletes the folder. Your real data and your running server are never touched. No AI key is needed: the tests cover accounts, permissions, limits and the queue, not clip quality."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("CLIPCUT_TEST_PORT", "8799"))
BASE = f"http://127.0.0.1:{PORT}"


def main() -> int:
    data = Path(tempfile.mkdtemp(prefix="clipcut-test-"))
    env = {**os.environ, "CLIPCUT_DATA": str(data), "CLIPCUT_PORT": str(PORT), "CLIPCUT_PUBLIC_URL": BASE,
           "CLIPCUT_HOST": "127.0.0.1", "CLIPCUT_AUTO_RELOAD": "0", "DATABASE_URL": "",
           "CLIPCUT_ACCOUNTS": "1", "CLIPCUT_FETCH_MODEL": "0", "CLIPCUT_UPDATE_CHECK": "0",                   # these tests are about people signing in; tests/test_local.py covers the default
           # nothing outside this machine is contacted: no AI, no email, no Google sign-in
           "CLIPCUT_SMTP_HOST": "", "CLIPCUT_VERIFY_EMAIL": "1",   # the tests cover the confirm-your-email rule
           "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "", "GOOGLE_CLIENT_FILE": "", "PYTHONUNBUFFERED": "1",
           "CLIPCUT_AI_KEY": "", "CLIPCUT_AI_KEY_FILE": "", "CLIPCUT_AI_MODELS": "",
           "CLIPCUT_UPLOAD_PART_MB": "5", "CLIPCUT_MAX_UPLOAD_MB": "64"}
    log = data / "server.log"
    failed = []
    with log.open("w", encoding="utf-8") as out:
        server = subprocess.Popen([sys.executable, "-m", "studio.server"], cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        for _ in range(90):
            try:
                urllib.request.urlopen(BASE + "/healthz", timeout=2)
                break
            except Exception:  # noqa: BLE001
                if server.poll() is not None:
                    print(log.read_text(encoding="utf-8", errors="replace")[-2000:])
                    return 1
                time.sleep(1)
        else:
            print("The test server did not start.")
            return 1
        runs = [("permissions", ["tests/test_permissions.py", BASE, str(ROOT), sys.executable]),
                ("abuse and limits", ["tests/test_abuse.py", BASE, str(ROOT)]),
                ("queue under load", ["tests/test_load_queue.py", str(ROOT)]),
                ("a day-long video in little memory", ["tests/test_longvideo.py"]),
                ("deleting and bulk actions", ["tests/test_delete.py"]),
                ("saving a video when Windows says busy", ["tests/test_jobsave.py"]),
                ("your own big text on the clips", ["tests/test_bigtext.py"]),
                ("hashtags made without an AI", ["tests/test_hashtags.py"]),
                ("big uploads in pieces", ["tests/test_upload_parts.py", BASE]),
                ("AI services", ["tests/test_ai.py"]),
                ("no sign-in, and the AI key from the dashboard", ["tests/test_local.py"]),
                ("Hindi and Urdu captions in Roman letters", ["tests/test_roman.py"]),
                ("turning captions off and back on", ["tests/test_captions.py"]),
                ("connecting YouTube, Instagram, TikTok and Facebook", ["tests/test_connect.py"]),
                ("scheduling posts: picked times, fixed times, the calendar, caption style", ["tests/test_schedule.py"]),
                ("a login that keeps everything, backups, YouTube extras", ["tests/test_extras.py"]),
                ("AI replies to comments on YouTube, Instagram and Facebook", ["tests/test_replies.py"]),
                ("autopilot: new uploads, logo, Telegram, DMs, best times, second titles, hits again", ["tests/test_autopilot.py"]),
                ("a shared workspace for a team", ["tests/test_team.py"]),
                ("the AI Manager: hourly round, report, chat with tools, Telegram", ["tests/test_manager.py"]),
                ("email codes, quick add, Hinglish/English, music, money, push, roles", ["tests/test_audience.py"]),
                ("autopilot: learning, hook tests, smart queue, viral, guards, slot filler, English version", ["tests/test_autopilot_plus.py"]),
                ("daily limit per page (hand-made posts count, checked every 2 hours)", ["tests/test_limits.py"]),
                ("comments on all recent page videos, shown even with replies off", ["tests/test_replies_all.py"]),
                ("YouTube growth strategy: SEO package, title lint, viral outliers, posting modes, comment piles, ONE fix", ["tests/test_ytstrategy.py"]),
                ("online with ngrok, closed sign-up, start with Windows, video picker, comment auto sync", ["tests/test_online.py"]),
                ("the Manager changes anything you ask: settings, hashtags, limits, posts", ["tests/test_manager_plus.py"]),
                ("effects, compilations, campaign reports, trending, analytics, swipe review, phone app, moving machines", ["tests/test_more.py"]),
                ("the new-version notice", ["tests/test_updates.py"]),
                ("no limits by default", ["tests/test_limits.py"]),
                ("captions never overlap, stuck clips, sentence endings", ["tests/test_stuck.py"]),
                ("ad breaks and frozen screens", ["tests/test_static.py"]),
                ("answers that are not quite right", ["tests/test_answer.py"]),
                ("waiting out AI rate limits", ["tests/test_retry.py"]),
                ("knowing which game a stream is", ["tests/test_games.py"]),
                ("finding the facecam in a gaming stream", ["tests/test_facecam.py"]),
                ("recording time: the buffer knows where each piece sits", ["tests/test_live_times.py"]),
                ("fresh installs: ffmpeg, the speech model, AI errors", ["tests/test_tools.py"]),
                ("the storage folder: full drive, open, move", ["tests/test_storage.py"]),
                ("security: visitor address, email addresses, Google sign-in, prompts", ["tests/test_hardening.py"]),
                ("long logs, the machine monitor, failed recordings, admin day totals", ["tests/test_robustness.py"]),
                ("speech models for other languages: Arabic, downloads, the second machine", ["tests/test_speech.py"]),
                ("post text: write again with AI, edit, post without re-making", ["tests/test_post_text.py"]),
                ("live recording stops and empty stream URLs", ["tests/test_live.py"])]
        for name, args in runs:
            print(f"\n=== {name} ===", flush=True)
            r = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            lines = (r.stdout + r.stderr).splitlines()
            passed = sum(1 for x in lines if x.startswith("PASS"))
            for x in lines:
                if not x.startswith("PASS") and x.strip():
                    print("  " + x)
            print(f"  {passed} checks passed")
            if r.returncode != 0 or any(x.startswith("FAIL") for x in lines):
                failed.append(name)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(data, ignore_errors=True)
    print("\nFAILED: " + ", ".join(failed) if failed else "\nAll tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
