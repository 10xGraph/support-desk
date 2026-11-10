"""Demo company systems: REST API for people, MCP server at /mcp/ for the agent.

Run: uvicorn demo_server.main:app --port 8100
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from demo_server import db
from demo_server.mcp_server import mcp
from demo_server.routes import router


# Endpoint at "/" inside the mount, so the URL is /mcp/. Stateless: no sessions between calls.
mcp_app = mcp.http_app(path="/", stateless_http=True, json_response=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    try:
        await db.init_db()
        async with mcp_app.lifespan(app):
            yield
    finally:
        await db.close()


app = FastAPI(
    title="Support desk demo systems",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(router)
app.mount("/mcp", mcp_app)
