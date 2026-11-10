from http import HTTPStatus

import jwt
import pytest
from fastapi import HTTPException

from demo_server.auth import AgentTokenVerifier, decode_token, staff_user

from .conftest import agent_token, make_token


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


def test_agent_token_is_refused_on_rest():
    with pytest.raises(jwt.InvalidAudienceError):
        decode_token(agent_token())


async def test_mcp_accepts_only_agent_tokens():
    verifier = AgentTokenVerifier()
    acting = await verifier.verify_token(agent_token("alice", "acme"))
    assert (acting.claims["user_id"], acting.claims["org_id"]) == ("alice", "acme")
    assert await verifier.verify_token(agent_token(user_id=None)) is not None  # tool listing
    assert await verifier.verify_token(make_token()) is None  # a user's own token
    assert await verifier.verify_token(make_token(roles=["service"])) is None  # no audience
    forged_actor = agent_token(act={"sub": "someone-else"})
    assert await verifier.verify_token(forged_actor) is None
    assert await verifier.verify_token(agent_token(ttl=-10)) is None  # expired
