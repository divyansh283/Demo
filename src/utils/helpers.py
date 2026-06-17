import logging
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from PIL import Image


CRITICAL_ENTITY_PATTERNS = {
    "PAN": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "Date": r"\b(?:[0-3]?\d[-/][01]?\d[-/](?:19|20)\d{2}|(?:19|20)\d{2}[-/][01]?\d[-/][0-3]?\d)\b",
    "GSTIN": r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b",
    "Vehicle Number": r"\b[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{3,4}\b",
    "Policy/CAF/Invoice Number": r"\b(?:POLICY|CAF|INVOICE|BILL)\s*(?:NO\.?|NUMBER|#)?\s*[:\-]\s*[A-Z0-9/-]{4,}\b",
    "PO Number": r"\bPO\s*(?:NO\.?|NUMBER|#)?\s*[:\-]\s*[A-Z0-9/-]{4,}\b",
    "Amount": r"(?:Rs\.?|INR|\u20b9)\s*(?=[\d,]*\d)[\d,]+(?:\.\d{2})?",
}

COMMON_ENGLISH_WORDS = {
    "the", "and", "for", "from", "with", "this", "that", "have", "has",
    "was", "were", "will", "shall", "total", "amount", "date", "name",
    "address", "page", "invoice", "balance", "sheet", "assets",
    "liabilities", "statement", "police", "panchnama", "enclosure",
    "company", "limited", "report", "stock", "quantity", "rate", "value",
    "description", "account", "number",
}


def parse_indian_currency(value_str):
    if pd.isna(value_str):
        return value_str

    cleaned = re.sub(r"[^\d\.,\s-]", "", str(value_str)).strip()
    if not cleaned or not any(c.isdigit() for c in cleaned):
        return value_str

    is_negative = "-" in cleaned
    cleaned = cleaned.replace("-", "")
    match = re.search(r"^(.*)([\.,\s])(\d{2})$", cleaned)

    try:
        if match:
            int_part = re.sub(r"[\.,\s]", "", match.group(1)) or "0"
            val = float(f"{int_part}.{match.group(3)}")
        elif "." in cleaned:
            int_part, dec_part = cleaned.rsplit(".", 1)
            int_part = re.sub(r"[\.,\s]", "", int_part) or "0"
            dec_part = re.sub(r"[\.,\s]", "", dec_part)
            val = float(f"{int_part}.{dec_part}")
        else:
            val = float(re.sub(r"[\.,\s]", "", cleaned))
        return -val if is_negative else val
    except ValueError:
        return value_str


def validate_row_math(df: pd.DataFrame) -> pd.DataFrame:
    statuses = []
    notes = []

    for _, row in df.iterrows():
        skip_cols = {
            "Page_Num",
            "Y_Coord",
            "Validation_Status",
            "Validation_Notes",
            "Completeness_Status",
        }
        data_row = row.drop(labels=[c for c in skip_cols if c in row.index])

        numeric_vals = []
        for val in data_row:
            if isinstance(val, float) and not pd.isna(val):
                numeric_vals.append(val)
            elif isinstance(val, str) and val.startswith("<low_conf>") and val.endswith("</low_conf>"):
                try:
                    numeric_vals.append(float(val.replace("<low_conf>", "").replace("</low_conf>", "")))
                except ValueError:
                    pass

        if len(numeric_vals) < 3:
            statuses.append("PASS")
            notes.append("Arithmetic validation skipped; fewer than 3 numeric values")
            continue

        value = numeric_vals[-1]
        qty_or_rate1 = numeric_vals[-2]
        qty_or_rate2 = numeric_vals[-3]
        expected_value = round(qty_or_rate1 * qty_or_rate2, 4)
        tolerance = max(10.0, abs(expected_value) * 0.02)

        if abs(value - expected_value) <= tolerance:
            statuses.append("PASS")
            notes.append("")
        else:
            statuses.append("FAIL")
            notes.append(f"Math mismatch: {qty_or_rate2} * {qty_or_rate1} != {value}")

    df = df.copy()
    df["Validation_Status"] = statuses
    df["Validation_Notes"] = notes
    return df


def _text_layer_metrics(text: str) -> dict:
    stripped = text.strip()
    chars = len(stripped)
    token_pattern = r"[\w\u0900-\u097F\u0A80-\u0AFF]{3,}"
    alpha_pattern = r"[A-Za-z\u0900-\u097F\u0A80-\u0AFF]"
    tokens = re.findall(token_pattern, stripped, flags=re.UNICODE)
    alpha_tokens = [t for t in tokens if re.search(alpha_pattern, t)]
    english_tokens = [t.lower() for t in tokens if re.fullmatch(r"[A-Za-z]{3,}", t)]
    indic_tokens = [t for t in tokens if re.search(r"[\u0900-\u097F\u0A80-\u0AFF]", t)]
    printable = sum(1 for c in stripped if c.isprintable())
    sane_chars = sum(
        1
        for c in stripped
        if c.isalnum() or c.isspace() or c in ".,;:()[]{}+-/%&'\"#\u20b9"
    )

    mean_token_len = (sum(len(t) for t in alpha_tokens) / len(alpha_tokens)) if alpha_tokens else 0.0
    common_hits = sum(1 for t in english_tokens if t in COMMON_ENGLISH_WORDS)

    return {
        "chars": chars,
        "token_count": len(tokens),
        "alpha_token_count": len(alpha_tokens),
        "english_token_count": len(english_tokens),
        "indic_token_count": len(indic_tokens),
        "mean_token_len": mean_token_len,
        "printable_ratio": printable / chars if chars else 0.0,
        "sane_char_ratio": sane_chars / chars if chars else 0.0,
        "english_hit_rate": common_hits / len(english_tokens) if english_tokens else None,
    }


