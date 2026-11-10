<!-- 10xgraph:start -->
## 10xGraph

This project is built on 10xGraph (`10xgraph`, `10xgraph-api`). Before you write or change agent,
graph, tool or `10xgraph.json` code, load the `10xgraph` skill (.claude/skills/10xgraph) and read the
reference file it points to. Tell every subagent you start to do the same.

- Start from a prebuilt agent: `ReactAgent` for a tool-calling agent. Hand-write a `StateGraph`
  only when no prebuilt agent fits, and say why.
- Build one agent unless the user asks for more. Do not add routers, handoffs, guard nodes or
  approval nodes the user did not ask for.
- Business data and rules belong in tools and the systems they call (APIs, MCP servers,
  databases), not in graph nodes or state.
- MCP: pass the signed-in user with `pass_user_info_to_mcp=True`. The MCP server reads it from
  `ctx.request_context.meta["user"]`. Never add `user`, `user_id`, `org_id` or tenant
  arguments to MCP tools.
- Do not work around 10xGraph bugs in app code (subclassing ToolNode, overriding private
  methods). Report them instead.
<!-- 10xgraph:end -->

## This project: support desk demo

One support agent for two demo companies (`acme`, `globex`, JWT claim `org_id`).

- `graph/agent.py`: one `ReactAgent`. Tools come from demo_server over MCP (`lookup_order`,
  `refund_order`, `create_ticket`), called with a 5-minute service JWT plus the customer in
  MCP metadata. The knowledge base is search-only agent memory (`agent_memory_tool`) in
  PgVectorStore with Google embeddings, one set of articles per company.
- `graph/prompts.py`: the system prompt. `graph/state.py`: `SupportState` (conversation only).
- `deploy/scripts/seed_knowledge_base.py`: loads the knowledge base for every company. It runs
  at stack start, before the API; it is seed data, not an agent tool or a worker task.
- `worker/tasks.py`: background jobs (the template's for now), not the knowledge base.
- `demo_server/`: the company's systems (orders, refunds, tickets in Postgres schema `demo`),
  a plain FastAPI app with REST for people and MCP for the agent. The business rules live
  there (refunds up to $100 issued at once, larger ones pending until staff approve, one
  refund per order).
- Core and API are installed editable from `../agentflow` and `../agentflow-api`.

Keep it this small. Do not add agents, nodes or rules to the graph; put rules in demo_server.
