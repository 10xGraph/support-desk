from http import HTTPStatus

import jwt
import pytest
from fastapi import HTTPException

from demo_server.auth import decode_token, staff_user

from .conftest import make_token


def test_valid_token():
    assert decode_token(make_token())["org_id"] == "acme"


@pytest.mark.parametrize(
    "token",
    [
        make_token(ttl=-10),  # expired
        make_token(secret="another-secret-that-is-long-enough-123"),  # noqa: S106
        make_token(ttl=None),  # no exp
    ],
)
def test_bad_tokens_rejected(token):
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token)


def test_staff_user_refuses_member():
    with pytest.raises(HTTPException) as err:
        staff_user({"user_id": "alice", "roles": ["member"], "org_id": "acme"})
    assert err.value.status_code == HTTPStatus.FORBIDDEN


def test_staff_user_allows_support():
    user = {"user_id": "sam", "roles": ["support"], "org_id": "acme"}
    assert staff_user(user) is user