def validate_text_layer(text: str, ocr_sample_text: str | None = None) -> bool:
    """Reject scanner garbage text layers before the PDF handler trusts them."""
    metrics = _text_layer_metrics(text)
    if metrics["chars"] < 20:
        return False
    if metrics["printable_ratio"] < 0.98 or metrics["sane_char_ratio"] < 0.78:
        return False
    if metrics["alpha_token_count"] < 4:
        return False
    if not 3 <= metrics["mean_token_len"] <= 16:
        return False

    has_indic = metrics["indic_token_count"] >= 4
    if not has_indic and metrics["english_token_count"] >= 8:
        hit_rate = metrics["english_hit_rate"]
        if hit_rate is not None and hit_rate < 0.08:
            return False

    if ocr_sample_text:
        left = re.sub(r"\s+", " ", text[:2500]).lower()
        right = re.sub(r"\s+", " ", ocr_sample_text[:2500]).lower()
        if len(right) >= 40 and SequenceMatcher(None, left, right).ratio() < 0.18:
            return False

    return True


def text_layer_diagnostics(text: str) -> dict:
    metrics = _text_layer_metrics(text)
    metrics["trusted_without_crosscheck"] = validate_text_layer(text)
    return metrics


def extract_qr_payload(pil_image: Image.Image) -> list[str]:
    try:
        from pyzbar.pyzbar import decode
    except (ImportError, OSError, Exception):
        return []

    payloads = []
    for obj in decode(pil_image):
        try:
            payloads.append(obj.data.decode("utf-8"))
        except Exception:
            pass
    return payloads


def validate_critical_entities(text: str, confidence: float) -> list[dict]:
    exceptions = []
    if confidence >= 85.0:
        return exceptions

    for entity, pattern in CRITICAL_ENTITY_PATTERNS.items():
        matches = re.findall(pattern, text or "", flags=re.IGNORECASE)
        if matches:
            exceptions.append(
                {
                    "table": "ENTITY_SCAN",
                    "row": "ALL",
                    "note": f"Low confidence ({confidence:.2f}%) on critical entity type: {entity}",
                    "data": {"matches": [str(m) for m in matches[:10]]},
                }
            )

    generic_terms = {
        "First Party",
        "Second Party",
        "Company Pvt",
        "Private Limited",
        "Police Station",
        "Post Office",
    }
    for name in re.findall(r"\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b", text or "")[:20]:
        if name in generic_terms:
            continue
        vowels = sum(1 for c in name.lower() if c in "aeiou")
        letters = sum(1 for c in name.lower() if c.isalpha())
        if letters >= 10 and vowels / max(letters, 1) < 0.22:
            exceptions.append(
                {
                    "table": "ENTITY_SCAN",
                    "row": "ALL",
                    "note": f"Possibly garbled legal name/address token: {name}",
                    "data": {"value": name},
                }
            )
    return exceptions


def filter_devanagari_noise(text_str: str) -> str:
    return re.sub(r"(?<![\u0900-\u097F])[\u0900-\u097F]{1,2}(?![\u0900-\u097F])", "", text_str)


def extract_grand_total(text: str) -> float | None:
    if not text:
        return None

    pattern = r"(?i)\b(?:Grand\s+Total|Total\s+Amount|Net\s+Amount|Amount\s+Due|Total\s*:?)\s*[:=\-]?\s*((?:\u20b9|\$|Rs\.?)?\s*[\d,]+(?:\.\d{2})?)\b"
    for match in re.findall(pattern, text):
        parsed = parse_indian_currency(match)
        if isinstance(parsed, float) and parsed > 0:
            return parsed

    lines = text.split("\n")
    bottom_text = "\n".join(lines[int(len(lines) * 0.70):])
    parsed_candidates = []
    for candidate in re.findall(r"\b[\d,]+\.\d{2}\b", bottom_text):
        result = parse_indian_currency(candidate)
        if isinstance(result, float) and result > 0:
            parsed_candidates.append(result)

    return max(parsed_candidates) if parsed_candidates else None


def _extract_value_by_keyword(text: str, keywords: list[str]) -> float | None:
    if not text:
        return None

    kw_pattern = "|".join(re.escape(k) for k in keywords)
    pattern = rf"(?i)\b(?:{kw_pattern})\s*[:=\-]?\s*((?:\u20b9|\$|Rs\.?)?\s*[\d,]+(?:\.\d{{2}})?)\b"
    parsed_vals = []
    for match in re.findall(pattern, text):
        parsed = parse_indian_currency(match)
        if isinstance(parsed, float) and parsed > 0:
            parsed_vals.append(parsed)

    return max(parsed_vals) if parsed_vals else None


