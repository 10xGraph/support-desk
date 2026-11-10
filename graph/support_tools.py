"""The support agent's tools: lookup_order, refund_order, create_ticket from demo_server (MCP)."""

import os
import time
import uuid
from collections.abc import Generator

import httpx2
import jwt
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


SERVICE_ID = "support-agent"


class ServiceTokenAuth(httpx2.Auth):
    """Signs a fresh 5-minute service JWT for every request to the demo_server MCP endpoint.

    demo_server checks it with the same JWT_SECRET_KEY, then reads the customer from the
    request metadata that 10xGraph attaches (pass_user_info_to_mcp).
    """

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:
        now = int(time.time())
        claims = {
            "user_id": SERVICE_ID,
            "roles": ["service"],
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + 300,
        }
        token = jwt.encode(
            claims, os.environ["JWT_SECRET_KEY"], algorithm=os.getenv("JWT_ALGORITHM", "HS256")
        )
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


mcp_client = Client(
    StreamableHttpTransport(
        os.getenv("DEMO_MCP_URL", "http://localhost:8100/mcp/"), auth=ServiceTokenAuth()
    )
)
