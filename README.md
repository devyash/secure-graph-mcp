# Secure Graph MCP

**Secure Graph MCP** is a **local-first** graph memory backed by **SQLite**. AI clients (starting with **[Cursor](https://cursor.com/)** via MCP) store **nodes**, **relationships**, and **field-level properties** through a structured API—not ad-hoc SQL or Markdown blobs in the workspace.

**Repository:** https://github.com/devyash/secure-graph-mcp

Goals:

1. **Durable memory** across chats and repos (path chosen by `SECURE_GRAPH_DB`).
2. **Field-level privacy** with permissions and deterministic classification of obviously sensitive payloads.
3. **Semantic-ish retrieval** (lightweight embedding over property text) plus structural context.
4. **Optional Cursor automation**: MCP for explicit tools, Composer **hooks** for automatic read/write of turn text.

Python **3.10+** required.

---

## Table of contents

- [Quick start (TL;DR)](#quick-start-tldr)
- [What ships in this repo](#what-ships-in-this-repo)
- [Data model (what gets stored)](#data-model-what-gets-stored)
- [Environment variables](#environment-variables)
- [Install the Python package](#install-the-python-package)
- [Cursor: easy setup (recommended)](#cursor-easy-setup-recommended)
- [Cursor: validate](#cursor-validate)
- [Cursor: manual MCP configuration](#cursor-manual-mcp-configuration)
- [Cursor: automatic memory (hooks + allowlist + rules)](#cursor-automatic-memory-hooks--allowlist--rules)
- [Command-line apps](#command-line-apps)
- [MCP tools (summary)](#mcp-tools-summary)
- [Example `ingest_graph_mutations` payload](#example-ingest_graph_mutations-payload)
- [Conversation ingestion](#conversation-ingestion)
- [Troubleshooting](#troubleshooting)
- [Development & tests](#development--tests)
- [Sharing / packaging](#sharing--packaging)
- [Security model](#security-model)

---

## Quick start (TL;DR)

### Closest thing to “one click”

There is **no** signed macOS `.pkg` / Windows installer or Cursor marketplace entry—Cursor and MCP assume you trust a repo and a Python toolchain. What you *can* do is **one shell command** after setting your Git URL:

```bash
export SECURE_GRAPH_MCP_REPO_URL=https://github.com/devyash/secure-graph-mcp.git
curl -fsSL "$SECURE_GRAPH_MCP_REPO_URL/raw/main/scripts/one_command_install.sh" | bash
```

The installer keeps a **persistent clone** at **`~/.local/share/secure-graph-mcp`** (override with **`SECURE_GRAPH_MCP_CLONE_DIR`**) because Cursor’s MCP and hooks must reference a stable **`.venv` path**.

**Already cloned?** From the repo root this is the full automation (no `curl`):

```bash
./scripts/one_command_install.sh
```

Preview installer changes only:

```bash
./scripts/one_command_install.sh --dry-run
```

Afterward: **User Rules** (`cursor-user-rule-secure-graph.md`), **Cursor Auto-Run**, **restart Cursor**, then run the verifier (**`<repo>/.venv/bin/secure-graph-verify-cursor`** if that directory is not on your `PATH`).

---

### Clone + installer (traditional)

```bash
git clone https://github.com/devyash/secure-graph-mcp.git
cd secure-graph-mcp
python3 scripts/install_cursor_bundle.py
```

Preview changes only:

```bash
python3 scripts/install_cursor_bundle.py --dry-run
```

Then:

1. Open **Cursor → Settings → Rules → User Rules** and paste the contents of **`cursor-user-rule-secure-graph.md`**.
2. Ensure **Cursor Agent → Auto-Run** is enabled (`Run Everything`, `Auto-run in Sandbox`, etc.—not *Ask Every Time*) so MCP allowlisting works as documented in [Cursor permissions](https://cursor.com/docs/reference/permissions.md).
3. **Restart Cursor** once.
4. Run **`secure-graph-verify-cursor`**; exit code **0** means the automated smoke checks passed.

Equivalent after **`pip install -e .`** (or installing from a wheel):

```bash
secure-graph-install-cursor
secure-graph-verify-cursor
```

---

## What ships in this repo

| Artifact | Purpose |
|----------|---------|
| **`secure_graph_mcp`** package | SQLite schema, policy, MCP server (`FastMCP` name **`secure-graph`**), ingestion, embeddings, viewer. |
| **`secure-graph-mcp`** CLI | MCP stdio server entrypoint (`python -m secure_graph_mcp.mcp_server`). |
| **`secure-graph-cursor-hook`** CLI | Composer hook stdin/JSON handler (`sessionStart`, `beforeSubmitPrompt`, `afterAgentResponse`). |
| **`secure-graph-install-cursor`** CLI | Merges `~/.cursor/mcp.json`, `hooks.json`, `permissions.json`; creates `./.venv` and `pip install -e .`. |
| **`secure-graph-verify-cursor`** CLI | Validates Cursor config paths + DB connectivity. |
| **`scripts/install_cursor_bundle.py`** | Thin bootstrap (`PYTHONPATH=src`) so teammates can install **before** a prior `pip install`. |
| **`cursor-user-rule-secure-graph.md`** | Paste into Cursor **User Rules** for MCP-oriented behavior hints. |

---

## Data model (what gets stored)

- **`agents`**: identities (e.g. `cursor_default`).
- **`agent_permissions`**: strings such as `pii.ssn.read` granting read access to gated fields.
- **`nodes`**: entities (`person:jane`, `org:acme`, `project:…`).
- **`edges`**: typed links between nodes, each with privacy metadata.
- **`properties`**: typed key/value pairs on nodes or edges, with **`privacy_level`**, **`required_permission`**, and audit metadata.
- **`embeddings`**: JSON vectors for cosine ranking over property text.
- **`audit_log`**: append-only-ish record of MCP / policy actions (used for validating hooks).

SQLite is the **authoritative store** for this prototype.

---

## Environment variables

| Variable | Typical use |
|----------|--------------|
| **`SECURE_GRAPH_DB`** | Path to **`graph.sqlite3`**. Parent dirs are created on first write. Default: **`~/.secure-graph-mcp/graph.sqlite3`** if unset. |
| **`SECURE_GRAPH_DEFAULT_AGENT_ID`** | Default **`agent_id`** when tools omit it (installer sets **`cursor_default`**). |
| **`SECURE_GRAPH_HOOK_SEMANTIC_LIMIT`** | Max semantic hits injected by hooks (default **12**). |
| **`SECURE_GRAPH_HOOK_RECENT_LIMIT`** | Max “recent properties” rows in hook digest (default **10**). |
| **`SECURE_GRAPH_HOOK_MAX_CHARS`** | Truncate injected hook context (default **8000**). |

Hooks inherit the Composer environment; MCP reads env from **`mcp.json`** for the `secure-graph` server entry.

---

## Install the Python package

```bash
cd secure-graph-mcp
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows: .venv\Scripts\activate

python -m pip install -U pip setuptools wheel
pip install -e .
```

Smoke-test imports:

```bash
python -c "from secure_graph_mcp.storage import GraphStore; GraphStore(':memory:').close()"
```

---

## Cursor: easy setup (recommended)

The **`install_cursor_bundle`** flow:

1. Creates **`<repo>/.venv`** (unless you pass **`--venv`** / **`--skip-venv`** for advanced setups).
2. Runs **`pip install -U pip setuptools wheel`** and **`pip install -e .`** from the repo root.
3. Merges a **`secure-graph`** stanza into **`~/.cursor/mcp.json`**:
   - **`command`**: **`<venv>/bin/python`** (or **`Scripts\\python.exe`** on Windows—installer follows the OS layout).
   - **`args`**: **`["-m", "secure_graph_mcp.mcp_server"]`**.
   - **`cwd`**: repo root (helps static viewer assets resolve consistently).
   - **`env`**: **`SECURE_GRAPH_DB`**, **`SECURE_GRAPH_DEFAULT_AGENT_ID`** (`--db` / `--agent-id` flags override defaults).
4. Prepends Composer hook definitions to **`~/.cursor/hooks.json`** using **`secure-graph-cursor-hook`** (old Secure Graph hook rows are filtered out first so you don’t stack duplicates).
5. **Unions** **`secure-graph:*`** into **`mcpAllowlist`** inside **`~/.cursor/permissions.json`**.

Installer flags worth knowing:

```text
python3 scripts/install_cursor_bundle.py --dry-run          # No writes
python3 scripts/install_cursor_bundle.py --db ~/my/graph.sqlite3
python3 scripts/install_cursor_bundle.py --repo /abs/path/to/secure-graph-mcp
```

**Backups** (only when files already exist):

- **`~/.cursor/mcp.json.bak`**, **`hooks.json.bak`**, **`permissions.json.bak`**.

**Important:** rewriting **`permissions.json` normalizes plain JSON.** If teammates used **`//`** comments previously, Cursor may accept them—but this installer persists valid JSON—so re-add explanatory comments manually if desired. When **`mcpAllowlist`** is present, Cursor treats it as the **override** list; merge patterns for **other** MCP servers (e.g. **`figma:*`**) manually.

References: [Cursor Hooks](https://cursor.com/docs/agent/hooks), [Cursor permissions](https://cursor.com/docs/reference/permissions.md).

---

## Cursor: validate

```bash
secure-graph-verify-cursor
```

Interpretation:

| Output | Meaning |
|--------|---------|
| **`[fail]`** | Hard problem (missing file, bad JSON, MCP python missing, unreadable SQLite, hook CLI absent). Exit **1**. |
| **`[warn]`** | Soft issue (database not yet created, optional fields missing—safe during first-run). Exit **0**. |
| **`[ ok ]`** | Check passed. |

**Live Composer proof** (after restart + Auto-run):

1. Hooks output channel fires for **`sessionStart`**, **`beforeSubmitPrompt`**, **`afterAgentResponse`** without stack traces.
2. SQLite **`audit_log`** gains **`semantic_search`** rows carrying your outbound message text inside `details_json`, and **`ingest_conversation`** rows with **`source_id`** like **`cursor:<conversation_uuid>:<generation_uuid>`** after each completed assistant reply.
3. **`~/.cursor/hooks/secure-graph-pending/`**: shows a pairing JSON file while a reply is pending; disappears after ingestion.

---

## Cursor: manual MCP configuration

Use this shape if you bypass the installer. Prefer **`venv` interpreter + module launch** so tooling never depends on `PATH`:

```json
{
  "mcpServers": {
    "secure-graph": {
      "command": "/absolute/path/to/repo/.venv/bin/python",
      "args": ["-m", "secure_graph_mcp.mcp_server"],
      "cwd": "/absolute/path/to/repo",
      "env": {
        "SECURE_GRAPH_DB": "/absolute/path/graph.sqlite3",
        "SECURE_GRAPH_DEFAULT_AGENT_ID": "cursor_default"
      }
    }
  }
}
```

On Windows, replace **`bin/python`** with **`Scripts/python.exe`** and use backslashes where convenient (JSON escapes still apply).

The FastMCP server name **`secure-graph`** should match **`mcp.json`** key—it is referenced by tooling and automation.

Alternative (global `PATH`): `"command": "secure-graph-mcp"` with **`env`** as above—the shell entrypoint behaves like **`python -m secure_graph_mcp.mcp_server`**.

Restart Cursor whenever **`mcp.json`** changes.

---

## Cursor: automatic memory (hooks + allowlist + rules)

Three layers reinforce each other:

1. **Composer hooks** (via **`hooks.json`**)
   - **`sessionStart`** → injects **`additional_context`** introducing recent graph facts (permission-aware digest).
   - **`beforeSubmitPrompt`** → persists pending user utterance pairing + attempts query-conditioned **`additional_context`** (Cursor’s docs list only `{continue, user_message}` for this event—some builds respect extra JSON fields anyway; **`sessionStart` always succeeds at documented bootstrap context).
   - **`afterAgentResponse`** → writes **`GraphStore.ingest_conversation`** for the **`User:/Assistant:`** transcript chunk.

2. **MCP Auto-run allowlist** (`**/permissions.json`)

   Patterns look like **`server:tool`**. Example: **`secure-graph:*`** scopes every tool on that server under allowlisting—**provided** Composer Auto-run isn’t forcing confirmation on every MCP call ([permissions docs](https://cursor.com/docs/reference/permissions.md)).

3. **User Rules** (**`cursor-user-rule-secure-graph.md`**)

   Encourages agents to use **`semantic_search`** and **`get_context`** when the injected digest isn’t sufficient.

Reminder: **`mcpAllowlist` overrides** Cursor’s IDE-side MCP checkbox list whenever it appears—maintain intentional unions for other MCP products your team relies on.

---

## Command-line apps

| CLI | Invocation example |
|-----|---------------------|
| **`secure-graph-mcp`** | `SECURE_GRAPH_DB=~/g.sqlite3 secure-graph-mcp` (stdio MCP—usually launched by Cursor, not typed manually). |
| **`secure-graph-demo`** | `secure-graph-demo` — seed / exercise flows. |
| **`secure-graph-view`** | `SECURE_GRAPH_DB=~/.secure-graph-mcp/graph.sqlite3 secure-graph-view` then open **`http://127.0.0.1:8765/?agent_id=<id>&root=<external_key>&depth=2`** |
| **`secure-graph-cursor-hook`** | Invoked exclusively by Composer (`stdin` JSON payloads). |

---

## MCP tools (summary)

| Tool | Role |
|------|------|
| **`create_agent`** | Upsert **`agents`** rows. |
| **`grant_permission` / `list_permissions`** | Manage capability strings controlling redaction/read. |
| **`ingest_conversation`** | Deterministic text extraction pipeline + ingestion. |
| **`ingest_graph_mutations`** | Structured nodes/edges/properties with policy upgrades. |
| **`upsert_node`**, **`add_edge`**, **`set_property`** | Low-level authoring. |
| **`get_context`**, **`semantic_search`** | Permission-filtered subgraph + ranked property hits.

Most optional **`agent_id`** parameters default via **`SECURE_GRAPH_DEFAULT_AGENT_ID`**.

Detailed behavior lives alongside implementation in **`src/secure_graph_mcp/mcp_server.py`** and **`storage.py`**.

---

## Example `ingest_graph_mutations` payload

```json
{
  "nodes": [
    {
      "external_key": "person:jane",
      "type": "person",
      "properties": [
        { "key": "name", "value": "Jane Doe" },
        { "key": "ssn", "value": "123-45-6789" }
      ]
    }
  ],
  "edges": []
}
```

The server upgrades obvious sensitive fields—for example **`ssn`** lands as **`restricted`** with **`pii.ssn.read`** even if callers forget to annotate.

Advanced flows can nest **`privacy_level`** / **`required_permission`** / **`verified_status`** on property dicts—the policy layer merges these with heuristic classification.

---

## Conversation ingestion

- **`ingest_conversation`** runs a small deterministic extractor (**`ingestion.extract_basic_mutations`**) for patterns like **`X works at Y`** plus SSN heuristics.  
- Larger clients should prefer supplying **`extracted_mutations`** (already structured) whenever their own LLMs perform extraction—they still inherit validation, embeddings, auditing, redaction semantics.

Hooks always call **`ingest_conversation`** with raw **`User`/`Assistant` text—not** LLM-produced structured JSON—matching the autopilot ingestion story.

---

## Troubleshooting

| Symptom | What to inspect |
|---------|----------------|
| MCP never connects | Restart Cursor after editing **`~/.cursor/mcp.json`**; validate JSON; confirm **`command`/`args`** match an existing venv. |
| MCP tools constantly ask permission | Toggle **Composer Auto-run** (`Run Everything`/sandboxed auto-run)—**Ask Every Time bypasses centralized allowlisting** per Cursor docs ([permissions](https://cursor.com/docs/reference/permissions.md)). |
| Hooks never seem to execute | Inspect **Hooks** output channel logs; rerun installer; validate **`hooks.json`** commands still point inside your clone after moving directories. |
| SQLite **“unable to open database”** ensure parent directory exists **`chmod`/ACL** sane; rerun **`secure-graph-verify-cursor`**. |
| **`semantic_search` always empty** embeddings require stored properties (`set_property`, ingestion). |
| Duplicate hook rows stacking | Latest installer strips hook commands referencing **`secure-graph-cursor-hook`** before re-inserting—you can clean manually otherwise. |

Log-level debugging: SQLite **`audit_log`** is the quickest truth source besides Cursor’s MCP trace UI.

---

## Development & tests

```bash
pip install -e .
python -m unittest discover -s tests -p 'test*.py' -v
```

Run **`ruff`** / **`mypy`** only if your team adopts them—they are optional for this scaffold.

Suggested branch workflow stays conventional (`main` protects production DB paths in docs only—your machine retains real paths).

---

## Sharing / packaging

**Teammates:**

```bash
git clone ...
python3 scripts/install_cursor_bundle.py
secure-graph-verify-cursor
```

**Wheel / CI publishing:**

```bash
python -m pip install build
python -m build
# dist/*.whl + dist/*.tar.gz
Recipients: pip install /path/to/wheel.whl && secure-graph-install-cursor ...
```

Pinned versions & metadata live in **`pyproject.toml`** (`requires-python ">=3.10"`, depends on **`mcp>=1.0.0`**).

Security reminder: **`SECURE_GRAPH_DB`** is confidential—don't commit populated DB blobs to Git.

---

## Security model

SQLite itself does **not** enforce row-level security in the filesystem—**all enforcement happens inside MCP / policy wrappers**.

Properties:

| Concern | Mitigation |
|---------|-------------|
| Least-privilege reads | `required_permission`; missing grants ⇒ redacted / omitted during search defaults. |
| Sensitive literals | Patterns (SSNs, etc.) escalate classification irrespective of sloppy keys. |
| Auditing | `audit_log` records actions with JSON detail payloads hooking into debugging. |

Do **not** mount the raw SQLite file into hostile sandboxes writable by arbitrary code—or treat that exposure like handing out a Postgres superuser credential.

Questions / improvements welcomed via Issues or internal channels—feature requests around hook timing should cite [Cursor Hooks](https://cursor.com/docs/agent/hooks).
