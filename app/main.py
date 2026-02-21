import os
import json
import re
import uuid
from typing import List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from google.genai import types
from google.adk.agents import Agent
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
# from google.adk.tools import google_search

from .agents.comedian import comedian_agent
from .tools.get_current_datetime import get_current_datetime

# Environment variables
load_dotenv()

# Override GOOGLE_CLOUD_LOCATION with MODEL_LOCATION if set,
# so that google.genai.Client uses the model-specific region.
_model_location = os.environ.get("MODEL_LOCATION")
if _model_location:
    os.environ["GOOGLE_CLOUD_LOCATION"] = _model_location

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.1-pro-preview")
ALLOWED_SLACK_WORKSPACE = os.environ.get("ALLOWED_SLACK_WORKSPACE")
APP_NAME = os.environ.get("APP_NAME", "slack-bot")

# Initialize Slack Bolt AsyncApp
bolt_app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
handler = AsyncSlackRequestHandler(bolt_app)

fastapi_app = FastAPI()


async def _build_content_from_event(event: dict) -> types.Content:
    parts: List[types.Part] = []
    text = event.get("text") or ""
    text = re.sub(r"<@[^>]+>\s*", "", text).strip()
    if text:
        parts.append(types.Part.from_text(text=text))

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for f in event.get("files", []):
            mimetype = (f.get("mimetype") or "")
            url = f.get("url_private_download")
            if not url:
                continue
            supported = (
                mimetype.startswith(("image/", "video/", "audio/", "text/"))
                or mimetype == "application/pdf"
            )
            if not supported:
                continue
            resp = await http_client.get(
                url,
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
            )
            resp.raise_for_status()
            if mimetype.startswith("text/"):
                parts.append(types.Part.from_text(text=resp.text))
            else:
                parts.append(types.Part.from_bytes(data=resp.content, mime_type=mimetype))

    if not parts:
        parts.append(types.Part.from_text(text="(no content)"))
    return types.Content(role="user", parts=parts)


async def _populate_session_from_thread(
    *,
    session,
    client,
    channel: str,
    thread_ts: str,
    current_ts: str,
) -> None:
    """Populate an ADK session with existing Slack thread history."""
    resp = await client.conversations_replies(channel=channel, ts=thread_ts)
    for m in resp.get("messages", []):
        if m.get("ts") == current_ts:
            continue
        if m.get("bot_id"):
            content = types.Content(
                role="model",
                parts=[types.Part.from_text(text=m.get("text", ""))],
            )
            author = "model"
        else:
            content = await _build_content_from_event(m)
            author = "user"
        event_obj = Event(
            invocation_id=str(uuid.uuid4()),
            author=author,
            content=content,
        )
        await session_service.append_event(session=session, event=event_obj)


root_agent = Agent(
    name="slack_bot_agent",
    model=MODEL_NAME,
    instruction="""
You are acting as a Slack Bot. All your responses must be formatted using Slack-compatible Markdown.

### Formatting Rules
- **Headings / emphasis**: Use `*bold*` for section titles or important words.
- *Italics*: Use `_underscores_` for emphasis when needed.
- Lists: Use `-` for unordered lists, and `1.` for ordered lists.
- Code snippets: Use triple backticks (```) for multi-line code blocks, and backticks (`) for inline code.
- Links: Use `<https://example.com|display text>` format.
- Blockquotes: Use `>` at the beginning of a line.

Always structure your response clearly, using these rules so it renders correctly in Slack.""",
    tools=[
        get_current_datetime,
    ],
    sub_agents=[
        comedian_agent,
    ],
)

runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
session_service = runner.session_service


MAX_SLACK_BLOCK_CHARS = 3000


def _build_slack_blocks_from_text(text: str) -> List[dict]:
    """Split long text into Slack blocks within allowed size."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text[i : i + MAX_SLACK_BLOCK_CHARS]}}
        for i in range(0, len(text), MAX_SLACK_BLOCK_CHARS)
    ] or [{"type": "section", "text": {"type": "mrkdwn", "text": ""}}]


@bolt_app.event("app_mention")
async def handle_mention(body, say, client, logger, ack):
    # Ack as soon as possible to avoid Slack retries that can cause duplicated responses
    await ack()

    event = body["event"]
    channel = event["channel"]
    message_ts = event["ts"]
    thread_ts = event.get("thread_ts") or message_ts
    user_id = event.get("user", "unknown")

    # Add 👀 reaction to indicate the message is being processed
    try:
        await client.reactions_add(channel=channel, timestamp=message_ts, name="eyes")
    except Exception:
        pass

    user_content = await _build_content_from_event(event)

    try:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=thread_ts
        )
    except Exception:
        pass

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=thread_ts
    )
    if session and not session.events:
        await _populate_session_from_thread(
            session=session,
            client=client,
            channel=channel,
            thread_ts=thread_ts,
            current_ts=message_ts,
        )

    try:
        reply_text = ""
        async for ev in runner.run_async(
            user_id=user_id, session_id=thread_ts, new_message=user_content
        ):
            if ev.is_final_response():
                reply_text = ev.content.parts[0].text.strip()
                break
        if not reply_text:
            reply_text = "(no response)"
    except Exception as e:
        logger.exception("Agent run failed")
        reply_text = f"Error from Agent: {e}"

    blocks = _build_slack_blocks_from_text(reply_text)
    await say(
        blocks=blocks,
        text=reply_text[:MAX_SLACK_BLOCK_CHARS],
        thread_ts=thread_ts,
    )

    # Add ✅ reaction to indicate the reply is complete
    try:
        await client.reactions_add(channel=channel, timestamp=message_ts, name="white_check_mark")
    except Exception:
        pass


@fastapi_app.post("/slack/events")
async def slack_events(req: Request):
    retry_num = req.headers.get("x-slack-retry-num")
    if retry_num is not None:
        return JSONResponse(status_code=404, content={"error": "ignored_slack_retry"})

    raw_body = await req.body()
    data = json.loads(raw_body)
    challenge = data.get("challenge")
    if challenge:
        return JSONResponse(content={"challenge": challenge})

    team_id = data.get("team_id")
    if ALLOWED_SLACK_WORKSPACE and team_id != ALLOWED_SLACK_WORKSPACE:
        return JSONResponse(status_code=403, content={"error": f"{team_id}:workspace_not_allowed"})
    return await handler.handle(req)


@fastapi_app.get("/")
async def root():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:fastapi_app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
