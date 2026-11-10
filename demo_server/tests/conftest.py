import time

import jwt
import pytest


SECRET = "test-secret-key-that-is-long-enough-1234"  # noqa: S105


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.delenv("JWT_ALGORITHM", raising=False)


def make_token(user_id="alice", roles=("member",), org_id="acme", ttl=3600, secret=SECRET):
    claims = {"user_id": user_id, "roles": list(roles), "iat": int(time.time())}
    if org_id:
        claims["org_id"] = org_id
    if ttl is not None:
        claims["exp"] = int(time.time()) + ttl
    return jwt.encode(claims, secret, algorithm="HS256")
