import datetime
import pytz
from google.adk.tools import ToolContext


async def get_current_datetime(timezone: str, tool_context: ToolContext):
    """Gets the current date and time for a given timezone.

    Args:
        timezone: The timezone to get the current time from. Defaults to "America/Los_Angeles".
    """
    if not timezone:
        timezone = "America/Los_Angeles"
    try:
        tz = pytz.timezone(timezone)
        now = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        return {"current_datetime": now}
    except pytz.UnknownTimeZoneError:
        return {"error": f"Unknown timezone: {timezone}"}
