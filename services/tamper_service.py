from __future__ import annotations

import uuid
import base64
from io import BytesIO
from pathlib import Path
from functools import lru_cache
from typing import Dict, List

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageOps

from tensorflow.keras.models import load_model


class TamperDetector:
    """
    ELA + CNN tamper detector using ELA_Model.keras (CASIA 2.0, DenseNet121).

    Output class mapping (matches Kaggle training script):
      pred[0] → Authentic / Real   (label index 0)
      pred[1] → Tampered           (label index 1)

    Returns:
      - label        : "REAL IMAGE" | "TAMPERED IMAGE"
      - confidence   : 0..1
      - heatmap_url  : URL of JET-colourmap ELA overlay saved to heatmap_dir
      - ela_sweep    : list of {quality, b64} for 6-step quality grid
    """

    # Six JPEG qualities for the visual sweep panel
    ELA_QUALITIES = [95, 90, 85, 80, 75, 70]

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = self._load_model()

    def _load_model(self):
        model = load_model(self.model_path)
        # Warm-up pass so first real prediction isn't slow
        dummy = np.zeros((1, 128, 128, 3), dtype=np.float32)
        model(dummy, training=False)
        return model

    # ── ELA core ─────────────────────────────────────────────────────────
    def _convert_to_ela(self, image: Image.Image, quality: int = 90) -> Image.Image:
        """
        Standard ELA: re-save as JPEG at `quality`, reload, return abs diff.
        Brightness is scaled so the max channel difference maps to 255 —
        this matches the convert_to_ela_image() function used during training
        in the Kaggle notebook, which the model was trained on.
        """
        buf = BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        recompressed = Image.open(buf).convert("RGB")

        diff    = ImageChops.difference(image.convert("RGB"), recompressed)
        extrema = diff.getextrema()
        max_d   = max(sum(ex[1] for ex in extrema) / 3, 1)
        diff    = ImageEnhance.Brightness(diff).enhance(255.0 / max_d)
        return diff

    # ── Heatmap overlay ───────────────────────────────────────────────────
    def _make_heatmap_overlay(
        self,
        original: Image.Image,
        ela: Image.Image,
        amplify: float = 15.0,
        alpha: float = 0.55,
    ) -> Image.Image:
        """
        Amplify ELA → JET colourmap → blend onto original.
        cv2.addWeighted ensures the overlay is always visible regardless of
        how small the raw ELA differences are.
        """
        W, H = original.size

        ela_gray    = np.array(ImageOps.grayscale(ela), dtype=np.float32)
        ela_amp     = np.clip(ela_gray * amplify, 0, 255).astype(np.uint8)
        ela_resized = cv2.resize(ela_amp, (W, H), interpolation=cv2.INTER_LINEAR)
        heatmap_bgr = cv2.applyColorMap(ela_resized, cv2.COLORMAP_JET)

        orig_bgr = cv2.cvtColor(np.array(original.convert("RGB"), dtype=np.uint8),
                                cv2.COLOR_RGB2BGR)
        blended  = cv2.addWeighted(orig_bgr, 1.0 - alpha, heatmap_bgr, alpha, 0)
        return Image.fromarray(cv2.cvtColor(blended, cv2.COLOR_BGR2RGB))

    # ── ELA sweep ─────────────────────────────────────────────────────────
    def _ela_sweep(self, image: Image.Image) -> List[Dict]:
        """
        Return a list of {quality, b64} dicts — one per entry in ELA_QUALITIES.
        Each b64 is a PNG-encoded ELA image ready for <img src="data:…">.
        """
        results = []
        for q in self.ELA_QUALITIES:
            ela = self._convert_to_ela(image, quality=q)
            buf = BytesIO()
            ela.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            results.append({"quality": q, "b64": b64})
        return results

    # ── ELA sweep (public helper) ──────────────────────────────────────────
    def ela_sweep_from_path(self, image_path: str) -> List[Dict]:
        """
        Generate the 6-quality ELA sweep from a file path.
        Called by the report route so the sweep is never transmitted
        over the network — it is always regenerated server-side.
        """
        image = Image.open(image_path).convert("RGB")
        return self._ela_sweep(image)

    # ── Predict ───────────────────────────────────────────────────────────
    def predict(self, image_path: str, heatmap_dir: Path) -> Dict[str, object]:
        original = Image.open(image_path).convert("RGB")

        # ── ELA at q=90 for model input ──────────────────────────────────
        ela = self._convert_to_ela(original, quality=90)
        arr = np.array(ela.resize((128, 128)), dtype=np.float32) / 255.0
        arr = arr.reshape(1, 128, 128, 3)

        pred = self.model.predict(arr, verbose=0)[0]   # shape (2,)

        # Class mapping from the Kaggle training notebook:
        #   Y label 0 → Real,    Y label 1 → Tampered
        #   to_categorical preserved that order, so:
        #   pred[0] = P(Real), pred[1] = P(Tampered)
        real_conf    = float(pred[0])
        tamper_conf  = float(pred[1])

        if tamper_conf > real_conf:
            label      = "TAMPERED IMAGE"
            confidence = tamper_conf
        else:
            label      = "REAL IMAGE"
            confidence = real_conf

        # ── Save heatmap overlay ──────────────────────────────────────────
        heatmap = self._make_heatmap_overlay(original, ela)
        heatmap_dir.mkdir(parents=True, exist_ok=True)
        name     = f"{uuid.uuid4().hex}.png"
        out_path = heatmap_dir / name
        heatmap.save(out_path, format="PNG", optimize=True)

        # ── ELA quality sweep (all 6 qualities, base64-encoded) ──────────
        ela_sweep = self._ela_sweep(original)

        return {
            "label"      : label,
            "confidence" : max(0.0, min(1.0, confidence)),
            "heatmap_url": f"/outputs/heatmaps/{name}",
            "ela_sweep"  : ela_sweep,
        }
