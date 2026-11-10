from tenxgraph.qa.evaluation import (
    CriteriaConfig,
    CriterionConfig,
    EvalConfig,
    EvalSet,
    EvalSetBuilder,
    MatchType,
)
from tenxgraph.qa.evaluation.config.presets import EvalPresets


def get_eval_config() -> EvalConfig:
    """Evaluation config for this file.

    EvalPresets provides ready-made criterion bundles.  Pick one that matches
    what your agent does, or call EvalPresets.combine() to mix them.

    Available presets:
        EvalPresets.response_quality()   - LLM judge on response accuracy
        EvalPresets.tool_usage()         - checks tool names + trajectory (no LLM)
        EvalPresets.conversation_flow()  - multi-turn conversation evaluation
        EvalPresets.comprehensive()      - all of the above combined
        EvalPresets.quick_check()        - fast ROUGE-based response check, no LLM cost

    This file checks, without any LLM call, every expectation the cases below set:
        - tool names and arguments           (tool_usage)
        - the expected final response        (quick_check, ROUGE-1 word overlap)
        - the expected node order            (node_order, extra nodes allowed)
    """
    return EvalPresets.combine(
        EvalPresets.tool_usage(threshold=0.6),
        EvalPresets.quick_check(),
        EvalConfig(
            criteria=CriteriaConfig(
                node_order=CriterionConfig.node_order(match_type=MatchType.IN_ORDER),
            )
        ),
    )


def get_eval_set() -> EvalSet:
    """Needs demo_server running and a run config with a user of company acme: demo_server
    refuses MCP calls without a customer identity."""
    return (
        EvalSetBuilder(name="support-agent-regression")
        .add_case(
            query="Hi",
            expected="Hello! How can I help you today?",
            expected_node_order=["MAIN"],
            name="greeting_response",
            description="The agent responds to a greeting.",
        )
        .add_tool_test(
            query="What is the status of order A-1001?",
            tool_name="lookup_order",
            tool_args={"order_id": "A-1001"},
            expected_response="Order A-1001: Wireless headset, $45.00, delivered.",
            case_id="lookup_order",
        )
        .add_tool_test(
            query="Please refund order A-1001 in full, the headset stopped working.",
            tool_name="refund_order",
            tool_args={"order_id": "A-1001", "amount": 45.0},
            expected_response="Refund of $45.00 for order A-1001 issued.",
            case_id="small_refund",
        )
        .add_tool_test(
            query="I want to talk to a person.",
            tool_name="create_ticket",
            tool_args={"needs_human": True},
            expected_response="I have opened a ticket for you.",
            case_id="human_ticket",
        )
        .build()
    )
