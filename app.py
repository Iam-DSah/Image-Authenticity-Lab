# app.py
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Tuple

from flask import Flask, jsonify, make_response, render_template, request, send_from_directory, send_file

from services.tamper_service import TamperDetector
from services.ai_service import AIImageClassifier
from services.caption_service import Captioner
from services.report_service import ReportService
from services.metadata_service import MetadataExtractor

ALLOWED_EXTS = {"jpg", "jpeg", "png"}


def create_app() -> Flask:
    app = Flask(__name__)

    root = Path(__file__).resolve().parent
    app.config["ROOT_DIR"]     = str(root)
    app.config["UPLOAD_DIR"]   = str(root / "static" / "uploads")
    app.config["HEATMAP_DIR"]  = str(root / "outputs" / "heatmaps")
    app.config["REPORT_DIR"]   = str(root / "outputs" / "reports")
    app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB

    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["HEATMAP_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["REPORT_DIR"]).mkdir(parents=True, exist_ok=True)

    # ── Load models once ──────────────────────────────────────────────────
    # Forgery detector: ELA_Model.keras  (CASIA 2.0, DenseNet121)
    # Falls back to best_model.keras if ELA_Model.keras is missing.
    _forgery_candidates = ["ELA_Model.keras", "best_model.keras"]
    _forgery_path = None
    for _name in _forgery_candidates:
        _p = root / "models" / _name
        if _p.exists():
            _forgery_path = str(_p)
            break
    if _forgery_path is None:
        raise FileNotFoundError(
            "No forgery model found in models/. "
            "Place ELA_Model.keras or best_model.keras there."
        )

    tamper_detector    = TamperDetector(model_path=_forgery_path)
    ai_classifier      = AIImageClassifier(model_path=str(root / "models" / "best_vit_model.pth"))
    captioner          = Captioner()
    metadata_extractor = MetadataExtractor()

    # ── Routes ────────────────────────────────────────────────────────────
    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/outputs/heatmaps/<path:filename>")
    def serve_heatmap(filename: str):
        return send_from_directory(app.config["HEATMAP_DIR"], filename)

    # ── Forgery detection ─────────────────────────────────────────────────
    @app.post("/api/forgery-detect")
    def api_forgery_detect():
        try:
            saved_path, public_url = _save_uploaded_image(app)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        image_caption = captioner.caption_file(saved_path)
        metadata      = MetadataExtractor.extract(saved_path)

        pred = tamper_detector.predict(
            saved_path,
            heatmap_dir=Path(app.config["HEATMAP_DIR"]),
        )

        output_caption = _caption_for_output(
            task="forgery",
            label=pred.get("label", ""),
            confidence=float(pred.get("confidence", 0.0) or 0.0),
        )

        return jsonify({
            "ok":                True,
            "task":              "forgery",
            "uploaded_image_url": public_url,
            "label":             pred.get("label", ""),
            "confidence":        float(pred.get("confidence", 0.0) or 0.0),
            "confidence_percent": round(float(pred.get("confidence", 0.0) or 0.0) * 100, 2),
            "heatmap_url":       pred.get("heatmap_url"),
            # NEW: 6-quality ELA sweep for the visual grid
            "ela_sweep":         pred.get("ela_sweep", []),
            "caption_image":     image_caption,
            "caption_output":    output_caption,
            "metadata":          metadata,
        })

    # ── AI classification ─────────────────────────────────────────────────
    @app.post("/api/ai-classify")
    def api_ai_classify():
        try:
            saved_path, public_url = _save_uploaded_image(app)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        image_caption = captioner.caption_file(saved_path)
        metadata      = MetadataExtractor.extract(saved_path)
        pred          = ai_classifier.predict(saved_path)

        output_caption = _caption_for_output(
            task="ai",
            label=pred.get("label", ""),
            confidence=float(pred.get("confidence", 0.0) or 0.0),
        )

        return jsonify({
            "ok":                True,
            "task":              "ai",
            "uploaded_image_url": public_url,
            "label":             pred.get("label", ""),
            "confidence":        float(pred.get("confidence", 0.0) or 0.0),
            "confidence_percent": round(float(pred.get("confidence", 0.0) or 0.0) * 100, 2),
            "caption_image":     image_caption,
            "caption_output":    output_caption,
            "metadata":          metadata,
        })

    # ── PDF report ────────────────────────────────────────────────────────
    @app.post("/api/report")
    def api_report():
        payload = request.get_json(silent=True) or {}

        task = (payload.get("task") or "").strip().lower()
        if task not in {"forgery", "ai"}:
            return jsonify({"ok": False, "error": "Invalid task."}), 400

        uploaded_url = payload.get("uploaded_image_url")
        if not uploaded_url or not isinstance(uploaded_url, str):
            return jsonify({"ok": False, "error": "Missing uploaded_image_url."}), 400

        heatmap_url    = payload.get("heatmap_url")
        label          = str(payload.get("label") or "")
        caption_image  = str(payload.get("caption_image") or "")
        caption_output = str(payload.get("caption_output") or "")
        # ela_sweep is NOT accepted from the client — it is always regenerated
        # server-side to avoid a 413 (the 6 base64 PNGs are ~15-30 MB over the wire)

        confidence_percent = payload.get("confidence_percent")
        try:
            if confidence_percent is None:
                confidence_percent = float(payload.get("confidence") or 0.0) * 100.0
            confidence_percent = float(confidence_percent)
        except Exception:
            confidence_percent = 0.0

        root_dir   = Path(app.config["ROOT_DIR"])
        upload_dir = Path(app.config["UPLOAD_DIR"])
        heatmap_dir_path = Path(app.config["HEATMAP_DIR"])

        input_path = _url_to_local_path(root_dir, uploaded_url,
                                        upload_dir=upload_dir,
                                        heatmap_dir=heatmap_dir_path)
        if not input_path or not input_path.exists():
            # Log the resolved path so the developer can diagnose
            print(f"[report] input_path not found: {input_path!r}  (from url={uploaded_url!r})")
            return jsonify({
                "ok": False,
                "error": f"Uploaded image not found on server. "
                         f"Expected path: {input_path}",
            }), 400

        heatmap_path = None
        if task == "forgery" and heatmap_url and isinstance(heatmap_url, str):
            hp = _url_to_local_path(root_dir, heatmap_url,
                                    upload_dir=upload_dir,
                                    heatmap_dir=heatmap_dir_path)
            if hp and hp.exists():
                heatmap_path = hp
            else:
                print(f"[report] heatmap not found: {hp!r}  (from url={heatmap_url!r})")

        # Regenerate ELA sweep server-side from the saved upload.
        # Never sent over the network — avoids 413 (6 base64 PNGs ~ 15-30 MB).
        ela_sweep = []
        if task == "forgery":
            try:
                ela_sweep = tamper_detector.ela_sweep_from_path(str(input_path))
            except Exception as sweep_err:
                print(f"[report] ela_sweep generation failed: {sweep_err}")

        try:
            pdf_bytes = ReportService.build_pdf_report(
                task=task,
                input_image_path=input_path,
                heatmap_image_path=heatmap_path,
                label=label,
                confidence_percent=confidence_percent,
                caption_image=caption_image,
                caption_output=caption_output,
                ela_sweep=ela_sweep,
            )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("─── PDF generation error ───────────────────────")
            print(tb)
            print("────────────────────────────────────────────────")
            return jsonify({"ok": False, "error": f"Could not generate PDF: {e}"}), 500

        # Serve directly from memory — no temp file, no path ambiguity
        response = make_response(pdf_bytes)
        response.headers["Content-Type"]        = "application/pdf"
        response.headers["Content-Length"]      = str(len(pdf_bytes))
        response.headers["Content-Disposition"] = 'attachment; filename="analysis-report.pdf"'
        response.headers["Cache-Control"]       = "no-cache, no-store, must-revalidate"
        return response

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────
def _allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTS


def _save_uploaded_image(app: Flask) -> Tuple[str, str]:
    if "image" not in request.files:
        raise ValueError("No file field named 'image' found.")
    f = request.files["image"]
    if not f or f.filename == "":
        raise ValueError("No file selected.")
    if not _allowed_file(f.filename):
        raise ValueError("Only JPG/JPEG/PNG are allowed.")

    ext      = f.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_path = Path(app.config["UPLOAD_DIR"]) / filename
    f.save(save_path)
    return str(save_path), f"/static/uploads/{filename}"


def _caption_for_output(task: str, label: str, confidence: float) -> str:
    pct = confidence * 100
    if task == "forgery":
        if "TAMPERED" in (label or "").upper():
            return f"The system predicts this image is tampered ({pct:.1f}% confidence)."
        return f"The system predicts this image is authentic ({pct:.1f}% confidence)."
    return f"The system predicts: {label} ({pct:.1f}% confidence)."


def _url_to_local_path(
    root_dir: Path,
    url_path: str,
    upload_dir: Path | None = None,
    heatmap_dir: Path | None = None,
) -> Path | None:
    """
    Resolve a public URL path to an absolute filesystem path.
    Uses the explicitly configured UPLOAD_DIR / HEATMAP_DIR when available
    so the mapping stays correct regardless of working directory.
    """
    if url_path.startswith("/static/uploads/"):
        rel = url_path.split("/static/uploads/", 1)[1]
        base = upload_dir if upload_dir else root_dir / "static" / "uploads"
        return base / rel

    if url_path.startswith("/outputs/heatmaps/"):
        rel = url_path.split("/outputs/heatmaps/", 1)[1]
        base = heatmap_dir if heatmap_dir else root_dir / "outputs" / "heatmaps"
        return base / rel

    return None


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
