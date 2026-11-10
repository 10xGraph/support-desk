"""Generate a JWT secret and save it in .env (JWT_SECRET_KEY, JWT_ALGORITHM=HS256).

Usage: .venv/bin/python scripts/make_secret.py [--force]

Creates .env when missing. Other lines in .env are kept. An existing JWT_SECRET_KEY is kept
unless --force is given (a new secret makes every token issued before it invalid).
Then make a token with: .venv/bin/python deploy/scripts/make_token.py user-1 --name "Alice Chen" --org acme
"""

import secrets
import sys
from pathlib import Path


ENV = Path(__file__).resolve().parent.parent / ".env"


def set_key(lines: list[str], key: str, value: str, replace: bool) -> tuple[list[str], bool]:
    """Set ``key=value`` in the lines of a dotenv file. Returns the lines and whether it changed."""
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            if not replace:
                return lines, False
            lines[i] = f"{key}={value}"
            return lines, True
    return [*lines, f"{key}={value}"], True


force = "--force" in sys.argv
lines = ENV.read_text().splitlines() if ENV.exists() else []
lines, secret_set = set_key(lines, "JWT_SECRET_KEY", secrets.token_urlsafe(48), force)
lines, _ = set_key(lines, "JWT_ALGORITHM", "HS256", False)
ENV.write_text("\n".join(lines) + "\n")

if secret_set:
    print(f"Saved a new JWT_SECRET_KEY (64 characters) in {ENV}")
else:
    print(f"JWT_SECRET_KEY already set in {ENV}; kept it. Use --force to replace it.")