def _validate_running_totals(dfs: list[pd.DataFrame]) -> list[dict]:
    exceptions = []

    for table_idx, df in enumerate(dfs, start=1):
        cum_sum = 0.0
        skip_cols = {
            "Page_Num",
            "Y_Coord",
            "Validation_Status",
            "Validation_Notes",
            "Completeness_Status",
        }
        data_cols = [c for c in df.columns if c not in skip_cols]
        if not data_cols:
            continue

        for row_idx, row in df.iterrows():
            row_str = " ".join(str(val).upper() for val in row[data_cols] if pd.notna(val))
            is_cf_row = any(
                kw in row_str
                for kw in ["CARRIED FORWARD", "BROUGHT FORWARD", "B/F", "C/F", "SUB-TOTAL", "SUB TOTAL"]
            )

            numeric_vals = []
            for val in row[data_cols]:
                if isinstance(val, float) and not pd.isna(val):
                    numeric_vals.append(val)
                elif isinstance(val, str) and val.startswith("<low_conf>") and val.endswith("</low_conf>"):
                    try:
                        numeric_vals.append(float(val.replace("<low_conf>", "").replace("</low_conf>", "")))
                    except ValueError:
                        pass

            if is_cf_row and numeric_vals:
                cf_value = numeric_vals[-1]
                if abs(cum_sum - cf_value) > max(10.0, abs(cf_value) * 0.02):
                    exceptions.append(
                        {
                            "table": table_idx,
                            "row": row_idx + 1,
                            "note": f"Running-total drift: expected {cum_sum:.2f}, got {cf_value:.2f}",
                            "data": {},
                        }
                    )
                cum_sum = cf_value
            elif numeric_vals:
                cum_sum += numeric_vals[-1]

    return exceptions


def detect_table_from_text(text: str) -> bool:
    indicators = 0
    for line in (text or "").split("\n"):
        nums = re.findall(r"\b\d+(?:[.,]\d+)?\b", line)
        if len(nums) >= 2:
            indicators += 1
        elif re.search(r" {4,}", line):
            indicators += 1
        elif "|" in line:
            indicators += 1
    return indicators >= 3


def classify_page(osd_data: dict, text: str = "", has_table: bool = False) -> dict:
    script = osd_data.get("script", "Unknown") or "Unknown"
    script_conf = float(osd_data.get("script_conf", 0.0) or 0.0)
    orientation_conf = float(osd_data.get("orientation_conf", 0.0) or 0.0)
    text_len = len((text or "").strip())
    likely_handwritten = bool(osd_data) and script_conf < 2.0 and text_len < 40

    if has_table:
        content_class = "table"
    elif likely_handwritten:
        content_class = "handwritten"
    elif text_len:
        content_class = "printed"
    else:
        content_class = "unknown"

    return {
        "script": script,
        "script_confidence": script_conf,
        "orientation_confidence": orientation_conf,
        "content_class": content_class,
        "likely_handwritten": likely_handwritten,
    }


def _triage_and_rotate(pil_image: Image.Image) -> tuple[Image.Image, dict]:
    import pytesseract

    osd_data = {}
    try:
        osd_data = pytesseract.image_to_osd(pil_image, output_type=pytesseract.Output.DICT)
        angle = int(osd_data.get("rotate", 0) or 0)
        if angle:
            pil_image = pil_image.rotate(-angle, expand=True)
    except Exception:
        pass

    return pil_image, osd_data


def build_production_gate_report(exceptions_list: list[dict]) -> dict:
    total_docs = len(exceptions_list)
    unreconciled = sum(1 for item in exceptions_list if item.get("status") != "RECONCILED")
    monetary_failures = sum(
        1
        for item in exceptions_list
        if isinstance(item.get("delta"), (int, float)) and item.get("delta") > 500
    )
    digital_text_layers_used = sum(1 for item in exceptions_list if item.get("digital_text_layer_used"))
    digital_text_layers_rejected = sum(1 for item in exceptions_list if item.get("digital_text_layer_rejected"))

    return {
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "PASS" if total_docs > 0 and unreconciled == 0 and monetary_failures == 0 else "FAIL",
        "documents": total_docs,
        "unreconciled_documents": unreconciled,
        "monetary_deltas_above_500": monetary_failures,
        "digital_text_layers_used": digital_text_layers_used,
        "digital_text_layers_rejected": digital_text_layers_rejected,
        "criteria": [
            "Zero unreconciled monetary delta above 500",
            "Zero garbage text layers accepted",
            "Handwritten pages must be flagged for review",
            "Legal/financial flagged items require human sign-off",
        ],
    }


def create_exception_logger(output_folder: str) -> logging.Logger:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(output_folder, f"OCR_ExceptionLog_{timestamp}.txt")

    logger = logging.getLogger("ocr_exception")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s  [%(levelname)s]  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(fh)
    return logger
