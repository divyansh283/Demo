import os
from pathlib import Path
import pytesseract
from PIL import Image
from src.utils.helpers import filter_devanagari_noise

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_REQUIRED_LANG_FILES = {
    "eng": "eng.traineddata",
    "hin": "hin.traineddata",
    "mar": "mar.traineddata",
    "guj": "guj.traineddata",
    "osd": "osd.traineddata",
}


def _candidate_tesseract_paths() -> list[Path]:
    candidates = [
        os.environ.get("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    return [Path(candidate) for candidate in candidates if candidate]


def _candidate_tessdata_dirs() -> list[Path]:
    candidates: list[Path] = []

    env_tessdata = os.environ.get("TESSDATA_PREFIX")
    if env_tessdata:
        candidates.append(Path(env_tessdata))

    for parent in [_PROJECT_ROOT, *_PROJECT_ROOT.parents]:
        candidates.append(parent / "tessdata")
        candidates.append(parent / "RCB_Utility" / "tessdata")

    candidates.extend(
        [
            Path.cwd() / "tessdata",
            Path.cwd() / "RCB_Utility" / "tessdata",
            Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
        ]
    )

    unique: list[Path] = []
    seen = set()
    for candidate in candidates:
        normalized = str(candidate).lower()
        if normalized not in seen:
            unique.append(candidate)
            seen.add(normalized)
    return unique


for candidate in _candidate_tesseract_paths():
    if candidate.exists():
        pytesseract.pytesseract.tesseract_cmd = str(candidate)
        break


def _resolve_tessdata_dir() -> Path:
    for path in _candidate_tessdata_dirs():
        if path.is_dir() and (path / "eng.traineddata").exists():
            os.environ["TESSDATA_PREFIX"] = str(path)
            return path

    checked = "\n".join(f" - {path}" for path in _candidate_tessdata_dirs())
    raise FileNotFoundError(
        "Tesseract language data was not found. The folder must contain "
        f"eng.traineddata.\nChecked:\n{checked}"
    )


def _validate_requested_languages(tessdata_dir: Path, lang: str) -> None:
    missing = []
    for code in lang.split("+"):
        traineddata = _REQUIRED_LANG_FILES.get(code, f"{code}.traineddata")
        if not (tessdata_dir / traineddata).exists():
            missing.append(traineddata)

    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(
            f"Tesseract language data missing in {tessdata_dir}: {missing_list}"
        )


def run_tesseract(pil_image: Image.Image, lang: str) -> tuple[str, float]:
    tessdata_dir = _resolve_tessdata_dir()
    _validate_requested_languages(tessdata_dir, lang)
    tess_config = f'--tessdata-dir "{str(tessdata_dir)}"'
    
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
