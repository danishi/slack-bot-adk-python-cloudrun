import os
import asyncio
import json
from typing import List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from google import genai
from google.genai import types
from google.genai.types import Tool, GenerateContentConfig

# Environment variables
load_dotenv()
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
PROJECT_ID = os.environ.get("GOOGLE_PROJECT")
LOCATION = os.environ.get("GOOGLE_LOCATION", "us-central1")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")
ALLOWED_SLACK_WORKSPACE = os.environ.get("ALLOWED_SLACK_WORKSPACE")

# Initialize Slack Bolt AsyncApp
bolt_app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
handler = AsyncSlackRequestHandler(bolt_app)

fastapi_app = FastAPI()

async def _build_contents_from_thread(client, channel: str, thread_ts: str) -> List[types.Content]:
    """Fetch thread messages and build google-genai contents."""
    history = await client.conversations_replies(channel=channel, ts=thread_ts, limit=50)
    contents: List[types.Content] = []

    import re
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for msg in sorted(history["messages"], key=lambda m: float(m["ts"])):
            is_bot = bool(msg.get("bot_id") or msg.get("subtype") == "bot_message")
            role = "model" if is_bot else "user"
            parts = []

            text = msg.get("text") or ""
            text = re.sub(r"<@[^>]+>\s*", "", text).strip()
            if text:
                parts.append(types.Part.from_text(text=text))

            for f in msg.get("files", []):
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

            if parts:
                contents.append(types.Content(role=role, parts=parts))

    if not contents:
        contents = [types.Content(role="user", parts=[types.Part.from_text(text="(no content)")])]
    return contents

@bolt_app.event("app_mention")
async def handle_mention(body, say, client, logger, ack):
    # Ack as soon as possible to avoid Slack retries that can cause duplicated responses
    await ack()
    
    event = body["event"]
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]

    contents = await _build_contents_from_thread(client, channel, thread_ts)

    def call_gemini() -> str:
        genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
        response = genai_client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=GenerateContentConfig(
                system_instruction="""
                You are acting as a Slack Bot. All your responses must be formatted using Slack-compatible Markdown.

                ### Formatting Rules
                - **Headings / emphasis**: Use `*bold*` for section titles or important words.
                - *Italics*: Use `_underscores_` for emphasis when needed.
                - Lists: Use `-` for unordered lists, and `1.` for ordered lists.
                - Code snippets: Use triple backticks (```) for multi-line code blocks, and backticks (`) for inline code.
                - Links: Use `<https://example.com|display text>` format.
                - Blockquotes: Use `>` at the beginning of a line.

                Always structure your response clearly, using these rules so it renders correctly in Slack.
                """,
                tools=[
                    {"url_context": {}},
                    {"google_search": {}},
                ],
            )
        )
        return response.text

    try:
        reply_text = await asyncio.to_thread(call_gemini)
    except Exception as e:
        logger.exception("Gemini call failed")
        reply_text = f"Error from Gemini: {e}"

    await say(
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": reply_text}}],
        text=reply_text,
        thread_ts=thread_ts,
    )

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
