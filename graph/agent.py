import os

from dotenv import load_dotenv
from injectq import InjectQ
from tenxgraph.core.state import Message, MessageContextManager
from tenxgraph.prebuilt.agent import ReactAgent
from tenxgraph.runtime.publisher import RabbitMQPublisher
from tenxgraph.storage.checkpointer import PgCheckpointer
from tenxgraph.storage.store import (
    AgentMemoryConfig,
    GoogleEmbedding,
    MemoryConfig,
    PgVectorStore,
)

from graph.prompts import CONTEXT_PROMPT, SYSTEM_PROMPT
from graph.state import SupportState
from graph.validators.manager import callback_manager


load_dotenv()

# Imported after load_dotenv(): support_tools reads DEMO_MCP_URL when the module loads.
from graph.support_tools import demo_server_auth, mcp_client  # noqa: E402


# Every thread and knowledge-base row carries the caller's company, from the token's org_id
# claim (auth.tenant_claims in 10xgraph.json). Checkpointer and store must declare the same.
TENANT_COLUMNS = {"org_id": "text"}

# The knowledge base is the agent's shared memory: owned by the reserved user
# "__system__:support-agent", one set of articles per company. deploy/scripts/seed_knowledge_base.py
# loads it at startup.
KB_AGENT_ID = "support-agent"
KB_COLLECTION = "knowledge_base"
KB_MEMORY_TYPE = "semantic"
KB_CATEGORY = "kb"

# Postgres connections per pool, in every process that loads this module (API workers, task
# workers, the seed step, evals). asyncpg's default keeps 10 open per pool even when idle, which
# fills Postgres' 100 connections once the API, a worker and an eval run side by side.
# PG_POOL_MAX raises the cap (the load-test stack sets it).
PG_POOL_CONFIG = {"min_size": 1, "max_size": int(os.getenv("PG_POOL_MAX", "5"))}

# Threads: Postgres keeps every thread, Redis caches the hot ones.
checkpointer = PgCheckpointer(
    postgres_dsn=os.getenv("DATABASE_URL"),
    redis_url=os.getenv("REDIS_URL"),
    tenant_columns=TENANT_COLUMNS,
    pool_config=PG_POOL_CONFIG,
)

# Knowledge base in the same Postgres (pgvector). 768 dimensions: pgvector's HNSW index takes
# at most 2000, and the model's default of 3072 would leave the table without an index.
store = PgVectorStore(
    embedding=GoogleEmbedding(output_dimensionality=768),
    dsn=os.getenv("DATABASE_URL"),
    tenant_columns=TENANT_COLUMNS,
    pool_config=PG_POOL_CONFIG,
)

# Graph events (node starts, tool calls, results) to RabbitMQ exchange "tenxgraph.events". The
# API adds the Phoenix tracer from "observability" in 10xgraph.json next to it.
events = RabbitMQPublisher({"url": os.getenv("BROKER_URL")})

# Dependency injection container; 10xgraph.json points at it ("injectq": "graph.agent:container").
container = InjectQ.get_instance()


# Load testing only: with LLM_MOCK_URL set (deploy/llmock, `docker compose --profile llmock`),
# the agent talks to an LLMock server in Anthropic format instead of Gemini. Tools, storage,
# publisher and tracing stay real. Reasoning is off: the mock ignores it.
LLM_MOCK_URL = os.getenv("LLM_MOCK_URL")
if LLM_MOCK_URL:
    llm_settings = {
        "model": "claude-mock",
        "provider": "anthropic",
        "base_url": LLM_MOCK_URL,
        "api_key": "mock",
        "reasoning_config": None,
    }
else:
    llm_settings = {"model": "gemini-2.5-flash", "provider": "google"}

react_agent = ReactAgent(
    state=SupportState(),
    **llm_settings,
    system_prompt=[
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
    ],
    # Changing per-request context (date, last refund, last ticket) goes after the history so
    # the system prompt and history stay a stable, cacheable prefix. Filled from the state.
    extra_messages=[
        Message.text_message(CONTEXT_PROMPT, role="user"),
    ],
    client=mcp_client,
    # Each MCP call carries a 60-second token naming the customer, signed by this agent.
    mcp_auth=demo_server_auth,
    memory=MemoryConfig(
        store=store,
        user_memory=None,
        agent_memory=AgentMemoryConfig(
            enabled=True,
            agent_id=KB_AGENT_ID,
            collection=KB_COLLECTION,
            memory_type=KB_MEMORY_TYPE,
            category=KB_CATEGORY,
        ),
    ),
    trim_context=True,
    context_manager=MessageContextManager(
        max_messages=20,
        remove_tool_msgs=True,
    ),
    container=container,
    publisher=events,
)

if os.getenv("LOAD_TEST_AGENT") == "1" and not LLM_MOCK_URL:
    # Load and security testing: same API, auth and storage, no LLM (graph/load_test_agent.py).
    # LLM_MOCK_URL wins: it runs the real agent against the mock LLM.
    from graph.load_test_agent import build_load_test_graph

    app = build_load_test_graph(publisher=events, container=container).compile(
        checkpointer=checkpointer,
        store=store,
        callback_manager=callback_manager,
    )
else:
    app = react_agent.compile(
        checkpointer=checkpointer,
        store=store,
        callback_manager=callback_manager,
    )
