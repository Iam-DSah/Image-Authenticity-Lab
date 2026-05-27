# services/metadata_service.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


class MetadataExtractor:
    """Extracts file and EXIF metadata from uploaded images."""

    @staticmethod
    def extract(image_path: str) -> Dict[str, Any]:
        path = Path(image_path)
        meta: Dict[str, Any] = {}

        # File-level info
        meta["file_name"] = path.name
        try:
            size_bytes = path.stat().st_size
            if size_bytes >= 1_048_576:
                meta["file_size"] = f"{size_bytes / 1_048_576:.2f} MB"
            else:
                meta["file_size"] = f"{size_bytes / 1024:.1f} KB"
        except Exception:
            meta["file_size"] = "Unknown"

        try:
            img = Image.open(image_path)
            meta["format"] = img.format or path.suffix.lstrip(".").upper()
            meta["mode"] = img.mode
            w, h = img.size
            meta["resolution"] = f"{w} × {h} px"

            # EXIF extraction
            exif_data = MetadataExtractor._get_exif(img)
            meta.update(exif_data)
            img.close()
        except Exception as e:
            meta["format"] = path.suffix.lstrip(".").upper() or "Unknown"
            meta["resolution"] = "Unknown"
            meta["exif_error"] = str(e)

        return meta

    @staticmethod
    def _get_exif(img: Image.Image) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            raw_exif = img._getexif()  # type: ignore[attr-defined]
            if not raw_exif:
                return result
        except Exception:
            return result

        tag_map = {
            "Make": "camera_make",
            "Model": "camera_model",
            "Software": "software",
            "DateTime": "capture_date",
            "DateTimeOriginal": "capture_date",
            "ExifImageWidth": "exif_width",
            "ExifImageHeight": "exif_height",
            "Flash": "flash",
            "FocalLength": "focal_length",
            "ISOSpeedRatings": "iso",
            "ExposureTime": "exposure_time",
            "FNumber": "f_number",
            "GPSInfo": "__gps__",
        }

        for tag_id, value in raw_exif.items():
            tag_name = TAGS.get(tag_id, "")
            key = tag_map.get(tag_name)
            if key is None:
                continue
            if key == "__gps__":
                gps = MetadataExtractor._parse_gps(value)
                if gps:
                    result["gps_coordinates"] = gps
                continue
            # Format rationals nicely
            try:
                from fractions import Fraction
                if hasattr(value, "numerator"):
                    value = float(Fraction(value))
            except Exception:
                pass
            if isinstance(value, tuple) and len(value) == 2:
                try:
                    value = f"{value[0] / value[1]:.4f}".rstrip("0").rstrip(".")
                except Exception:
                    pass
            if key in result:
                continue  # prefer first occurrence (DateTimeOriginal over DateTime)
            result[key] = str(value).strip()

        return result

    @staticmethod
    def _parse_gps(gps_info: dict) -> Optional[str]:
        try:
            def to_deg(val):
                d, m, s = val
                try:
                    d = float(d.numerator) / float(d.denominator)
                    m = float(m.numerator) / float(m.denominator)
                    s = float(s.numerator) / float(s.denominator)
                except Exception:
                    d, m, s = float(d), float(m), float(s)
                return d + m / 60.0 + s / 3600.0

            gps_tags = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            lat = to_deg(gps_tags["GPSLatitude"])
            lon = to_deg(gps_tags["GPSLongitude"])
            if gps_tags.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_tags.get("GPSLongitudeRef") == "W":
                lon = -lon
            return f"{lat:.6f}, {lon:.6f}"
        except Exception:
            return None
