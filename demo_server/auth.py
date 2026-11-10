"""JWT checks, using the same secret and claims as the 10xGraph API.

Claims: user_id, roles (list), org_id; exp is required. Staff are support, org_admin and admin.
The agent calls /mcp with a token whose roles contain "service".
"""

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp.server.auth import AccessToken, TokenVerifier


STAFF_ROLES = {"support", "org_admin", "admin"}

bearer = HTTPBearer(auto_error=False)


def decode_token(token: str) -> dict[str, Any]:
    """Return the claims of a valid token, or raise jwt.InvalidTokenError."""
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not set.")
    claims = jwt.decode(
        token,
        secret,
        algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
        options={"require": ["exp"]},
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


class ServiceTokenVerifier(TokenVerifier):
    """MCP bearer check: only a valid token with the "service" role gets through."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = decode_token(token)
        except jwt.InvalidTokenError:
            return None
        if "service" not in claims["roles"]:
            return None
        return AccessToken(
            token=token,
            client_id=str(claims["user_id"]),
            scopes=[],
            expires_at=int(claims["exp"]),
            claims=claims,
        )
