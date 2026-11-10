from tenxgraph.core import AgentState


class SupportState(AgentState):
    """Thread state of the support agent: the conversation only.

    Orders, refunds and tickets live in demo_server and are reached through its MCP tools.
    """
