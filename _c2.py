import subprocess

ROOT = r"C:\APPS\NITRO"
msg = (
    "fix(security): make ensure_user_chat_prefs race-safe across uvicorn workers\n\n"
    "Same class of startup race as mark_migration_completed: multiple workers run\n"
    "the lifespan concurrently and all reach ensure_user_chat_prefs for each user,\n"
    "raising UniqueViolation on user_chat_prefs_pkey and crashing startup. Replace\n"
    "the ORM get-then-add with a dialect-aware upsert (ON CONFLICT DO NOTHING for\n"
    "PostgreSQL, INSERT OR IGNORE for SQLite) then re-fetch the row.\n"
)

r = subprocess.run(["git", "-C", ROOT, "add", "-A"], capture_output=True, text=True)
print("add:", r.returncode, r.stderr)
r = subprocess.run(["git", "-C", ROOT, "commit", "-m", msg], capture_output=True, text=True)
print("commit:", r.returncode, r.stdout[-500:], r.stderr[-200:])
