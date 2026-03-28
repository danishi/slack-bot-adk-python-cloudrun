import asyncio
import contextvars
import os
import threading
from typing import List

from google import genai
from google.adk.tools import ToolContext
from google.genai.types import GenerateContentConfig, Modality

# Default image generation model (Nanobanana 2)
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

# Thread-safe storage for generated images keyed by session_id
_generated_images: dict[str, List[bytes]] = {}
_images_lock = threading.Lock()

# ContextVar set by the request handler before running the agent
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id", default="unknown"
)


def get_and_clear_images(session_id: str) -> List[bytes]:
    """Retrieve and remove generated images for a session."""
    with _images_lock:
        return _generated_images.pop(session_id, [])


async def generate_image(prompt: str, tool_context: ToolContext, model: str = ""):
    """Generates images using Gemini image generation models (Nanobanana Pro / Nanobanana 2).

    Use this tool when the user asks you to create, draw, generate, or design an image.

    Args:
        prompt: A detailed description of the image to generate.
        model: The model to use for image generation.
               Use "gemini-3-pro-image-preview" (Nanobanana Pro) for higher quality.
               Use "gemini-3.1-flash-image-preview" (Nanobanana 2) for faster generation.
               Defaults to Nanobanana 2 if not specified.
    """
    image_model = model if model else os.environ.get(
        "IMAGE_MODEL_NAME", DEFAULT_IMAGE_MODEL
    )

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

    def call_gemini():
        client = genai.Client(vertexai=True, project=project_id, location=location)
        response = client.models.generate_content(
            model=image_model,
            contents=prompt,
            config=GenerateContentConfig(
                response_modalities=[Modality.TEXT, Modality.IMAGE],
            ),
        )
        return response

    try:
        response = await asyncio.to_thread(call_gemini)
    except Exception as e:
        return {"error": f"Image generation failed: {e}"}

    text_parts = []
    images = []

    candidates = getattr(response, "candidates", None)
    if candidates:
        for part in candidates[0].content.parts or []:
            if getattr(part, "thought", None):
                continue
            if getattr(part, "text", None):
                text_parts.append(part.text)
                continue
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                images.append(inline.data)

    if not images:
        return {
            "status": "no_image_generated",
            "text": "\n".join(text_parts) if text_parts else "",
            "note": "No image was produced. Tell the user in their language.",
        }

    # Store images for the main handler to upload to Slack
    session_id = current_session_id.get()
    with _images_lock:
        _generated_images.setdefault(session_id, []).extend(images)

    return {
        "status": "success",
        "model": image_model,
        "image_count": len(images),
        "text": "\n".join(text_parts) if text_parts else "",
        "note": f"{len(images)} image(s) generated. Inform the user in their language.",
    }
