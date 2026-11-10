"""Lifecycle hooks for the support agent graph."""

import logging
import re
from datetime import UTC, datetime
from typing import Any

from tenxgraph.core.authz import get_identity
from tenxgraph.core.state.message import Message
from tenxgraph.core.state.message_block import ToolResultBlock
from tenxgraph.utils.callbacks import GraphLifecycleContext, GraphLifecycleHook

from graph.state import SupportState


logger = logging.getLogger(__name__)

TICKET_ID = re.compile(r"Ticket ([A-Z0-9_-]+-\d+) created")


class AgentLifecycleHook(GraphLifecycleHook[SupportState]):
    async def on_graph_start(
        self,
        context: GraphLifecycleContext,
        state: SupportState,
    ) -> SupportState | None:
        """Copy who is calling from the verified token (config["user"]) and today's date into
        the state.

        Runs on every run, so a value a client wrote into the state is replaced.
        """
        state.today = datetime.now(UTC).date().isoformat()
        identity = get_identity(context.config)
        if identity is None:
            return state
        state.user_id = identity.user_id
        state.user_name = str(identity.claims.get("name") or identity.user_id)
        state.org_id = identity.tenant.get("org_id", "")
        return state

    async def on_graph_end(
        self,
        context: GraphLifecycleContext,
        final_state: SupportState,
        messages: list[Message],
        total_steps: int,
    ) -> SupportState | None:
        """Called after successful graph completion, before final state sync.

        Return a modified SupportState to persist, or None to keep the current state.
        """
        return None

    async def on_graph_error(  # noqa: PLR0913
        self,
        context: GraphLifecycleContext,
        error: Exception,
        partial_state: SupportState,
        messages: list[Message],
        step: int,
        node_name: str,
    ) -> tuple[SupportState, str] | None:
        """Called when an unhandled error escapes the execution loop.

        Return (modified_state, error_message) to change the persisted error snapshot,
        or None to keep the current error state. The exception is always re-raised.
        """
        return None

    async def on_interrupt(
        self,
        context: GraphLifecycleContext,
        interrupted_node: str,
        interrupt_type: str,
        state: SupportState,
    ) -> SupportState | None:
        """Called when execution pauses at an interrupt point.

        Return a modified SupportState to persist at interrupt, or None to keep the current state.
        In-place mutation of the passed state is also supported.
        """
        return None

    async def on_resume(
        self,
        context: GraphLifecycleContext,
        resumed_node: str,
        state: SupportState,
        resume_data: dict[str, Any],
    ) -> SupportState | None:
        """Called when a previously interrupted execution is about to resume.

        Called before clear_interrupt(). Return a modified SupportState to continue with,
        or None to use the loaded state unchanged.
        """
        return None

    async def on_checkpoint(
        self,
        context: GraphLifecycleContext,
        state: SupportState,
        messages: list[Message],
        is_context_trimmed: bool,
    ) -> tuple[SupportState, list[Message]] | SupportState | None:
        """Called before every durable checkpoint write.

        Return (state, messages) to modify both, SupportState to modify state only,
        or None to persist without modification.
        """
        return None

    async def on_state_update(
        self,
        context: GraphLifecycleContext,
        node_name: str,
        old_state: SupportState,
        new_state: SupportState,
        step: int,
    ) -> SupportState | None:
        """After the tool node: remember the latest refund status and ticket id."""
        if node_name != "TOOL":
            return None
        for message in new_state.context:
            if message.role != "tool":
                continue
            for block in message.content:
                if not isinstance(block, ToolResultBlock) or not isinstance(block.output, str):
                    continue
                if block.name == "refund_order":
                    new_state.last_refund_status = block.output
                elif block.name == "create_ticket" and (match := TICKET_ID.search(block.output)):
                    new_state.last_ticket_id = match.group(1)
        return new_state
