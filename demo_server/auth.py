"""JWT checks, using the same secret and claims as the 10xGraph API.

REST: the user's own token (claims user_id, roles, org_id; exp required). Staff are support,
org_admin and admin.

MCP: only the support agent's own short-lived tokens, with audience "demo-mcp". The agent signs
one per call (graph/support_tools.py): the customer as user_id/org_id and itself as the actor
(act.sub), or, to list tools, itself alone with role "service". A user token has no audience, so
it is refused on /mcp; an agent token has one, so it is refused on REST.
"""

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp.server.auth import AccessToken, TokenVerifier


STAFF_ROLES = {"support", "org_admin", "admin"}
MCP_AUDIENCE = "demo-mcp"
AGENT_ID = "support-agent"

bearer = HTTPBearer(auto_error=False)


def decode_token(token: str, audience: str | None = None) -> dict[str, Any]:
    """Return the claims of a valid token, or raise jwt.InvalidTokenError.

    Without `audience`, a token that carries an `aud` claim is refused (InvalidAudienceError).
    """
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not set.")
    claims = jwt.decode(
        token,
        secret,
        algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
        audience=audience,
        options={"require": ["exp", "aud"] if audience else ["exp"]},
    )
    if not isinstance(claims.get("roles"), list) or not claims.get("user_id"):
        raise jwt.InvalidTokenError("Token needs user_id and a roles list.")
    return claims


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    """Any signed-in user of an organisation. 401 otherwise."""
    if creds is None:
        raise HTTPException(401, "Missing bearer token.", {"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(creds.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired token.", {"WWW-Authenticate": "Bearer"})
    if not claims.get("org_id"):
        raise HTTPException(401, "Token has no org_id.", {"WWW-Authenticate": "Bearer"})
    return claims


def staff_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """A support, org_admin or admin user. 403 for anyone else."""
    if not STAFF_ROLES & set(user["roles"]):
        raise HTTPException(403, "Staff only.")
    return user


class AgentTokenVerifier(TokenVerifier):
    """MCP bearer check: only tokens the support agent signed for demo_server get through."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = decode_token(token, audience=MCP_AUDIENCE)
        except jwt.InvalidTokenError:
            return None
        acting_for_customer = (claims.get("act") or {}).get("sub") == AGENT_ID
        agent_alone = claims["user_id"] == AGENT_ID and "service" in claims["roles"]
        if not (acting_for_customer or agent_alone):
            return None
        return AccessToken(
            token=token,
            client_id=AGENT_ID,
            scopes=[],
            expires_at=int(claims["exp"]),
            claims=claims,
        )
