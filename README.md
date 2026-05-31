# Slack Bot using Google Agent Development Kit (Python, Cloud Run)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/danishi/slack-bot-adk-python-cloudrun)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)

<img width="1024" alt="image" src="https://github.com/user-attachments/assets/815339c0-5299-498e-8372-d03acc442830" />

This repository provides a Slack bot backend implemented in Python that uses [Slack Bolt](https://slack.dev/bolt-python) and Google Cloud's [Vertex AI Gemini](https://cloud.google.com/vertex-ai) model via the [Agent Development Kit](https://google.github.io/adk-docs/). The bot responds to text, images, PDFs, plain text files, videos, and audio messages, while maintaining conversation context within Slack threads. It is designed to run on [Cloud Run](https://cloud.google.com/run).

If you want to use the [Google Gen AI SDK](https://googleapis.github.io/python-genai/), please refer to [this repository](https://github.com/danishi/slack-gemini-bot-on-google-cloud)💡

If you want a simpler, lightweight Slack bot without the ADK framework, check out [Nano Banana](https://github.com/danishi/slack-nano-banana-bot-on-google-cloud)🍌

## Features
- Powered by Vertex AI Gemini via the ADK. Verified working with `gemini-3.5-flash` (the default `MODEL_NAME`); any other Gemini model can be used by setting `MODEL_NAME`.
- Responds to `@mention` messages in Slack channels and direct messages (DMs).
- Supports text, image, PDF, text file, video, and audio inputs from Slack messages. Files are fetched via authenticated URLs and sent to Gemini for multimodal understanding.
- **Web search** via `web_search_agent` (Google Search) and `url_fetch_agent` (URL content retrieval) using `AgentTool`. Allows the bot to look up live web information and fetch page content on demand.
- **Image generation** via `generate_image` tool using Gemini image generation models:
  - `gemini-3-pro-image` ([Nanobanana Pro](https://github.com/danishi/slack-nano-banana-bot-on-google-cloud)) — higher quality
  - `gemini-3.1-flash-image` ([Nanobanana 2](https://github.com/danishi/slack-nano-banana-bot-on-google-cloud)) — faster generation
  - Generated images are automatically uploaded to the Slack thread.
- Maintains conversation context by retrieving prior messages in a thread and sending them as conversation history to Gemini.
- **MCP integration sample** via `mock_service_agent`, which reaches an external service over the [Model Context Protocol](https://modelcontextprotocol.io/). The bundled `mcp_servers/mock_service_server.py` wraps the public [JSONPlaceholder](https://jsonplaceholder.typicode.com/) mock API as a read-only user directory — swap the base URL and tools for your own backend to build a real integration.
- **Access control** via Slack workspace, user, and bot allowlists (`ALLOWED_SLACK_WORKSPACE`, `ALLOWED_SLACK_USERS`, `ALLOWED_SLACK_BOTS`). Empty user/bot lists mean "allow everyone / no bots".
- **Invocable by other bots** (e.g. Slackbot) when allowlisted, which enables scheduled/periodic runs triggered by [Slack reminders](#use-cases).
- Formats responses using Slack-compatible Markdown for rich text output.
- FastAPI-based web server suitable for Cloud Run.
- Deployment script for building and deploying to Cloud Run.

## Use Cases

### Interactive assistant
- `@mention` the bot in a channel or DM it to ask questions, hand it images/PDFs/audio for multimodal understanding, summarize a thread (the bot attributes statements by speaker), search the web, fetch a URL, or generate images.
- Ask it to look up people ("list the users", "what's user 2's email?") and it delegates to the MCP-backed `mock_service_agent`.

### Scheduled / periodic execution via Slack reminders
Because the bot can be invoked by an allowlisted bot, you can drive it on a schedule with a plain [Slack reminder](https://slack.com/help/articles/208423427-Set-a-reminder) — no extra cron infrastructure required. When a reminder fires, **Slackbot** posts the reminder text into the channel; if that text `@mention`s the bot, an `app_mention` event reaches your service and the agent runs.

Setup:
1. Add Slackbot's user ID, `USLACKBOT`, to `ALLOWED_SLACK_BOTS` (it is in `.env.example` by default). Without this the bot ignores messages posted by Slackbot.
2. Make sure the bot is a member of the target channel.
3. Create a recurring reminder whose text mentions the bot, for example:
   ```
   /remind #ops "@YourBot Summarize the open incidents and post the highlights" every weekday at 9:00
   ```
4. At each scheduled time Slackbot posts the reminder, the bot is mentioned, and the agent generates and posts its reply in the thread.

This pattern works for any recurring agent task — daily standup prompts, morning digests, periodic data lookups through the MCP service, and so on. Slack [scheduled messages](https://slack.com/help/articles/360046528633-Schedule-messages-to-send-later) and Workflow Builder can be used the same way as long as the posted message `@mention`s the bot and the posting identity is allowlisted.

## Project Structure
```
app/
  main.py           # FastAPI app, Slack Bolt handlers, access control, agent wiring
  agents/
    comedian.py            # ex: Comedian agent implementation
    web_search_agent.py    # ex: Web search & URL fetch agents (AgentTool)
    mock_service_agent.py  # ex: MCP-backed user directory sub-agent
  tools/
    generate_image.py        # ex: Image generation tool (Nanobanana Pro / Nanobanana 2)
    get_current_datetime.py  # ex: Date/time utility tool
  skills/
    greeting-skill/          # ex: Greeting skill (file-based ADK Skill)
      SKILL.md
      references/
        greeting_templates.md
    datetime-skill/          # ex: Datetime skill (file-based ADK Skill)
      SKILL.md
      references/
        default_timezones.md
mcp_servers/
  mock_service_server.py  # ex: MCP server wrapping the JSONPlaceholder mock API
scripts/
  deploy.sh         # Helper script to deploy to Cloud Run
Dockerfile          # Container definition for Cloud Run
requirements.txt    # Python dependencies
llms.txt           # ADK documentation for LLM reference
llms-full.txt      # Extended ADK documentation for LLM context
```

## Prerequisites
- Python 3.14
- [Google Cloud SDK](https://cloud.google.com/sdk) with `gcloud` authenticated
- Slack workspace admin privileges

## Local Development
1. Install dependencies
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Configure environment variables
   ```bash
   cp .env.example .env
   # edit .env and set your Slack and Google Cloud credentials
   # ALLOWED_SLACK_WORKSPACE is the Slack team ID to allow requests from
   # ALLOWED_SLACK_USERS / ALLOWED_SLACK_BOTS gate who can invoke the bot (see Access Control)
   ```
3. Run the server
   ```bash
   uvicorn app.main:fastapi_app --host 0.0.0.0 --port 8080 --reload
   ```
4. Use a tunneling tool like `ngrok` to expose `http://localhost:8080/slack/events` to Slack during development.

### Optional: Use the ADK Web Development UI

The Agent Development Kit includes a built-in web-based Development UI that you can run locally. It's a powerful tool for testing, debugging, and interacting with your agent during development. It provides a chat interface to send messages to your agent and inspect the results.

1.  **Start the ADK web server:**
    ```bash
    gcloud auth application-default login
    adk web
    ```

2.  **Interact with your agent:**
    Open the local URL (usually `http://127.0.0.1:8000`) in your browser to use the Development UI.

## Slack App Configuration
1. Create a new Slack app at <https://api.slack.com/apps>.
2. Under **OAuth & Permissions**, add the following Bot Token scopes:
   - `app_mentions:read`
   - `chat:write`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `files:read`
   - `files:write`
   - `reactions:write`
   - `users:read`
3. Install the app to your workspace to obtain `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`.
4. Enable **Event Subscriptions** and set the Request URL to `https://<your-cloud-run-service-url>/slack/events`.
5. Subscribe to bot events: `app_mention`, `message.im`.
6. Invite the bot to channels where you want to use it. For DMs, simply open a direct message with the bot.

## Access Control

Three independent, optional allowlists gate who can reach the bot:

| Variable | Empty / unset behavior | When set |
|----------|------------------------|----------|
| `ALLOWED_SLACK_WORKSPACE` | Allow all workspaces | Only accept events from the given Slack team ID (others get HTTP 403) |
| `ALLOWED_SLACK_USERS` | Allow all human users | Comma-separated user IDs; only listed humans may invoke the bot |
| `ALLOWED_SLACK_BOTS` | No bots allowed (bot messages ignored) | Comma-separated bot user IDs (e.g. `USLACKBOT`) that may invoke the bot |

Notes:
- A **disallowed human** user gets a permission-denied reply (in-thread) so they know why the bot is not responding. Customize it with `ACCESS_DENIED_MESSAGE` (empty = built-in default).
- **Disallowed bots** (anything carrying a `bot_id`, including Slackbot and the bot's own replies) are ignored silently to avoid reply loops and channel noise.
- The bot's own messages carry a `bot_id` and are never allowlisted, so reply loops are prevented automatically.
- `ALLOWED_SLACK_BOTS` is what makes [scheduled execution via Slack reminders](#use-cases) possible — `USLACKBOT` posts reminder messages, so it must be listed.
- To find a user ID, open the member's profile → **⋮** → **Copy member ID**, or call the Slack API:
  ```bash
  curl -s -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
    "https://slack.com/api/users.list" | jq '.members[] | {id, name, real_name: .profile.real_name}'
  ```

## MCP Integration Sample

`mock_service_agent` demonstrates how to connect the bot to an external service through the [Model Context Protocol](https://modelcontextprotocol.io/):

- `mcp_servers/mock_service_server.py` is a [FastMCP](https://modelcontextprotocol.io/) server, started by ADK's `McpToolset` as a stdio subprocess (`python -m mcp_servers.mock_service_server`).
- It exposes two read-only tools — `list_users` and `get_user(user_id)` — backed by the public [JSONPlaceholder](https://jsonplaceholder.typicode.com/) mock API (`/users` and `/users/{id}`).
- The backend URL is hardcoded as the `MOCK_API_BASE_URL` literal at the top of `mock_service_server.py`.

To turn this into a real integration, change that `MOCK_API_BASE_URL` literal to your own service and replace the tool implementations in `mock_service_server.py` (add auth, write operations, etc.).

## Deploy to Cloud Run
The repository includes a helper script to build the container and deploy to Cloud Run. Ensure your `.env` contains `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` before running:

### One-time setup (first run only)
Enable the Cloud Build API for your project:
```bash
gcloud services enable cloudbuild.googleapis.com
```

Then deploy:
```bash
./scripts/deploy.sh
```

The script will:
1. Build the container image using Cloud Build.
2. Deploy the image to Cloud Run.
3. Set the required environment variables on the service.

After deployment, configure the Slack app's event subscription URL to the Cloud Run service URL.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=danishi/slack-bot-adk-python-cloudrun&type=Month)](https://star-history.com/#danishi/slack-bot-adk-python-cloudrun&Month)
