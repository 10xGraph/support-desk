from __future__ import annotations

import importlib.util
from pathlib import Path

from tenxgraph.core.authz import Reach
from tenxgraph.storage.store import system_user_id

from graph.agent import KB_AGENT_ID, KB_CATEGORY, KB_COLLECTION


_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "scripts" / "seed_knowledge_base.py"
_spec = importlib.util.spec_from_file_location("seed_knowledge_base", _SCRIPT)
seed_kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_kb)


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str, dict]] = []

    async def astore(self, config, content, **kwargs) -> str:
        self.calls.append((config, content, kwargs))
        return "id"


async def test_seeds_every_company() -> None:
    store = RecordingStore()
    count = await seed_kb.seed(store)

    assert count == sum(len(a) for a in seed_kb.KNOWLEDGE_BASE.values())
    orgs = {config["user"].tenant["org_id"] for config, _, _ in store.calls}
    assert orgs == set(seed_kb.KNOWLEDGE_BASE)


async def test_articles_land_where_the_agent_searches() -> None:
    store = RecordingStore()
    await seed_kb.seed(store)

    for config, content, kwargs in store.calls:
        org_id = config["user"].tenant["org_id"]
        assert config["user"].user_id == system_user_id(KB_AGENT_ID)
        assert config["user"].reach == Reach.OWN
        assert config["collection"] == KB_COLLECTION
        assert kwargs["category"] == KB_CATEGORY
        assert seed_kb.KNOWLEDGE_BASE[org_id][kwargs["memory_key"]] == content
