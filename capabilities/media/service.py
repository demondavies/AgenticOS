"""
Media capability — image generation service.

Calls any Stable Diffusion-compatible API (Automatic1111, ComfyUI,
or any server that exposes POST /sdapi/v1/txt2img).  The service
is disabled by default; set IMAGE_GEN_ENABLED=True in core/config.py
to activate it.

Returns the absolute path of the saved PNG on success.
"""

from __future__ import annotations

import base64
import datetime
import json
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ImageResult:
    """Result of a single image generation request."""

    path: str
    prompt: str
    negative_prompt: str
    steps: int
    width: int
    height: int

    def __str__(self) -> str:
        return (
            f"Image saved: {self.path}\n"
            f"Prompt: {self.prompt}\n"
            f"Steps: {self.steps} | Size: {self.width}x{self.height}"
        )


class ImageGenService:
    """
    Thin wrapper around a Stable Diffusion-compatible txt2img endpoint.

    The host, output directory, and default parameters are supplied by
    the caller (from core/config.py constants) so this class stays free
    of any direct config import.
    """

    def __init__(
        self,
        *,
        host: str = "http://127.0.0.1:7860",
        output_dir: str = "./media_output",
        enabled: bool = False,
    ) -> None:
        self.host = host.rstrip("/")
        self.output_dir = pathlib.Path(output_dir)
        self.enabled = enabled

    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        steps: int = 20,
        width: int = 512,
        height: int = 512,
        seed: int = -1,
    ) -> ImageResult:
        """
        Generate an image and save it to output_dir.

        Raises RuntimeError when IMAGE_GEN_ENABLED is False or the
        upstream API returns an error.
        """

        if not self.enabled:
            raise RuntimeError(
                "Image generation is disabled. "
                "Set IMAGE_GEN_ENABLED=True in core/config.py to enable it."
            )

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": steps,
            "width": width,
            "height": height,
            "seed": seed,
            "save_images": False,
        }

        url = f"{self.host}/sdapi/v1/txt2img"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Image generation API unreachable at {url}: {exc}"
            ) from exc

        images = body.get("images", [])
        if not images:
            raise RuntimeError(
                "Image generation API returned no images."
            )

        # Save the first image
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"arnie_{timestamp}.png"
        out_path = self.output_dir / filename

        image_bytes = base64.b64decode(images[0])
        out_path.write_bytes(image_bytes)

        return ImageResult(
            path=str(out_path.resolve()),
            prompt=prompt,
            negative_prompt=negative_prompt,
            steps=steps,
            width=width,
            height=height,
        )
