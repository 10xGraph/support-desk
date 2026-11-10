from tenxgraph.core import AgentState


class SupportState(AgentState):
    """Thread state of the support agent.

    Filled by the lifecycle hook (graph/validators/lifecyle.py) and shown to the model through
    {placeholders} in graph/prompts.py.

    Orders, refunds and tickets themselves live in demo_server; these are only reminders for
    the conversation.
    """

    # From the verified token on every run (config["user"]); a client value is overwritten.
    user_id: str = ""
    user_name: str = ""
    org_id: str = ""

    # Set on every run: a date, not a time, so it changes once a day at most.
    today: str = ""

    # From the latest refund_order / create_ticket results in this thread.
    last_refund_status: str = "none"
    last_ticket_id: str = "none"
