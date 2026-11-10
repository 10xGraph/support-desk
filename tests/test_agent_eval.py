from __future__ import annotations

import asyncio

from tenxgraph.qa import QuickTest
from tenxgraph.qa.evaluation import (
    CriterionResult,
    EvalCaseResult,
    EvalReport,
    EvalSummary,
    ReporterConfig,
    ReporterManager,
)

from evals.weather_agents_eval import get_eval_set


def test_eval_set_covers_core_support_behaviors() -> None:
    eval_set = get_eval_set()

    case_ids = {case.eval_id for case in eval_set.eval_cases}
    case_names = {case.name for case in eval_set.eval_cases}

    assert eval_set.name == "support-agent-regression"
    assert len(eval_set.eval_cases) == 4
    assert "greeting_response" in case_names
    assert {"lookup_order", "small_refund", "human_ticket"} <= case_ids


def test_reporter_writes_html_and_json_artifacts(tmp_path) -> None:
    report = EvalReport(
        eval_set_id="support-agent-regression",
        eval_set_name="support-agent-regression",
        results=[
            EvalCaseResult(
                eval_id="sample",
                name="sample",
                passed=True,
                actual_response="Order A-1001: Wireless headset, $45.00, delivered.",
                criterion_results=[
                    CriterionResult(
                        criterion="response",
                        score=1.0,
                        passed=True,
                        threshold=0.6,
                    )
                ],
            )
        ],
        summary=EvalSummary(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            error_cases=0,
            pass_rate=1.0,
        ),
    )

    output = ReporterManager(
        ReporterConfig(output_dir=str(tmp_path), html=True, json_report=True, console=False)
    ).run_all(report, output_dir=str(tmp_path))

    assert output.json_path is not None
    assert output.html_path is not None
    assert "support-agent-regression" in tmp_path.joinpath(output.json_path).read_text(
        encoding="utf-8"
    )


def test_quick_test_smoke_for_expected_support_greeting() -> None:
    result = QuickTest.single_turn(
        agent_response="Hello! I can help with your orders, refunds and products.",
        user_message="Hi",
    )

    asyncio.run(result).assert_contains("orders").assert_no_errors()
