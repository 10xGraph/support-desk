import os
from datetime import datetime

from tenxgraph.core.state import MessageContextManager
from tenxgraph.prebuilt.agent import ReactAgent
from tenxgraph.storage.checkpointer import PgCheckpointer
from tenxgraph.storage.store import PgVectorStore
from tenxgraph.storage.store import GoogleEmbedding
from dotenv import load_dotenv
from injectq import InjectQ

from graph.state import WeatherState
from graph.tools.weather_tool import get_weather
from graph.validators.manager import callback_manager


load_dotenv()

# Storage is chosen at init; run `10xgraph config` to review or change it.
# Durable thread state: Postgres keeps every thread, Redis caches the hot ones.
# Set DATABASE_URL and REDIS_URL in .env (see .env.example). The tables are created (or
# upgraded) when the server starts, so a fresh database needs no setup step.
checkpointer = PgCheckpointer(
    postgres_dsn=os.getenv("DATABASE_URL"),
    redis_url=os.getenv("REDIS_URL"),
)

# Long-term memory in the same Postgres (pgvector).
store = PgVectorStore(
    embedding=GoogleEmbedding(),
    dsn=os.getenv("DATABASE_URL"),
)

# Dependency injection container; 10xgraph.json points at it ("injectq": "graph.agent:container").
container = InjectQ.get_instance()

context_manager = MessageContextManager(
    max_messages=20,  # last 20 user messages will be kept in context
    remove_tool_msgs=True,
)

react_agent = ReactAgent(
    state=WeatherState(),
    model="gemini-2.5-flash",
    provider="google",
    system_prompt=[
        {
            "role": "system",
            "content": """
                You are a helpful assistant.
                Your task is to assist the user in finding information and answering questions.
                User Current Location: {user_location}
                If missing information, ask the user for clarification.
                Use tools when they help answer the user.
            """,
        },
        {
            "role": "user",
            "content": f"Today Date is {datetime.now().strftime('%Y-%m-%d')}",
        },
    ],
    trim_context=True,
    tools=[get_weather],
    context_manager=context_manager,
    container=container,
)

app = react_agent.compile(
    checkpointer=checkpointer,
    store=store,
    callback_manager=callback_manager,
)
