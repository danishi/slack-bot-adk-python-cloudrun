# Slack Bot using Google Agent Development Kit (Python, Cloud Run)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/danishi/slack-bot-adk-python-cloudrun)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)

<img width="1024" alt="image" src="https://github.com/user-attachments/assets/815339c0-5299-498e-8372-d03acc442830" />

This repository provides a Slack bot backend implemented in Python that uses [Slack Bolt](https://slack.dev/bolt-python) and Google Cloud's [Vertex AI Gemini](https://cloud.google.com/vertex-ai) model via the [Agent Development Kit](https://google.github.io/adk-docs/). The bot responds to text, images, PDFs, plain text files, videos, and audio messages, while maintaining conversation context within Slack threads. It is designed to run on [Cloud Run](https://cloud.google.com/run).

If you want to use the [Google Gen AI SDK](https://googleapis.github.io/python-genai/), please refer to [this repository](https://github.com/danishi/slack-gemini-bot-on-google-cloud)💡

If you want a simpler, lightweight Slack bot without the ADK framework, check out [Nano Banana](https://github.com/danishi/slack-nano-banana-bot-on-google-cloud)🍌

## Features
- Responds to `@mention` messages in Slack channels.
- Supports text, image, PDF, text file, video, and audio inputs from Slack messages. Files are fetched via authenticated URLs and sent to Gemini for multimodal understanding.
- Maintains conversation context by retrieving prior messages in a thread and sending them as conversation history to Gemini.
- Formats responses using Slack-compatible Markdown for rich text output.
- FastAPI-based web server suitable for Cloud Run.
- Deployment script for building and deploying to Cloud Run.

## Project Structure
```
app/
  main.py           # FastAPI app and Slack Bolt handlers
  agents/
    comedian.py     # ex: Comedian agent implementation
  tools/
    get_current_datetime.py  # ex: Date/time utility tool
scripts/
  deploy.sh         # Helper script to deploy to Cloud Run
Dockerfile          # Container definition for Cloud Run
requirements.txt    # Python dependencies
llms.txt           # ADK documentation for LLM reference
llms-full.txt      # Extended ADK documentation for LLM context
```

## Prerequisites
- Python 3.13
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
   # ALLOWED_SLACK_WORKSPACES is a comma-separated list of Slack team IDs to allow requests from
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
   - `reactions:write`
   - `users:read`
3. Install the app to your workspace to obtain `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`.
4. Enable **Event Subscriptions** and set the Request URL to `https://<your-cloud-run-service-url>/slack/events`.
5. Subscribe to bot events: `app_mention`.
6. Invite the bot to channels where you want to use it.

### Getting Slack Workspace (Team) IDs for `ALLOWED_SLACK_WORKSPACES`
To restrict the bot to specific Slack workspaces, set `ALLOWED_SLACK_WORKSPACES` in your `.env` with comma-separated team IDs. You can find your workspace's team ID by:
1. Open your Slack workspace in a browser.
2. The team ID is the `T`-prefixed value in the URL (e.g., `https://app.slack.com/client/T0123456789/...`).
3. Or go to your [Slack App settings](https://api.slack.com/apps), select your app, and find the **Team ID** displayed under **App Credentials** on the **Basic Information** page.

Example:
```
ALLOWED_SLACK_WORKSPACES="T0123456789,T9876543210"
```
If the variable is empty or unset, requests from all workspaces are allowed.

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
