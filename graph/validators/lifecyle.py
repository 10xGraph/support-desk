"""Lifecycle hooks for the support agent graph."""

import logging
from typing import Any

from tenxgraph.core.state.message import Message
from tenxgraph.utils.callbacks import GraphLifecycleContext, GraphLifecycleHook

from graph.state import SupportState


logger = logging.getLogger(__name__)


class AgentLifecycleHook(GraphLifecycleHook[SupportState]):
    async def on_graph_start(
        self,
        context: GraphLifecycleContext,
        state: SupportState,
    ) -> SupportState | None:
        """Hydrate ``SupportState`` from the org config attached by AgentAuth."""
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
        """Called after each node's result is merged into state.

        Return a modified SupportState to replace new_state, or None to use new_state unchanged.
        """
        return None
