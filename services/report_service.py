# services/report_service.py
from __future__ import annotations

import base64
import datetime
import io
import tempfile
import textwrap
from pathlib import Path
from typing import List, Optional

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


class ReportService:
    """
    PDF report generator.

    Forgery report layout:
      Page 1 — Summary KV, captions, input image, heatmap overlay
      Page 2 — ELA Quality Sweep (3-column grid, q = 95 → 70)

    AI report layout:
      Page 1 — Summary KV, captions, input image
    """

    MAX_SIDE_PX  = 1100
    JPEG_QUALITY = 55

    @staticmethod
    def build_pdf_report(
        task: str,
        input_image_path: Path,
        heatmap_image_path: Optional[Path],
        label: str,
        confidence_percent: float,
        caption_image: str,
        caption_output: str,
        ela_sweep: Optional[List[dict]] = None,
    ) -> bytes:
        """
        Returns the PDF as bytes (written to BytesIO — no temp file).
        ela_sweep: list of {"quality": int, "b64": str} dicts.
                   Each b64 is a base64-encoded PNG ELA image.
                   Only rendered when task == "forgery".
        """
        page_w, page_h = A4
        margin   = 0.7 * inch
        usable_w = page_w - 2 * margin

        _buf  = io.BytesIO()
        c     = canvas.Canvas(_buf, pagesize=A4)
        title = "Forgery Detection Report" if task == "forgery" else "AI Classification Report"

        # ── Canvas helpers ────────────────────────────────────────────────

        def draw_header():
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(margin, page_h - margin + 0.15 * inch,
                         "Image Authenticity Lab")
            c.setFont("Helvetica", 10)
            c.setFillColor(colors.HexColor("#666666"))
            c.drawRightString(
                page_w - margin,
                page_h - margin + 0.18 * inch,
                datetime.datetime.now().strftime("%Y-%m-%d  %H:%M"),
            )
            c.setFillColor(colors.black)
            c.setLineWidth(0.75)
            c.setStrokeColor(colors.HexColor("#cccccc"))
            c.line(margin, page_h - margin, page_w - margin, page_h - margin)
            c.setFont("Helvetica-Bold", 18)
            c.setFillColor(colors.black)
            c.drawString(margin, page_h - margin - 0.35 * inch, title)

        def draw_kv(y: float, key: str, value: str):
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.black)
            c.drawString(margin, y, key)
            c.setFont("Helvetica", 11)
            c.drawString(margin + 1.7 * inch, y, value)

        def draw_section_label(y: float, text: str):
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(colors.black)
            c.drawString(margin, y, text)

        def draw_wrapped(y: float, text: str, chars: int = 95) -> float:
            c.setFont("Helvetica", 11)
            c.setFillColor(colors.black)
            obj = c.beginText(margin, y)
            obj.setLeading(15)
            for line in ReportService.wrap_text(text, chars):
                obj.textLine(line)
            c.drawText(obj)
            return obj.getY()

        def maybe_new_page(y: float, needed: float) -> float:
            if y - needed < margin:
                c.showPage()
                draw_header()
                return page_h - margin - 0.75 * inch
            return y

        def embed_file_image(img_path: Path, y: float, max_h: float) -> float:
            """Embed a compressed on-disk image; return y below it."""
            tmp = ReportService._compressed_jpeg(img_path)
            try:
                with Image.open(tmp) as im:
                    iw, ih = im.size
                scale = min(usable_w / iw, max_h / ih)
                dw, dh = iw * scale, ih * scale
                c.drawImage(tmp, margin, y - dh,
                            width=dw, height=dh,
                            preserveAspectRatio=True, mask="auto")
                return y - dh
            finally:
                Path(tmp).unlink(missing_ok=True)

        def embed_b64_cell(b64_str: str, cell_x: float, cell_top: float,
                           cell_w: float, cell_h: float):
            """
            Decode a base64 PNG, compress to JPEG, and draw it centred
            inside the given cell rectangle (origin = top-left).
            """
            raw   = base64.b64decode(b64_str)
            pil   = Image.open(io.BytesIO(raw)).convert("RGB")
            pw, ph = pil.size
            sc    = min(1.0, ReportService.MAX_SIDE_PX / max(pw, ph))
            if sc < 1.0:
                pil = pil.resize(
                    (max(1, int(pw * sc)), max(1, int(ph * sc))),
                    Image.LANCZOS,
                )
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp_path = tmp.name
            tmp.close()
            pil.save(tmp_path, "JPEG",
                     quality=ReportService.JPEG_QUALITY,
                     optimize=True, progressive=True)
            pil.close()

            try:
                with Image.open(tmp_path) as im:
                    iw, ih = im.size
                img_scale = min(cell_w / iw, cell_h / ih)
                dw, dh    = iw * img_scale, ih * img_scale
                ox = cell_x + (cell_w - dw) / 2
                oy = cell_top - cell_h + (cell_h - dh) / 2
                c.drawImage(tmp_path, ox, oy,
                            width=dw, height=dh,
                            preserveAspectRatio=True, mask="auto")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        # ── Page 1 ────────────────────────────────────────────────────────
        draw_header()
        y = page_h - margin - 0.75 * inch

        # Summary
        draw_kv(y, "Task:",
                "Forgery Detection" if task == "forgery" else "AI Classification")
        y -= 0.28 * inch
        draw_kv(y, "Result:", label or "—")
        y -= 0.28 * inch
        draw_kv(y, "Confidence:", f"{confidence_percent:.2f}%")
        y -= 0.35 * inch

        c.setLineWidth(0.75)
        c.setStrokeColor(colors.HexColor("#cccccc"))
        c.line(margin, y, page_w - margin, y)
        y -= 0.28 * inch

        # Captions
        draw_section_label(y, "Caption (Image)")
        y -= 0.22 * inch
        y = draw_wrapped(y, caption_image) - 0.22 * inch

        draw_section_label(y, "Caption (Output)")
        y -= 0.22 * inch
        y = draw_wrapped(y, caption_output) - 0.32 * inch

        # Input image
        img_h = 3.0 * inch if task == "ai" else 2.5 * inch
        y = maybe_new_page(y, img_h + 0.4 * inch)
        draw_section_label(y, "Input Image")
        y -= 0.22 * inch
        y = embed_file_image(input_image_path, y, img_h) - 0.25 * inch

        # Heatmap (forgery only)
        if task == "forgery" and heatmap_image_path is not None:
            y = maybe_new_page(y, img_h + 0.4 * inch)
            draw_section_label(y, "Forgery Heatmap (ELA Overlay)")
            y -= 0.22 * inch
            y = embed_file_image(heatmap_image_path, y, img_h) - 0.18 * inch
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor("#888888"))
            c.drawString(
                margin, y,
                "Note: Warmer colours indicate higher ELA residual energy — possible manipulation.",
            )
            c.setFillColor(colors.black)

        # ── Page 2 — ELA Quality Sweep ────────────────────────────────────
        if task == "forgery" and ela_sweep:
            c.showPage()
            draw_header()
            y = page_h - margin - 0.75 * inch

            draw_section_label(y, "ELA Quality Sweep")
            y -= 0.22 * inch

            # Intro paragraph
            c.setFont("Helvetica", 11)
            c.setFillColor(colors.HexColor("#444444"))
            intro = (
                "The image is re-saved at six JPEG quality levels and differenced against "
                "the original. Tampered regions retain elevated residual energy across all "
                "qualities; authentic regions fade as quality decreases. Brightness is "
                "scaled so the maximum difference maps to 255 — matching training preprocessing."
            )
            obj = c.beginText(margin, y)
            obj.setLeading(15)
            for line in ReportService.wrap_text(intro, 95):
                obj.textLine(line)
            c.drawText(obj)
            y = obj.getY() - 0.32 * inch
            c.setFillColor(colors.black)

            # Grid geometry
            cols   = 3
            gap    = 0.14 * inch
            cell_w = (usable_w - gap * (cols - 1)) / cols
            cell_h = cell_w * 0.78        # ~4:3
            lbl_h  = 0.22 * inch          # height below each cell for quality label
            row_h  = cell_h + lbl_h + gap

            row_y = y  # top of current row

            for i, item in enumerate(ela_sweep):
                col = i % cols

                # Move down one full row at the start of each new row (after first)
                if col == 0 and i > 0:
                    row_y -= row_h
                    row_y = maybe_new_page(row_y, row_h)

                cell_x = margin + col * (cell_w + gap)

                # Grey cell background
                c.setFillColor(colors.HexColor("#f2f2f2"))
                c.setStrokeColor(colors.HexColor("#cccccc"))
                c.setLineWidth(0.5)
                c.roundRect(cell_x, row_y - cell_h,
                            cell_w, cell_h, 4, stroke=1, fill=1)
                c.setFillColor(colors.black)

                # ELA image inside cell
                try:
                    embed_b64_cell(item["b64"], cell_x, row_y, cell_w, cell_h)
                except Exception:
                    pass  # skip silently if one entry is malformed

                # Quality label centred below cell
                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(colors.HexColor("#333333"))
                c.drawCentredString(
                    cell_x + cell_w / 2,
                    row_y - cell_h - lbl_h + 0.05 * inch,
                    f"q = {item.get('quality', '?')}",
                )
                c.setFillColor(colors.black)

            # Footer note
            footer_y = row_y - row_h - 0.08 * inch
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor("#888888"))
            c.drawString(
                margin, footer_y,
                "Model input: ELA at q=90, resized to 128×128, normalised ÷255  |  "
                "Architecture: DenseNet121  |  Training dataset: CASIA 2.0",
            )

        c.showPage()
        c.save()
        _buf.seek(0)
        return _buf.read()

    # ── Static helpers ────────────────────────────────────────────────────

    @staticmethod
    def wrap_text(text: str, width: int) -> list[str]:
        text = (text or "").strip()
        if not text:
            return ["—"]
        return textwrap.wrap(text, width=width)

    @staticmethod
    def _compressed_jpeg(img_path: Path) -> str:
        """
        Downscale + JPEG-compress an on-disk image for PDF embedding.
        Returns a temp-file path — caller must delete.
        """
        im = Image.open(img_path)
        try:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode != "RGB":
            im = im.convert("RGB")
        w, h  = im.size
        scale = min(1.0, ReportService.MAX_SIDE_PX / max(w, h))
        if scale < 1.0:
            im = im.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.LANCZOS,
            )
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp_path = tmp.name
        tmp.close()
        im.save(tmp_path, "JPEG",
                quality=ReportService.JPEG_QUALITY,
                optimize=True, progressive=True)
        im.close()
        return tmp_path
