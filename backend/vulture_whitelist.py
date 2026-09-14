# ruff: noqa
"""vulture allowlist (Phase 3.4). Names here are used dynamically or are part
of a Protocol's signature, which vulture cannot see. Keep it short and give a
reason per entry; CI runs `vulture app vulture_whitelist.py --min-confidence 80`.
"""

# Protocol method parameters: implementers must accept them by keyword.
calls_per_minute  # ToolRateLimiter.consume protocol
calls_per_user_per_minute  # ToolRateLimiter.consume protocol
