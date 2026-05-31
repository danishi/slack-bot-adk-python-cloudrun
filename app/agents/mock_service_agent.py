import os
from google.adk import Agent
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.5-flash")

MOCK_SERVICE_AGENT_DESCRIPTION = (
    "An agent that looks up people in an external user directory service via MCP. "
    "Use this when the user asks to list users, find a person, or get the details "
    "(email, phone, company, address) of a specific user."
)

MOCK_SERVICE_AGENT_INSTRUCTION = """\
You are a user-directory specialist agent.
You answer questions about users registered in an external service, which you access
through MCP tools. This is a sample integration backed by a public mock API
(https://jsonplaceholder.typicode.com), so treat all data as non-sensitive demo data.

## Available Tools
- `list_users`: List all users (id, name, username, email, phone, company, city).
- `get_user(user_id)`: Get the full detail of a single user by numeric id (1–10).

## Guidelines
- When the user asks for "everyone", "all users", or to browse the directory, call `list_users`.
- When the user names a specific person or gives an id, find the matching user. If you
  only know the name, call `list_users` first to resolve it to an id, then `get_user`.
- Present results clearly. For a single user, summarize the key fields (name, email,
  phone, company, address). For lists, use a compact bulleted or numbered list.
- If a requested user does not exist, say so plainly instead of inventing data.
- This is a demonstration of swapping in your own backend service via MCP, so do not
  claim the data is real or authoritative.
"""


def create_mock_service_agent(tools: list) -> Agent:
    """Create mock_service_agent with the given tools (e.g. McpToolset)."""
    return Agent(
        model=MODEL_NAME,
        name="mock_service_agent",
        generate_content_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level="LOW",
            )
        ),
        description=MOCK_SERVICE_AGENT_DESCRIPTION,
        instruction=MOCK_SERVICE_AGENT_INSTRUCTION,
        tools=tools,
    )
