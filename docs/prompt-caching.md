# Prompt caching: how to lay out an agent's prompt

LLM providers bill cached input tokens at a large discount (Gemini on Vertex AI: 90% off), and
cached input is also faster. Whether a call hits the cache depends only on how the request is
ordered. This page explains the mechanism, the layout this agent uses, and the provider rules.

## How the cache works

- The cache is keyed by the **exact tokens at the start of the request**, not by user, thread
  or API call. The serving system hashes the token sequence prefix and reuses the work it
  already did for that prefix. Open-source servers document this as "automatic prefix caching"
  (vLLM) and "RadixAttention" (SGLang); the hosted providers behave the same way.
- Matching stops at the **first token that differs**. Everything after it is billed as new
  input, even if it is identical to an earlier request.
- Every distinct prefix is its own cache entry. Users with different system prompts get
  separate entries, side by side; nothing is overwritten.
- Entries are kept per account (OpenAI, Gemini) or per workspace (Anthropic, per secondary
  sources). All end users of this app share them, because all calls use one key. Entries expire
  when unused; the lifetime is provider-specific and not guaranteed.

Request order is always: tools, then system prompt, then messages.

## The layout

```
1. instructions          same for every user          -> shared across users
2. per-thread data       fixed for this conversation  -> cached for this thread
3. history               grows, never rewritten       -> cached turn by turn
4. dynamic context       changes during the thread    -> the only part re-billed
```

| Data | Changes mid-conversation? | Slot |
|---|---|---|
| Rules, tone, tool usage | No, same for all users | 1, top of the system prompt |
| Customer name, id, company; a candidate's CV and JD | No, but differs per user | 2, end of the system prompt (or the first saved message) |
| Messages and tool results | Appended only | 3 |
| Today's date, last refund, last ticket, current step | Yes | 4, a small message after the history |

Rules:

1. **Nothing that changes mid-conversation goes into the system prompt.** One change re-bills
   the whole thread, including all history after it.
2. **Large fixed data goes in slot 2, never slot 4.** Slot 4 is rebuilt on every call, so a
   3,000-token CV there is billed in full on every turn.
3. **Slot 4 is never saved to the thread.** Next call it moves to the new end; the history
   stays byte-identical. The only tokens re-billed per call are slot 4's own.
4. **Slot 4 is a `role: "user"` message.** The 10xGraph Gemini adapter moves every
   `role: "system"` message into `system_instruction` and the Anthropic adapter into the
   top-level `system=`; both are sent first, which breaks the cache again.
5. **Dates, not timestamps.** A time precise to the second changes on every call.
6. **Fence slot 4** (`<conversation_context>...</conversation_context>`) and say in the system
   prompt that it is reference data, not instructions.

Why slot 4 goes after the history and not before the latest user message: placed at the very
end, only its own tokens are re-billed. Placed before the latest user message, every new turn
also re-bills the previous turn's messages, because their position shifts when the old block
is dropped.

## Several users at once

```
A, turn 3:  [tools][system prompt][A's history .....][A context]
B, turn 1:  [tools][system prompt][B's message][B context]
            └── identical tokens ──┘└── differs from here on ──┘
```

- The shared part (tools + static instructions) is cached once and reused by every user, if it
  is above the provider's minimum size (below).
- Each user's history is cached separately and helps only that user's next turn.
- With per-user system prompts (a CV and JD per candidate), each interview still caches its own
  prefix from turn 2 on. Only the first call of each user pays full price for it. Put the
  common instructions first, so that part is still shared.

The minimum size applies to the cached prefix as a whole. Within one conversation it is
reached quickly (instructions + per-thread data + history). It only decides whether the
instructions alone are shared across users. This agent's static part is small (likely under
1,024 tokens), so it caches per thread, not across users.

## Provider rules

| | OpenAI | Gemini (implicit) | Anthropic |
|---|---|---|---|
| Turn on | Automatic | Automatic on 2.5 and newer | `cache_control` breakpoints, or top-level automatic mode |
| Minimum | 1,024 tokens, then 128-token steps | 1,024 (2.5 Flash), 4,096 (2.5 Pro) | Per model: check the official "Cache limitations" table (sources disagree, 512 to 4,096) |
| Parallel requests | Routed by prefix hash + `prompt_cache_key`; above ~15 requests/min per prefix and key, traffic spills to other machines and hit rate drops | Send similar prefixes close together; hits not guaranteed | An entry is usable only after the first response begins: simultaneous cold requests all miss |
| Read hits from | `usage.prompt_tokens_details.cached_tokens` | `usage_metadata.cached_content_token_count` | `usage.cache_read_input_tokens` |

