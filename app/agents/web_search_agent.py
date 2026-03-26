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
        "An agent that searches the web for information. "
        "Looks up details such as official name, website, address, phone number, and industry about companies or organizations."
    ),
    instruction="""\
You are a web search specialist agent.
Search the web for information about the requested topic, company, or organization and return:
- Official name
- Official website URL
- Headquarters address
- Main phone number
- Industry / business description
- English name or abbreviation (if available)

Return the results in a structured format. If any information cannot be found, explicitly note it as "Unknown".
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
        "Retrieves page content from a given URL and extracts the required information."
    ),
    instruction="""\
You are a URL content retrieval specialist agent.
Fetch the content of the specified URL and extract the relevant information as requested.
""",
    tools=[
        url_context,
    ],
)
