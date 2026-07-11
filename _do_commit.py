import subprocess

ROOT = r"C:\APPS\Alpha Router"
msg = (
    "feat(security): phase 4 atomic budget/credit + streaming message corruption\n\n"
    "- _apply_cost_to_user: atomic SQL UPDATE (col = col + :cost) instead of ORM\n"
    "  read-modify-write, eliminating lost updates under concurrent requests.\n"
    "- record_key_usage: atomic UPDATE for period_used_usd/total_used_usd + refresh.\n"
    "- stream_chat finally: log_usage now runs in an independent AsyncSession so a\n"
    "  persister rollback cannot drop the RequestLog/budget increment.\n"
    "- ChatCompletionPersister: reset_persist_state() called after rollbacks so the\n"
    "  next flush re-writes full content; finalize() is rollback-resilient and\n"
    "  retries the final write on a clean transaction.\n"
    "- Tests: test_budget_atomicity.py + test_streaming_corruption.py (10 new).\n"
)

r = subprocess.run(
    ["git", "-C", ROOT, "add", "-A"],
    capture_output=True, text=True,
)
print("add:", r.returncode, r.stderr)

r = subprocess.run(
    ["git", "-C", ROOT, "commit", "-m", msg],
    capture_output=True, text=True,
)
print("commit:", r.returncode)
print(r.stdout[-1500:])
print(r.stderr[-800:])
