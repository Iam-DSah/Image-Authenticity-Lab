# Image Authenticity Lab

A Flask-based web application for detecting image forgery and AI-generated images, with metadata analysis, heatmap visualization, and PDF report export.

## Features

- **Forgery Detection** — ELA + CNN (Keras) with JET-colourmap heatmap overlay & comparison slider
- **AI Classification** — Vision Transformer (ViT-Base/16, PyTorch) for AI vs Real detection
- **Image Captioning** — BLIP model generates natural language descriptions
- **Metadata Extraction** — EXIF data (camera, GPS, capture date, etc.)
- **History Panel** — Last 10 analyses stored in browser localStorage
- **PDF Reports** — ReportLab-generated ~1–2 MB reports with images and results
- **Model Info Panel** — Architecture overview for all ML models

---

## Project Structure

```
image_authenticity_lab/
├── app.py                        # Flask application entry point
├── requirements.txt
├── README.md
├── .gitignore
│
├── services/                     # ML & utility service modules
│   ├── __init__.py
│   ├── tamper_service.py         # ELA + CNN forgery detection + heatmap
│   ├── ai_service.py             # ViT AI-generated image classifier
│   ├── caption_service.py        # BLIP image captioning
│   ├── metadata_service.py       # EXIF metadata extraction
│   └── report_service.py         # PDF report generation (ReportLab)
│
├── models/                       # Place trained model weights here
│   ├── ELA_Model.keras           # Forgery CNN (TensorFlow/Keras)
│   └── best_vit_model.pth        # AI classifier (PyTorch ViT)
│
├── templates/
│   └── index.html                # Main UI (Jinja2 template)
│
├── static/
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── main.js
│   ├── img/
│   │   └── logo.svg
│   └── uploads/                  # Saved uploaded images (runtime)
│
└── outputs/
    ├── heatmaps/                 # Generated heatmap PNGs (runtime)
    └── reports/                  # Generated PDF reports (runtime)
```

---

## Setup

### 1. Place model weights

Copy your trained model files into the `models/` directory:

```
models/model_casia_run1.h5
models/best_vit_model.pth
```

### 2. Create virtual environment & install dependencies

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

Then open: **http://127.0.0.1:5000**

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main web UI |
| POST | `/api/forgery-detect` | Run forgery detection on uploaded image |
| POST | `/api/ai-classify` | Run AI vs Real classification |
| POST | `/api/report` | Generate and download PDF report |
| GET | `/outputs/heatmaps/<file>` | Serve generated heatmap images |

### Request format (forgery-detect & ai-classify)
`multipart/form-data` with field `image` (JPG or PNG, max 15 MB)

### Response format
```json
{
  "ok": true,
  "task": "forgery",
  "label": "TAMPERED IMAGE",
  "confidence": 0.934,
  "confidence_percent": 93.40,
  "heatmap_url": "/outputs/heatmaps/abc123.png",
  "caption_image": "a street scene with cars",
  "caption_output": "The system predicts this image is tampered (93.4% confidence).",
  "metadata": {
    "file_name": "photo.jpg",
    "file_size": "1.2 MB",
    "resolution": "3024 × 4032 px",
    "camera_model": "iPhone 14 Pro",
    "capture_date": "2024:03:15 14:22:01"
  },
  "uploaded_image_url": "/static/uploads/abc123.jpg"
}
```

---

## Heatmap Notes

The heatmap uses **Error Level Analysis (ELA)** — a technique that amplifies JPEG compression inconsistencies left behind by image editing. The ELA signal is converted to a JET colourmap overlay on the original image:

- **Blue / cool areas** — consistent compression → likely authentic
- **Red / warm areas** — inconsistent compression → possible manipulation

> This is a best-effort localization. True pixel-level segmentation requires a dedicated segmentation model.

---

## Class Mapping

**Forgery model** (`model_casia_run1.h5`):
- `pred[0]` → TAMPERED confidence
- `pred[1]` → REAL confidence

**AI classifier** (`best_vit_model.pth`):
- Index `0` → AI GENERATED
- Index `1` → REAL

If your training used a different mapping, edit the relevant service file.
