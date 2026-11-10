"""Signed-in customers for the evals, shaped like the identity the API builds from a JWT.

The run config carries one as config["user"]: the lifecycle hook reads the name and company
from it, and demo_server refuses tool calls without a customer.
"""

from tenxgraph.qa.evaluation import SessionInput


def customer(user_id: str, name: str, org_id: str) -> dict:
    return {
        "user_id": user_id,
        "tenant": {"org_id": org_id},
        "roles": ["member"],
        "claims": {"name": name},
    }


ALICE = customer("alice", "Alice Chen", "acme")
BOB = customer("bob", "Bob Ray", "globex")


def session(user: dict) -> SessionInput:
    """Session for an eval case run as this customer."""
    return SessionInput(user_id=user["user_id"], config={"user": user})
