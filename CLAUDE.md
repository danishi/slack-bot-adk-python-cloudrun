# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Conventions

- **Write everything in English**: commit messages, pull request titles/descriptions, and code comments must all be in English, regardless of the language used in conversation.
- Commit messages use the imperative mood ("Add feature", not "Added feature") with the first line kept under 72 characters.

## Overview

A Slack bot backend built with **Slack Bolt** (async) + **FastAPI**, powered by Google's **Agent Development Kit (ADK)** running Vertex AI Gemini models. It handles `@mention` and DM messages with multimodal input (text, image, PDF, text file, video, audio), maintains conversation context per Slack thread, can search the web, fetch URLs, and generate images. Designed to run on Cloud Run.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in Slack + GCP credentials

# Run locally (expose /slack/events via ngrok for Slack to reach it)
uvicorn app.main:fastapi_app --host 0.0.0.0 --port 8080 --reload

# ADK Development UI for testing/debugging the agent in isolation
gcloud auth application-default login
adk web   # opens http://127.0.0.1:8000

# Deploy to Cloud Run (reads .env, builds via Cloud Build, sets env vars on service)
./scripts/deploy.sh
```

There is no test suite, linter, or formatter configured in this repo.

## Architecture

The entire request lifecycle lives in `app/main.py`. The flow:

1. **Slack → FastAPI** — `POST /slack/events` (`app/main.py`). This endpoint does request filtering *before* handing off to Bolt:
   - Drops Slack retries (`x-slack-retry-num` header) with a 404 — important because agent runs can exceed Slack's 3s timeout, and without this every slow reply would be re-processed.
   - Echoes the URL-verification `challenge`.
   - Enforces a workspace allowlist via `ALLOWED_SLACK_WORKSPACE` (403 if `team_id` mismatches).
   - Only then delegates to the Bolt `AsyncSlackRequestHandler`.
2. **Bolt event handlers** — `handle_mention` (app_mention) and `handle_direct_message` (DMs only, `channel_type == "im"`) both `ack()` immediately, gate the sender via `_is_sender_allowed`, then call the shared `_handle_message`. The DM handler drops human message subtypes (edits/joins) but keeps `bot_message` so allowlisted bots (e.g. Slackbot reminders) get through.
   - **Access control** — `_is_sender_allowed` checks two allowlists: `ALLOWED_SLACK_USERS` (empty = allow all humans) and `ALLOWED_SLACK_BOTS` (empty = no bots; bots are never allowed implicitly). The bot's own messages carry a `bot_id` and aren't allowlisted, so reply loops are prevented. Listing `USLACKBOT` in `ALLOWED_SLACK_BOTS` is what lets Slack reminders trigger scheduled runs. `_deny_if_not_allowed` wraps the check at the handler boundary: a disallowed **human** gets the `ACCESS_DENIED_MESSAGE` reply in-thread, while anything with a `bot_id` is dropped silently (no loops/noise).
3. **`_handle_message`** — the core orchestration:
   - Adds the 👀 reaction (`REACTION_PROCESSING`), runs the agent, posts the reply, uploads any generated images, adds the ✅ reaction (`REACTION_COMPLETED`).
   - Uses `thread_ts` as the **ADK session id**, so each Slack thread is one persistent conversation.
   - On a fresh session, `_populate_session_from_thread` backfills the ADK session with prior thread messages via `conversations_replies`, so context survives even though sessions are in-memory only (`InMemoryRunner`).

### Agent composition (`root_agent` in `app/main.py`)

`root_agent` (`slack_bot_agent`) is wired with:
- **`SkillToolset`** — file-based ADK skills loaded from `app/skills/` via `load_skill_from_dir` (`greeting-skill`, `datetime-skill`). The `get_current_datetime` tool is passed as `additional_tools`; a skill can also declare tools via `metadata.adk_additional_tools` in its `SKILL.md` frontmatter (see `datetime-skill`).
- **`generate_image`** tool (`app/tools/generate_image.py`).
- **`AgentTool`-wrapped sub-agents** `web_search_agent` (Google Search) and `url_fetch_agent` (url_context) from `app/agents/web_search_agent.py`.
- **`sub_agents`**: `comedian_agent` (`app/agents/comedian.py`) and `mock_service_agent` (`app/agents/mock_service_agent.py`) — true delegated sub-agents, not AgentTools.
- **MCP integration** — `mock_service_agent` is built via `create_mock_service_agent(tools=[_mock_service_mcp])`. `_mock_service_mcp` is an ADK `McpToolset` that launches `mcp_servers/mock_service_server.py` as a stdio subprocess (`python -m mcp_servers.mock_service_server`). The FastMCP server wraps the JSONPlaceholder mock API (hardcoded `MOCK_API_BASE_URL` literal in `mock_service_server.py`) and exposes `list_users` / `get_user`. This is the template for swapping in a real backend service over MCP. Because the server runs as a subprocess, `mcp_servers/` must be COPYed into the Docker image.

### Key cross-cutting patterns

- **Speaker identification** — Every user message (current and history) is prefixed with a `[Speaker: <name>]` text part so the agent can attribute statements by name in multi-person threads. The root agent's instruction explicitly tells it never to echo this tag. User names are resolved via `users_info` and cached in `_user_name_cache`.
- **Image hand-off** — `generate_image` cannot upload to Slack directly (it's a tool, not a handler). It stashes image bytes in a module-level dict keyed by session id, set via the `current_session_id` **ContextVar** before each run. `_handle_message` then calls `get_and_clear_images(thread_ts)` to upload them. When editing image generation, preserve this ContextVar → dict → drain flow.
- **Multimodal input** — `_build_content_from_event` downloads Slack files via `url_private_download` with the bot token, sending images/video/audio/pdf as bytes and `text/*` as decoded text. Unsupported mimetypes are silently skipped.
- **Slack output chunking** — replies are split into 3000-char (`MAX_SLACK_BLOCK_CHARS`) `mrkdwn` blocks. The root agent instruction enforces Slack-flavored markdown (`*bold*`, `_italic_`, `<url|text>`), which differs from standard markdown.

## Configuration

All config is environment variables (see `.env.example`). Notable ones:
- `MODEL_NAME` (default `gemini-3.5-flash`) — used by root and all sub-agents.
- `IMAGE_MODEL_NAME` (default `gemini-3.1-flash-image`, "Nanobanana 2") — the agent can override per-call to `gemini-3-pro-image` ("Nanobanana Pro") for higher quality.
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (`global`) — Vertex AI auth.
- `ALLOWED_SLACK_WORKSPACE` — Slack team ID allowlist (omit to allow all).
- `ALLOWED_SLACK_USERS` — comma-separated user IDs allowed to invoke (empty = allow all humans).
- `ALLOWED_SLACK_BOTS` — comma-separated bot user IDs allowed to invoke, e.g. `USLACKBOT` for Slack reminders (empty = no bots).
- `ACCESS_DENIED_MESSAGE` — reply sent to a disallowed human user (empty = built-in default).
- `REACTION_PROCESSING` / `REACTION_COMPLETED` — reaction emoji names.

The sample MCP server's backend URL is a hardcoded literal (`MOCK_API_BASE_URL`) in `mcp_servers/mock_service_server.py`, not an env var.

`deploy.sh` passes env vars with a `^@^` delimiter (not commas) so allowlist values like `ALLOWED_SLACK_USERS=U1,U2` survive `gcloud run deploy --set-env-vars`.

## Notes

- `llms.txt` / `llms-full.txt` are bundled ADK documentation for LLM reference — they are not source code. They are snapshots pulled from the [adk-python](https://github.com/google/adk-python) `release/v2.1.0` branch: `llms.txt` is a concise index/overview of the ADK and `llms-full.txt` is the full documentation corpus. Consult them as the authoritative ADK reference (matching the pinned ADK version) before reaching for external web docs, and refresh both files from the same branch when the ADK dependency is bumped.
- Sessions are in-memory (`InMemoryRunner`); restarting the service loses live sessions, but thread history is rehydrated from Slack on the next message.
- Adding a new ADK skill: create `app/skills/<name>/SKILL.md` (+ optional `references/`), then register it in the `SkillToolset` in `app/main.py`.
