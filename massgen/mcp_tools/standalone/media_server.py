"""Standalone MCP server exposing MassGen media tools (generate_media, read_media).

Wraps the existing multimodal tool implementations with explicit parameters
instead of the @context_params decorator. Requires massgen to be installed
and relevant API keys in the environment.

Usage:
    python -m massgen.mcp_tools.standalone.media_server
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import fastmcp

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_media_tools"

mcp = fastmcp.FastMCP(SERVER_NAME)


def _extract_text_from_result(result: Any) -> str:
    """Extract text content from an ExecutionResult or similar return value."""
    if isinstance(result, str):
        return result
    if hasattr(result, "output_blocks"):
        texts = []
        for block in result.output_blocks:
            if hasattr(block, "data"):
                texts.append(str(block.data))
            elif hasattr(block, "text"):
                texts.append(str(block.text))
        return "\n".join(texts) if texts else str(result)
    return str(result)


@mcp.tool(
    name="generate_media",
    description=(
        "Generate media content from a text prompt.\n\n"
        "Modes:\n"
        "- 'image': Text-to-image or image-to-image (provide input_images)\n"
        "- 'video': Text-to-video or image-to-video (provide input_images)\n"
        "- 'audio': Text-to-speech, music, or sound effects (set audio_type)\n\n"
        "Backend auto-selects based on available API keys. Override with backend_type.\n"
        "Image backends: google (Gemini), openai, grok, openrouter\n"
        "Video backends: grok, google (Veo), openai (Sora)\n"
        "Audio backends: elevenlabs, openai\n\n"
        "For audio: prompt is the TEXT TO SPEAK. Use 'instructions' for tone/style."
    ),
)
async def generate_media(
    prompt: str | None = None,
    mode: str = "image",
    prompts: list[str] | None = None,
    input_images: list[str] | None = None,
    backend_type: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    size: str | None = None,
    aspect_ratio: str | None = None,
    duration: int | None = None,
    voice: str | None = None,
    audio_type: str = "speech",
    instructions: str | None = None,
    audio_format: str | None = None,
    input_audio: str | None = None,
    voice_samples: list[str] | None = None,
    speed: float | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    continue_from: str | None = None,
    storage_path: str | None = None,
    max_concurrent: int = 4,
) -> str:
    """Generate media content (images, video, audio)."""
    try:
        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media as _generate_media,
        )
    except ImportError:
        return json.dumps(
            {
                "status": "error",
                "error": "massgen media tools not available. Install massgen package.",
            },
        )

    cwd = Path.cwd()

    kwargs: dict[str, Any] = {
        "mode": mode,
        "agent_cwd": str(cwd),
        "allowed_paths": [str(cwd)],
    }

    # Only pass non-None values to avoid overriding defaults
    if prompt is not None:
        kwargs["prompt"] = prompt
    if prompts is not None:
        kwargs["prompts"] = prompts
    if input_images is not None:
        kwargs["input_images"] = input_images
    if backend_type is not None:
        kwargs["backend_type"] = backend_type
    if model is not None:
        kwargs["model"] = model
    if quality is not None:
        kwargs["quality"] = quality
    if size is not None:
        kwargs["size"] = size
    if aspect_ratio is not None:
        kwargs["aspect_ratio"] = aspect_ratio
    if duration is not None:
        kwargs["duration"] = duration
    if voice is not None:
        kwargs["voice"] = voice
    if audio_type != "speech":
        kwargs["audio_type"] = audio_type
    if instructions is not None:
        kwargs["instructions"] = instructions
    if audio_format is not None:
        kwargs["audio_format"] = audio_format
    if input_audio is not None:
        kwargs["input_audio"] = input_audio
    if voice_samples is not None:
        kwargs["voice_samples"] = voice_samples
    if speed is not None:
        kwargs["speed"] = speed
    if negative_prompt is not None:
        kwargs["negative_prompt"] = negative_prompt
    if seed is not None:
        kwargs["seed"] = seed
    if continue_from is not None:
        kwargs["continue_from"] = continue_from
    if storage_path is not None:
        kwargs["storage_path"] = storage_path
    kwargs["max_concurrent"] = max_concurrent

    try:
        result = await _generate_media(**kwargs)
        return _extract_text_from_result(result)
    except Exception as exc:
        logger.exception("generate_media failed")
        return json.dumps(
            {
                "status": "error",
                "error": f"Media generation failed: {exc}",
            },
        )


@mcp.tool(
    name="read_media",
    description=(
        "Analyze media files using AI vision/audio models with a critical-first "
        "lens. The model identifies problems, classifies severity (fundamental "
        "vs surface-level), and assesses whether the approach is sound.\n\n"
        "All files in file_paths are sent TOGETHER in a single call — critical "
        "for before/after comparison. The model sees all files side-by-side.\n\n"
        "For follow-up questions on the same media, use continue_from with the "
        "conversation_id from a previous response.\n\n"
        "Formats: png/jpg/gif/webp (images), mp4/mov/mkv (video), mp3/wav/m4a (audio)"
    ),
)
async def read_media(
    prompt: str | None = None,
    file_paths: list[str] | None = None,
    continue_from: str | None = None,
    backend_type: str | None = None,
    model: str | None = None,
    max_concurrent: int = 4,
) -> str:
    """Analyze media files with critical-first lens."""
    try:
        from massgen.tool._multimodal_tools.read_media import read_media as _read_media
    except ImportError:
        return json.dumps(
            {
                "status": "error",
                "error": "massgen media tools not available. Install massgen package.",
            },
        )

    if not file_paths and not continue_from:
        return json.dumps(
            {
                "status": "error",
                "error": "Provide file_paths (list of paths) or continue_from (conversation_id).",
            },
        )

    cwd = Path.cwd()

    # Convert file paths to single input dict — all files together for comparison
    inputs = None
    if file_paths:
        files = {f"file_{i}": fp for i, fp in enumerate(file_paths)}
        inputs = [{"files": files}]

    kwargs: dict[str, Any] = {
        "inputs": inputs,
        "max_concurrent": max_concurrent,
        "agent_cwd": str(cwd),
        "allowed_paths": [str(cwd)],
    }
    if prompt is not None:
        kwargs["prompt"] = prompt
    if continue_from is not None:
        kwargs["continue_from"] = continue_from
    if backend_type is not None:
        kwargs["backend_type"] = backend_type
    if model is not None:
        kwargs["model"] = model

    try:
        result = await _read_media(**kwargs)
        return _extract_text_from_result(result)
    except Exception as exc:
        logger.exception("read_media failed")
        return json.dumps(
            {
                "status": "error",
                "error": f"Media analysis failed: {exc}",
            },
        )


if __name__ == "__main__":
    mcp.run()
