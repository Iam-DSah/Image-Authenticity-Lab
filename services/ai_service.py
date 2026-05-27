from __future__ import annotations

from functools import lru_cache
from typing import Dict

import torch
import timm
from PIL import Image
from torchvision import transforms
from torchvision.transforms import InterpolationMode


class AIImageClassifier:
    """
    AI vs Real classifier based on your notebook function predict_ai_image()
    using ViT base patch16 224 from timm and a saved .pth state_dict.

    Expected classes: index 0 and 1. We'll map them to labels:
      0 -> AI Generated
      1 -> Real

    If your training used different mapping, adjust LABELS below.
    """

    LABELS = {
        0: "AI GENERATED",
        1: "REAL",
    }

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self._load_model()
        self.transform = self._build_transform()

    @lru_cache(maxsize=1)
    def _load_model(self):
        model = timm.create_model("vit_base_patch16_224", pretrained=False, num_classes=2)
        state = torch.load(self.model_path, map_location=self.device)
        model.load_state_dict(state)
        model.to(self.device)
        model.eval()
        return model

    def _build_transform(self):
        # Mirror common ViT test-time transform (resize->center crop->normalize)
        return transforms.Compose([
            transforms.Resize(256, interpolation=InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    @torch.no_grad()
    def predict(self, image_path: str) -> Dict[str, object]:
        img = Image.open(image_path).convert("RGB")
        x = self.transform(img).unsqueeze(0).to(self.device)

        logits = self.model(x)
        probs = torch.softmax(logits, dim=1)[0]
        idx = int(torch.argmax(probs).item())
        confidence = float(probs[idx].item())
        label = self.LABELS.get(idx, f"CLASS_{idx}")

        return {
            "label": label,
            "confidence": max(0.0, min(1.0, confidence)),
        }
