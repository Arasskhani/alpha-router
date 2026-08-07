"""Deprecated: blank favicon generator.

Brand favicons are produced by prepare_alpha_mark.py from the Alpha mark artwork.
Run: python frontend/scripts/prepare_alpha_mark.py
"""

from pathlib import Path


if __name__ == "__main__":
    raise SystemExit(
        "Use prepare_alpha_mark.py to regenerate favicon.ico / favicon.svg from the brand mark.\n"
        f"Expected script: {Path(__file__).resolve().parents[0] / 'prepare_alpha_mark.py'}"
    )
