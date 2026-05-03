# Cursor User Rule: Secure Graph automatic memory

Copy/paste this entire file into **Cursor Settings → Rules → User Rules** (global across all projects).

For the bundled **MCP + hooks + MCP allowlist** installer (same automation as distributed with this prototype), run from the checkout:

`python3 scripts/install_cursor_bundle.py` (see `README.md`).

If you want per-repo behavior instead, copy into that repo’s `.cursor/rules/*.mdc` with `alwaysApply: true` frontmatter.

---

You have access to the MCP server named `secure-graph` (configured in `~/.cursor/mcp.json`). It stores durable memory in SQLite with field-level permissions.

## Automatic writes (hooks)

On this machine, durable **writes** are handled by a **global Cursor hook** in `~/.cursor/hooks.json` (`sessionStart`, `beforeSubmitPrompt`, `afterAgentResponse`) that pairs each user message with the assistant’s final reply and calls `GraphStore.ingest_conversation` against the same SQLite DB as MCP.

You do **not** need to call ingest tools manually just to remember plain user/assistant facts (for example “Jane works at Acme”).

## Automatic reads (hooks)

**Reads** are injected as `additional_context`:

- On **new Composer sessions** (`sessionStart`) — documented hook output; includes an intro plus **recently updated** properties you are allowed to see (sensitive values appear as redacted markers).
- On **each user message** (`beforeSubmitPrompt`) — the hook runs a **semantic match** against the user prompt text and appends the **recent** snapshot. Cursor’s public hook table lists only `{continue, user_message}` for this event; builds that honor extra fields will apply `additional_context` here—if yours does not, you still get the **session-level** injection above.

Tune size with optional environment variables on the Cursor / Composer process (hooks inherit that environment): `SECURE_GRAPH_HOOK_SEMANTIC_LIMIT`, `SECURE_GRAPH_HOOK_RECENT_LIMIT`, `SECURE_GRAPH_HOOK_MAX_CHARS`. The hook script still resolves `SECURE_GRAPH_DB` / agent defaults from `~/.cursor/mcp.json` when they are not set in the environment.

For graph-shaped follow-ups (neighbors, paths, deeper retrieval), still use MCP `semantic_search` / `get_context` when the injected digest is not enough.

## Defaults (do not wait for the user to ask)

Assume:

- Default writer/reader identity is `SECURE_GRAPH_DEFAULT_AGENT_ID` (server default: `cursor_default`).
- You should use memory **proactively** whenever it improves correctness, consistency, or personalization.

## Writes: short-term vs long-term memory

After **material** new information is established (decisions, preferences, facts, TODOs, architectures, bug repros, API contracts, naming choices, etc.), persist it using MCP:

- Prefer `ingest_conversation` when facts are embedded in natural language.
- Prefer `ingest_graph_mutations` when you can emit clean structured nodes/edges/properties.

 Encode memory tier on nodes as properties:

- `memory.tier`: `short_term` or `long_term`
- Optional: `memory.expires_at` (ISO-8601) for scratch/draft/state that should expire
- Optional: `topic`, `confidence`, `source`

Do not store secrets as “public”; allow the server privacy classifier to upgrade sensitive fields.

Tool parameter note: `agent_id` is optional for most `secure-graph` tools — omit it to use the default agent identity.

## Reads: automatic enrichment

A memory digest is already prepended via hooks (see **Automatic reads**). On top of that, when you need more structure or a wider hop than the digest:

1. Run `semantic_search` with a compact query derived from the user goal + key entities.
2. If you identify a stable anchor key (e.g. `person:jane`, `project:foobar`), also run `get_context` around it for relational context.

If nothing relevant exists, proceed normally.

## Hygiene

Avoid duplicating identical facts; update existing keys when obvious.
