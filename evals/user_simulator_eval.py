"""
User simulator evaluation example.

The CLI detects get_scenarios() and handles everything:
  - runs each scenario through UserSimulator
  - scores goal achievement with an LLM judge
  - produces the same JSON report as regular eval cases

You only need to define your scenarios. No asyncio, no EvalSetBuilder, no boilerplate.

Usage:
    10xgraph eval evals/user_simulator_eval.py
    10xgraph eval evals/user_simulator_eval.py --parallel --max-concurrency 4

Each scenario runs as a signed-in customer (config={"user": ...}, evals/customers.py), like a
real chat through the API. Needs the stack running and GOOGLE_API_KEY.
"""

from tenxgraph.qa.evaluation import ConversationScenario, UserSimulatorConfig

from evals.customers import ALICE


# ---------------------------------------------------------------------------
# Agent — the CLI reads `app` from this module if present, otherwise it loads
# the graph from 10xgraph.json ("agent": "graph.agent:app") automatically.
# Uncomment and set this if you want to target a specific graph:
#
#   from graph.agent import app
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Optional: override the simulator model and settings for this file.
# If omitted, the CLI uses UserSimulatorConfig defaults (gemini-2.5-flash).
# The provider prefix picks the SDK ("gemini/", "openai/", "anthropic/").
# ---------------------------------------------------------------------------
SIMULATOR_CONFIG = UserSimulatorConfig(
    model="gemini/gemini-2.5-flash",
    max_invocations=8,
    temperature=0.7,
)


# ---------------------------------------------------------------------------
# Scenarios — the only thing you need to write.
# ---------------------------------------------------------------------------


def get_scenarios() -> list[ConversationScenario]:
    return [
        ConversationScenario(
            scenario_id="large_refund_waits_for_staff",
            description="Customer wants a refund for a broken monitor (order A-1002, $250)",
            starting_prompt="My monitor from order A-1002 arrived with a cracked screen.",
            conversation_plan=(
                "1. Ask for a full refund\n"
                "2. Ask when the money will arrive\n"
                "3. Ask what the warranty covers"
            ),
            goals=[
                "The agent looks up order A-1002 before refunding",
                "User is told the refund waits for staff approval and is not paid yet",
                "User gets the warranty terms from the knowledge base",
            ],
            max_turns=8,
            config={"user": ALICE},
        ),
        ConversationScenario(
            scenario_id="product_help_then_human",
            description="Customer cannot pair a headset and then asks for a person",
            starting_prompt="My Acme headset will not connect to my laptop.",
            conversation_plan=(
                "1. Follow the pairing steps\n"
                "2. Say it still does not work\n"
                "3. Ask to talk to a person"
            ),
            goals=[
                "User receives the pairing steps from the knowledge base",
                "A ticket is created for a human and the user gets its number",
            ],
            max_turns=8,
            config={"user": ALICE},
        ),
    ]
