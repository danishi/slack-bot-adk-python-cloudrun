---
name: datetime-skill
description: A skill that provides current date and time information for any timezone using the get_current_datetime tool.
metadata:
  adk_additional_tools:
    - get_current_datetime
---

Step 1: Identify the timezone the user is asking about. If no timezone is specified, check 'references/default_timezones.md' for common defaults.
Step 2: Use the `get_current_datetime` tool with the appropriate timezone identifier (e.g., "Asia/Tokyo", "America/New_York").
Step 3: Format the result clearly for the user, including the timezone name and the current date/time.
