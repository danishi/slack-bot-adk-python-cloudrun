"""Mock Service MCP Server.

A minimal, dependency-free sample MCP server that exposes a read-only "user
directory" backed by the public mock REST API at https://jsonplaceholder.typicode.com.

It is intended as a template: swap the base URL and tool implementations for your
own backend (internal API, database, SaaS service, etc.) to turn this into a real integration.
"""

import json

import httpx
from mcp.server.fastmcp import FastMCP

# Base URL of the backend service. This sample is hardcoded to the public
# JSONPlaceholder mock API — swap this literal for your own backend to build
# a real integration.
MOCK_API_BASE_URL = "https://jsonplaceholder.typicode.com"

mcp = FastMCP("mock-service")


async def _api_get(path: str) -> object:
    """Make a GET request to the mock service and return parsed JSON."""
    url = f"{MOCK_API_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _summarize_user(user: dict) -> dict:
    """Pick the most useful fields from a user record for list views."""
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "username": user.get("username"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "company": (user.get("company") or {}).get("name"),
        "city": (user.get("address") or {}).get("city"),
    }


@mcp.tool()
async def list_users() -> str:
    """List all users registered in the mock service.

    Returns a JSON array of users with their id, name, username, email, phone,
    company name, and city. Use `get_user` to fetch the full detail of one user.
    """
    users = await _api_get("/users")
    summary = [_summarize_user(u) for u in users]
    return json.dumps(
        {"count": len(summary), "users": summary},
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def get_user(user_id: int) -> str:
    """Get the full detail of a single user by their numeric id.

    Args:
        user_id: The numeric id of the user to retrieve (e.g. 1, 2, 3). The mock
            service currently holds users with ids 1 through 10.
    """
    user = await _api_get(f"/users/{user_id}")
    return json.dumps(user, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
