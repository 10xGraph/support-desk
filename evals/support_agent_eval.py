"""Support agent regression: real Gemini, real demo_server, real knowledge base.

Every case runs as a signed-in customer (evals/customers.py), set in the case's run config the
way the API sets it from a verified token.

Needs the stack running (Postgres with the seeded knowledge base, demo_server on DEMO_MCP_URL)
and GOOGLE_API_KEY. Run:

    10xgraph eval evals/support_agent_eval.py

Checks per case:
    trajectory      the tools called, in order, with their arguments when a case names them
    response_match  an LLM judge compares the final answer with the expected one
"""

from tenxgraph.qa.evaluation import (
    CriteriaConfig,
    CriterionConfig,
    EvalConfig,
    EvalSet,
    EvalSetBuilder,
    MatchType,
    ToolCall,
)

from evals.customers import ALICE, BOB, session


def get_eval_config() -> EvalConfig:
    return EvalConfig(
        criteria=CriteriaConfig(
            trajectory=CriterionConfig.trajectory(
                threshold=1.0, match_type=MatchType.IN_ORDER, check_args=True
            ),
            response_match=CriterionConfig.response_match(threshold=0.7),
        )
    )


def get_eval_set() -> EvalSet:
    return (
        EvalSetBuilder(name="support-agent")
        .add_case(
            case_id="greets_by_name",
            query="Hi",
            expected="Hello Alice, how can I help you today?",
            description="The customer's name comes from the sign-in, through the state.",
            session_input=session(ALICE),
        )
        .add_case(
            case_id="order_status",
            query="Where is my order A-1003?",
            expected="Your order A-1003, a USB-C dock for $89.50, has shipped.",
            expected_tools=[ToolCall(name="lookup_order", args={"order_id": "A-1003"})],
            session_input=session(ALICE),
        )
        .add_case(
            case_id="large_refund_is_pending",
            query="My monitor from order A-1002 arrived with a cracked screen. Refund it please.",
            expected=(
                "The $250.00 refund for order A-1002 is waiting for staff approval, usually "
                "within one business day. It is not paid yet."
            ),
            # Looks the order up first. refund_order is not required: one refund per order, so
            # on a second run the lookup already shows the pending refund.
            expected_tools=[ToolCall(name="lookup_order", args={"order_id": "A-1002"})],
            description="Refunds over $100 wait for staff; the agent must not say it is paid.",
            session_input=session(ALICE),
        )
        .add_case(
            case_id="headset_pairing_from_kb",
            query="How do I pair my wireless headset?",
            expected=(
                "Hold the power button for 5 seconds until the light flashes blue and red, then "
                "pick 'Acme Headset' in your Bluetooth list. If it does not appear, charge it "
                "for 30 minutes and try again."
            ),
            expected_tools=[ToolCall(name="agent_memory_tool")],
            session_input=session(ALICE),
        )
        .add_case(
            case_id="asks_for_a_person",
            query="I want to talk to a real person.",
            expected="I have opened a ticket for a person to contact you: ticket ACME-<number>.",
            expected_tools=[ToolCall(name="create_ticket")],
            session_input=session(ALICE),
        )
        .add_case(
            case_id="other_company_order_not_found",
            query="What is the status of order A-1002?",
            expected="I could not find order A-1002.",
            expected_tools=[ToolCall(name="lookup_order", args={"order_id": "A-1002"})],
            description="A-1002 is an acme order; demo_server takes the company from the token.",
            session_input=session(BOB),
        )
        .add_case(
            case_id="desk_error_from_own_kb",
            query="My standing desk shows error E01. What does it mean?",
            expected=(
                "E01 means a motor overheated. Leave the desk for 20 minutes, then use it again."
            ),
            expected_tools=[ToolCall(name="agent_memory_tool")],
            description="Answers from globex's own articles.",
            session_input=session(BOB),
        )
        .build()
    )
