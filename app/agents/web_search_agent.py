import os
from google.adk import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools import url_context
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.1-pro-preview")

web_search_agent = Agent(
    model=MODEL_NAME,
    name="web_search_agent",
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="LOW",
        )
    ),
    description=(
        "An agent that searches the web for up-to-date information on any topic. "
        "Use this when the user asks about recent events, facts, documentation, or anything that may require live web data."
    ),
    instruction="""\
You are a web search specialist agent.
Search the web for the requested information and return clear, accurate, and well-structured results.
Include source URLs where possible so the user can verify the information.
If detailed information from a specific URL is needed, ask the url_fetch_agent to retrieve it.
""",
    tools=[
        GoogleSearchTool(),
    ],
)

url_fetch_agent = Agent(
    model=MODEL_NAME,
    name="url_fetch_agent",
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="LOW",
        )
    ),
    description=(
        "An agent that fetches and extracts content from web pages. "
        "Use this when detailed information from a specific URL is needed."
    ),
    instruction="""\
You are a URL content retrieval specialist agent.
Fetch the content of the specified URL and extract the relevant information as requested.
""",
    tools=[
        url_context,
    ],
)
