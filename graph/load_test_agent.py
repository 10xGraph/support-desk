"""A stand-in for the support agent that never calls an LLM, for load and security testing.

It runs through the same API, auth, checkpointer, tenant columns and callbacks as the real
agent; only the model call is replaced by a 2-second sleep and a random canned reply. Turn it on
with LOAD_TEST_AGENT=1 (see graph/agent.py). Never enable it for real users.
"""

import asyncio
import random

from tenxgraph.core.graph import StateGraph
from tenxgraph.core.state import Message
from tenxgraph.utils.constants import END

from graph.state import SupportState


# Simulated model latency, in seconds.
FAKE_LATENCY_SECONDS = 2.0

REPLIES = [
    "Thanks for reaching out. I can help with orders, refunds and tickets.",
    "I have looked into that for you. Is there anything else I can help with?",
    "Could you share your order number so I can check it?",
    "I have opened a ticket for this; our team will follow up shortly.",
    "Your request has been noted. Anything else today?",
]


async def fake_reply(state: SupportState) -> Message:
    """Wait like a model would, then answer with a random canned reply."""
    await asyncio.sleep(FAKE_LATENCY_SECONDS)
    return Message.text_message(random.choice(REPLIES), role="assistant")  # noqa: S311  # nosec B311


def build_load_test_graph(**graph_kwargs) -> StateGraph:
    """One node, MAIN -> END, with the support agent's state class."""
    graph = StateGraph(state=SupportState(), **graph_kwargs)
    graph.add_node("MAIN", fake_reply)
    graph.set_entry_point("MAIN")
    graph.add_edge("MAIN", END)
    return graph