Anthropic notes:

- Automatic mode puts the breakpoint on the last block (the conversation). To share the
  instructions across users, add an explicit breakpoint at the end of the instructions; add
  another after per-thread data. Maximum 4 breakpoints per request.
- Only about 20 blocks before a breakpoint are checked; long prompts need more breakpoints.
- Writing a cache entry costs more than normal input; reads are discounted.

OpenAI note: a per-user or per-session `prompt_cache_key` raises each user's history hits but
keeps different users' shared-prefix entries on different machines.

## How this agent does it (10xGraph)

- `graph/prompts.py` `SYSTEM_PROMPT`: static rules first, then the customer block (name,
  customer id, company), which is fixed for the thread. `{placeholders}` are filled from
  `SupportState` by `str.format` before each model call.
- `graph/prompts.py` `CONTEXT_PROMPT`: slot 4 (today's date, last refund, last ticket).
- `graph/validators/lifecyle.py`: fills the state. `on_graph_start` sets the customer fields
  from the verified token and `today`; `on_state_update` sets the last refund and ticket from
  tool results.
- 10xGraph sends `system_prompt`, then the history, then `extra_messages`
  (`tenxgraph/utils/converter.py`), and never saves `extra_messages` to the thread. That is
  exactly slot 4.

**Open item:** 10xGraph fills `{placeholders}` only in `system_prompt`, not in
`extra_messages`, so `CONTEXT_PROMPT` is not attached yet. Once core interpolates
`extra_messages`, pass it as:

```python
from tenxgraph.core.state import Message
from graph.prompts import CONTEXT_PROMPT

ReactAgent(..., extra_messages=[Message.text_message(CONTEXT_PROMPT, role="user")])
```

Until then the model does not see the last refund, last ticket or date.

## Measured on Gemini (2026-11-10)

`cache_experiment.py` at the project root, gemini-2.5-flash, google-genai 3.0.0 (API version
v1beta), about 2,600 tokens of fixed instructions, 2 runs; both runs gave identical numbers.
Raw output: `cache_experiment_results.txt`.

| Scenario | Cached on later calls | Finding |
|---|---|---|
| Identical request, 3 times | 69% | Cached 2,028 of 2,954 tokens: caching goes in blocks of about 1,000 tokens, so up to ~1,000 tail tokens are always billed |
| Context at the end (slot 4) | 41% | Turn by turn: 0, 0, 0, 2,026, 3,033 |
| Context before the latest user message | 41% | The same as at the end, to the token |
| Context inside the system prompt | 33% | Turn 5 cached only 2,021 (the rules); history never cached |
| One system prompt, 3 users | 39% | User B missed, user C reused the shared rules (2,038) |
| Context after a function response | 66% | Accepted, and cached on the second call of the tool loop |

Conclusions:

- End of the request vs before the latest message made no difference here; the gap (the
  previous turn's tokens) was smaller than Gemini's caching block. The end stays the choice:
  equal in practice, better with large tool results, and simpler.
- Changing data in the system prompt does cost cache: it caps the cached prefix at the text
  before the change.
- Gemini accepted a `role: "user"` message right after another user message and right after a
  function response (0 errors in 48 calls). Not tested on Anthropic or OpenAI.
- Implicit caching started late: turns 2 and 3 of a new conversation got no hits even with a
  repeated 2,600-token prefix, while an exact repeat hit on its second call. Google does not
  document when entries are stored. Short conversations may get no caching at all; for large
  shared instructions that must be cached, use Gemini explicit context caching.

## Checking it

Do not assume a layout caches: run two turns of one conversation, and one turn each for two
users, and read the provider's cached-token field (table above). The first call of a new
prefix is always a miss.

## Sources

- OpenAI: [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching),
  [Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201),
  [community: prompt_cache_key routing](https://community.openai.com/t/understanding-prompt-cache-keys-in-query-efficiency/1357382)
- Google: [Gemini API context caching](https://ai.google.dev/gemini-api/docs/caching?lang=rest),
  [Vertex AI context cache](https://cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview),
  [implicit caching announcement](https://developers.googleblog.com/en/gemini-2-5-models-now-support-implicit-caching/)
- Anthropic: [prompt caching](https://platform.claude.com/en/docs/build-with-claude/prompt-caching)
- Practice: [Manus, context engineering for AI agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
