#!/usr/bin/env python3
"""Host/container wrapper for the admin IP restriction break-glass CLI."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.security_breakglass import main

if __name__ == "__main__":
    raise SystemExit(main())
