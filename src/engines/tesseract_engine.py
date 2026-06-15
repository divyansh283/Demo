import os
from pathlib import Path
import pytesseract
from PIL import Image
from src.utils.helpers import filter_devanagari_noise

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TESSERACT_CANDIDATES = [
    os.environ.get("TESSERACT_CMD"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

_TESSDATA_CANDIDATES = [
    os.environ.get("TESSDATA_PREFIX"),
    _PROJECT_ROOT / "tessdata",
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
]

for candidate in _TESSERACT_CANDIDATES:
    if candidate and Path(candidate).exists():
        pytesseract.pytesseract.tesseract_cmd = candidate
        break


def _resolve_tessdata_dir() -> Path:
    for candidate in _TESSDATA_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir() and (path / "eng.traineddata").exists():
            return path

    checked = "\n".join(f" - {Path(c)}" for c in _TESSDATA_CANDIDATES if c)
    raise FileNotFoundError(
        "Tesseract language data was not found. The folder must contain "
        f"eng.traineddata.\nChecked:\n{checked}"
    )


def run_tesseract(pil_image: Image.Image, lang: str) -> tuple[str, float]:
    tessdata_dir = _resolve_tessdata_dir()
    tess_config = f'--tessdata-dir "{tessdata_dir}"'
    
    data = pytesseract.image_to_data(
        pil_image, lang=lang, config=tess_config, output_type=pytesseract.Output.DICT
    )

    valid_confs = [
        int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0
    ]
    avg_conf = (sum(valid_confs) / len(valid_confs)) if valid_confs else 0.0

    text = pytesseract.image_to_string(pil_image, lang=lang, config=tess_config)
    text = filter_devanagari_noise(text)
    return text.strip(), round(avg_conf, 2)
