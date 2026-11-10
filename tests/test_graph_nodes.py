from __future__ import annotations

from graph.agent import app, container, react_agent, store
from graph.prompts import SYSTEM_PROMPT


def test_main_agent_is_the_support_agent() -> None:
    agent = react_agent._agent
    assert agent.model == "gemini-2.5-flash"
    assert agent.provider == "google"
    assert agent.trim_context is True
    assert agent.system_prompt[0]["content"] == SYSTEM_PROMPT


def test_tools_come_from_demo_server_with_the_user_attached() -> None:
    tool_node = react_agent._tool_node
    assert tool_node._client is not None
    assert tool_node._pass_user_info_to_mcp is True


def test_knowledge_base_is_search_only_agent_memory() -> None:
    memory = react_agent._agent._memory_config
    assert memory.store is store
    assert memory.user_memory is None
    assert memory.agent_memory.enabled is True


def test_graph_compiles() -> None:
    assert app is not None


def test_container_is_exported_for_10xgraph_json() -> None:
    # 10xgraph.json loads "graph.agent:container"; the server refuses to start without it.
    assert container is not None


async def test_thread_name_comes_from_the_first_message() -> None:
    from graph.thread_name_generator import MyNameGenerator

    name = await MyNameGenerator().generate_name(
        ["My monitor from order A-1002 arrived with a cracked screen."]
    )
    assert name == "Monitor from order, cracked screen"


async def test_thread_name_falls_back_to_a_random_name() -> None:
    from graph.thread_name_generator import MyNameGenerator

    assert await MyNameGenerator().generate_name(["Hi"])
    assert await MyNameGenerator().generate_name([])
