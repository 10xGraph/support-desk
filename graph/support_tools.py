"""The support agent's tools: lookup_order, refund_order, create_ticket from demo_server (MCP)."""

import os
import time
import uuid

import jwt
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from tenxgraph.core.graph.tool_node import MCPAuthContext


AGENT_ID = "support-agent"
DEMO_MCP_AUDIENCE = "demo-mcp"  # demo_server accepts this audience on /mcp only
TOKEN_TTL_SECONDS = 60


async def demo_server_auth(ctx: MCPAuthContext) -> dict[str, str]:
    """Headers for one MCP request to demo_server: a short-lived token this agent signs.

    10xGraph calls this before every MCP tool call and tool listing (ToolNode mcp_auth). For a
    tool call the token names the customer as the subject and this agent as the actor (`act`),
    so demo_server verifies who acts for whom from a signed token. The customer's own API token
    is never forwarded: it was issued for this API, not for demo_server.
    """
    now = int(time.time())
    claims = {
        "aud": DEMO_MCP_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    identity = ctx.identity
    if identity is not None and identity.tenant.get("org_id"):
        # On behalf of the signed-in customer, taken from the verified identity.
        claims |= {
            "user_id": identity.user_id,
            "org_id": identity.tenant["org_id"],
            "roles": sorted(identity.roles),
            "act": {"sub": AGENT_ID},
        }
    else:
        # No customer (fetching the tool list): the agent alone, which can list but not act.
        claims |= {"user_id": AGENT_ID, "roles": ["service"]}
    token = jwt.encode(
        claims, os.environ["JWT_SECRET_KEY"], algorithm=os.getenv("JWT_ALGORITHM", "HS256")
    )
    return {"Authorization": f"Bearer {token}"}


mcp_client = Client(
    StreamableHttpTransport(
        os.getenv(
            "DEMO_MCP_URL",
            "http://localhost:8100/mcp/",
        )
    )
)
