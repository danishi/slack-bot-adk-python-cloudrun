import io
import os
import json
import pathlib
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
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
# from google.adk.tools import google_search

from .agents.comedian import comedian_agent
from .tools.get_current_datetime import get_current_datetime
from .tools.generate_image import generate_image, get_and_clear_images

# Environment variables
load_dotenv()
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.1-pro-preview")
ALLOWED_SLACK_WORKSPACE = os.environ.get("ALLOWED_SLACK_WORKSPACE")
APP_NAME = os.environ.get("APP_NAME", "slack-bot")
REACTION_PROCESSING = os.environ.get("REACTION_PROCESSING", "eyes")
REACTION_COMPLETED = os.environ.get("REACTION_COMPLETED", "white_check_mark")

# Initialize Slack Bolt AsyncApp
bolt_app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
handler = AsyncSlackRequestHandler(bolt_app)

fastapi_app = FastAPI()

# Cache for Slack user display names: user_id -> display_name
_user_name_cache: dict[str, str] = {}
# Bot's own user ID (resolved once at first mention)
_bot_user_id: str | None = None


async def _resolve_user_name(client, user_id: str) -> str:
    """Resolve a Slack user ID to a display name, with caching."""
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        resp = await client.users_info(user=user_id)
        user_info = resp.get("user", {})
        profile = user_info.get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or user_info.get("real_name")
            or user_id
        )
        _user_name_cache[user_id] = name
    except Exception:
        _user_name_cache[user_id] = user_id
    return _user_name_cache[user_id]


async def _get_bot_user_id(client) -> str:
    """Get the bot's own Slack user ID via auth.test, cached after first call."""
    global _bot_user_id
    if _bot_user_id is None:
        try:
            resp = await client.auth_test()
            _bot_user_id = resp.get("user_id", "")
        except Exception:
            _bot_user_id = ""
    return _bot_user_id


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
    bot_uid = await _get_bot_user_id(client)
    resp = await client.conversations_replies(channel=channel, ts=thread_ts)
    for m in resp.get("messages", []):
        if m.get("ts") == current_ts:
            continue
        msg_user = m.get("user", "")
        is_bot = bool(m.get("bot_id")) or msg_user == bot_uid
        if is_bot:
            content = types.Content(
                role="model",
                parts=[types.Part.from_text(text=m.get("text", ""))],
            )
            author = "model"
        else:
            speaker_name = await _resolve_user_name(client, msg_user) if msg_user else "unknown"
            content = await _build_content_from_event(m)
            # Prepend speaker label so the agent knows who said it
            speaker_prefix = types.Part.from_text(text=f"[Speaker: {speaker_name}]")
            content = types.Content(role="user", parts=[speaker_prefix] + list(content.parts))
            author = "user"
        event_obj = Event(
            invocation_id=str(uuid.uuid4()),
            author=author,
            content=content,
        )
        await session_service.append_event(session=session, event=event_obj)


# Load skills from directory
_skills_dir = pathlib.Path(__file__).parent / "skills"
greeting_skill = load_skill_from_dir(_skills_dir / "greeting-skill")
datetime_skill = load_skill_from_dir(_skills_dir / "datetime-skill")

skill_toolset = SkillToolset(
    skills=[greeting_skill, datetime_skill],
    additional_tools=[get_current_datetime, generate_image],
)

root_agent = Agent(
    name="slack_bot_agent",
    model=MODEL_NAME,
    instruction="""
You are acting as a Slack Bot. All your responses must be formatted using Slack-compatible Markdown.

### Speaker Identification
- Each user message begins with a `[Speaker: <name>]` tag identifying who sent it.
- Your own previous responses (model messages) do NOT have a speaker tag — those are yours.
- When summarizing discussions, attributing opinions, or referring to what someone said,
  always use the speaker's name (e.g., "Tanaka said …", "Suzuki suggested …").
- If asked to summarize a thread, list each person's key points by name.
- Do NOT include the `[Speaker: ...]` tag in your replies.

### Image Generation
- When the user asks you to create, draw, generate, or design an image, use the `generate_image` tool.
- Available models:
  - `gemini-3.1-flash-image-preview` (Nanobanana 2): Fast generation (default)
  - `gemini-3-pro-image-preview` (Nanobanana Pro): Higher quality
- If the user requests a specific model or quality level, set the `model` parameter accordingly.
- Write a detailed, descriptive prompt for best results.
- Generated images will be automatically uploaded to the Slack thread.

### Formatting Rules
- **Headings / emphasis**: Use `*bold*` for section titles or important words.
- *Italics*: Use `_underscores_` for emphasis when needed.
- Lists: Use `-` for unordered lists, and `1.` for ordered lists.
- Code snippets: Use triple backticks (```) for multi-line code blocks, and backticks (`) for inline code.
- Links: Use `<https://example.com|display text>` format.
- Blockquotes: Use `>` at the beginning of a line.

Always structure your response clearly, using these rules so it renders correctly in Slack.""",
    tools=[
        skill_toolset,
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
        await client.reactions_add(channel=channel, timestamp=message_ts, name=REACTION_PROCESSING)
    except Exception:
        pass

    user_content = await _build_content_from_event(event)

    # Prepend speaker identification to the current message
    speaker_name = await _resolve_user_name(client, user_id)
    speaker_prefix = types.Part.from_text(text=f"[Speaker: {speaker_name}]")
    user_content = types.Content(role="user", parts=[speaker_prefix] + list(user_content.parts))

    try:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=thread_ts
        )
    except Exception:
        pass

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=thread_ts
    )
    # Store session_id in state so the generate_image tool can key images
    if session:
        session.state["_session_id"] = thread_ts
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

    # Upload any images generated by the generate_image tool
    generated_images = get_and_clear_images(thread_ts)
    for idx, image_bytes in enumerate(generated_images, start=1):
        try:
            await client.files_upload_v2(
                channel=channel,
                thread_ts=thread_ts,
                filename=f"generated-image-{idx}.png",
                title=f"Generated image {idx}",
                file=io.BytesIO(image_bytes),
            )
        except Exception:
            logger.exception("Failed to upload generated image %d", idx)

    # Add ✅ reaction to indicate the reply is complete
    try:
        await client.reactions_add(channel=channel, timestamp=message_ts, name=REACTION_COMPLETED)
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
