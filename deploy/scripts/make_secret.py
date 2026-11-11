"""Generate the stack's secrets and save them in .env.

JWT_SECRET_KEY (with JWT_ALGORITHM=HS256), PHOENIX_SECRET and PHOENIX_ADMIN_SECRET.

Usage: .venv/bin/python deploy/scripts/make_secret.py [--force]

Creates .env when missing. Other lines in .env are kept. Existing values are kept unless
--force is given (a new JWT secret makes every token issued before it invalid).
Then make a token with: .venv/bin/python deploy/scripts/make_token.py user-1 --name "Alice Chen" --org acme
"""

import secrets
import sys
from pathlib import Path


ENV = Path(__file__).resolve().parents[2] / ".env"  # project root


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
def phoenix_secret() -> str:
    """Phoenix needs 32+ characters with at least one digit and one lowercase letter."""
    return "p0" + secrets.token_hex(32)


lines, _ = set_key(lines, "JWT_ALGORITHM", "HS256", False)
for key, value in (
    ("JWT_SECRET_KEY", secrets.token_urlsafe(48)),
    ("PHOENIX_SECRET", phoenix_secret()),
    ("PHOENIX_ADMIN_SECRET", phoenix_secret()),
):
    lines, changed = set_key(lines, key, value, force)
    print(f"{key}: {'saved a new value' if changed else 'already set, kept'}")
ENV.write_text("\n".join(lines) + "\n")
print(f"in {ENV}. Use --force to replace existing values.")
