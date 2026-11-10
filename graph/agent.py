import os

from dotenv import load_dotenv
from injectq import InjectQ
from tenxgraph.core.state import MessageContextManager
from tenxgraph.prebuilt.agent import ReactAgent
from tenxgraph.storage.checkpointer import PgCheckpointer
from tenxgraph.storage.store import (
    AgentMemoryConfig,
    GoogleEmbedding,
    MemoryConfig,
    PgVectorStore,
)

from graph.prompts import SYSTEM_PROMPT
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

# Threads: Postgres keeps every thread, Redis caches the hot ones.
checkpointer = PgCheckpointer(
    postgres_dsn=os.getenv("DATABASE_URL"),
    redis_url=os.getenv("REDIS_URL"),
    tenant_columns=TENANT_COLUMNS,
)

# Knowledge base in the same Postgres (pgvector). 768 dimensions: pgvector's HNSW index takes
# at most 2000, and the model's default of 3072 would leave the table without an index.
store = PgVectorStore(
    embedding=GoogleEmbedding(output_dimensionality=768),
    dsn=os.getenv("DATABASE_URL"),
    tenant_columns=TENANT_COLUMNS,
)

# Dependency injection container; 10xgraph.json points at it ("injectq": "graph.agent:container").
container = InjectQ.get_instance()


react_agent = ReactAgent(
    state=SupportState(),
    model="gemini-2.5-flash",
    provider="google",
    system_prompt=[{"role": "system", "content": SYSTEM_PROMPT}],
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
    context_manager=MessageContextManager(max_messages=20, remove_tool_msgs=True),
    container=container,
)

app = react_agent.compile(
    checkpointer=checkpointer,
    store=store,
    callback_manager=callback_manager,
)
