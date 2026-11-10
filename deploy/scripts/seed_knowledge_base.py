"""Load the support agent's knowledge base into Postgres (pgvector), for every company.

Run once when the stack starts, before the API serves traffic (from the project root):
    .venv/bin/python deploy/scripts/seed_knowledge_base.py

Needs DATABASE_URL and GOOGLE_API_KEY (read from .env by graph.agent). Safe to run on every
start: each article has a stable memory_key, so a rerun updates it in place.
"""

import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # make `graph` importable

from tenxgraph.core.authz import Identity, Reach
from tenxgraph.storage.store import BaseStore, MemoryType, system_user_id

from graph.agent import (
    KB_AGENT_ID,
    KB_CATEGORY,
    KB_COLLECTION,
    KB_MEMORY_TYPE,
    store,
)


# Articles per company (org_id), matching the products in demo_server's orders.
KNOWLEDGE_BASE: dict[str, dict[str, str]] = {
    "acme": {
        "acme-headset-pairing": (
            "Acme wireless headset pairing: hold the power button for 5 seconds until the light "
            "flashes blue and red, then pick 'Acme Headset' in your device's Bluetooth list. "
            "If it does not appear, charge it for 30 minutes and try again."
        ),
        "acme-monitor-no-signal": (
            "Acme 27-inch monitor shows 'No signal': check that the cable is in the port named in "
            "the input menu (Menu > Input), try another cable, and update the graphics driver. "
            "A monitor that arrived with a cracked screen is covered for a full refund."
        ),
        "acme-dock-display": (
            "Acme USB-C dock does not drive two displays: the laptop's USB-C port must support "
            "DisplayPort Alt Mode. Use the dock's own power adapter, not laptop power alone."
        ),
        "acme-refund-policy": (
            "Acme refunds: refunds up to $100 are issued at once. Larger refunds are reviewed by "
            "our support staff, usually within one business day. One refund per order."
        ),
        "acme-warranty": (
            "Acme hardware has a 2 year warranty against defects. Water damage and drops are "
            "not covered."
        ),
    },
    "globex": {
        "globex-keyboard-keys": (
            "Globex mechanical keyboard: a key that repeats or does not register usually needs "
            "cleaning. Pull the keycap with the included tool and blow out dust. Firmware "
            "updates are in the Globex app under Devices."
        ),
        "globex-desk-calibration": (
            "Globex standing desk calibration: lower the desk fully, then hold the down button "
            "for 10 seconds until it beeps twice. Calibration takes under a minute."
        ),
        "globex-desk-error": (
            "Globex standing desk error E01 means a motor overheated: leave the desk for 20 "
            "minutes. Error E04 means an obstacle was detected: clear the area and recalibrate."
        ),
        "globex-refund-policy": (
            "Globex refunds: refunds up to $100 are issued at once. Larger refunds need approval "
            "from our support staff. One refund per order."
        ),
        "globex-returns": "Globex accepts returns within 30 days if the box is unopened.",
    },
}


def kb_config(org_id: str) -> dict:
    """Write config matching what the agent searches: the agent's reserved owner, the KB
    collection, and the company as the tenant column."""
    owner = system_user_id(KB_AGENT_ID)
    identity = Identity(user_id=owner, kind="system", tenant={"org_id": org_id}, reach=Reach.OWN)
    return {"user": identity, "user_id": owner, "collection": KB_COLLECTION}


async def seed(kb_store: BaseStore) -> int:
    count = 0
    for org_id, articles in KNOWLEDGE_BASE.items():
        for key, text in articles.items():
            await kb_store.astore(
                kb_config(org_id),
                text,
                memory_type=MemoryType(KB_MEMORY_TYPE),
                category=KB_CATEGORY,
                memory_key=key,
            )
            count += 1
    return count


async def main() -> None:
    await store.asetup()
    try:
        count = await seed(store)
    finally:
        await store.arelease()
    print(f"Knowledge base: {count} articles for {', '.join(KNOWLEDGE_BASE)}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
