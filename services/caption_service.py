from __future__ import annotations

import os
from functools import lru_cache
from typing import Tuple

import torch
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration


class Captioner:
    """BLIP captioning for any uploaded image."""

    def __init__(self, model_name: str = "Salesforce/blip-image-captioning-base"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_name = model_name
        self.processor, self.model = self._load()

    @lru_cache(maxsize=1)
    def _load(self) -> Tuple[BlipProcessor, BlipForConditionalGeneration]:
        processor = BlipProcessor.from_pretrained(self.model_name)
        model = BlipForConditionalGeneration.from_pretrained(self.model_name).to(self.device)
        model.eval()
        return processor, model

    def caption_file(self, image_path: str, max_new_tokens: int = 30) -> str:
        image = Image.open(image_path).convert("RGB")
        return self.caption_image(image, max_new_tokens=max_new_tokens)

    def caption_image(self, image: Image.Image, max_new_tokens: int = 30) -> str:
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
        return self.processor.decode(out[0], skip_special_tokens=True)
