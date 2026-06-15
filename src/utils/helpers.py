import re
import pandas as pd
from PIL import Image

def parse_indian_currency(value_str):
    if pd.isna(value_str):
        return value_str
        
    orig_str = str(value_str)
    cleaned = re.sub(r'[^\d\.,\s-]', '', orig_str).strip()
    
    if not cleaned:
        return value_str
        
    if not any(c.isdigit() for c in cleaned):
        return value_str

    is_negative = '-' in cleaned
    cleaned = cleaned.replace('-', '')
    
    match = re.search(r'^(.*)([\.,\s])(\d{2})$', cleaned)
    
    try:
        if match:
            int_part = match.group(1)
            dec_part = match.group(3)
            int_part = re.sub(r'[\.,\s]', '', int_part)
            if not int_part:
                int_part = '0'
            val = float(f"{int_part}.{dec_part}")
            return -val if is_negative else val
        else:
            if '.' in cleaned:
                parts = cleaned.rsplit('.', 1)
                int_part = re.sub(r'[\.,\s]', '', parts[0])
                dec_part = re.sub(r'[\.,\s]', '', parts[1])
                if not int_part:
                    int_part = '0'
                val = float(f"{int_part}.{dec_part}")
                return -val if is_negative else val
            else:
                clean_num = re.sub(r'[\.,\s]', '', cleaned)
                val = float(clean_num)
                return -val if is_negative else val
    except ValueError:
        return value_str

def validate_row_math(df: pd.DataFrame) -> pd.DataFrame:
    statuses = []
    notes = []
    
    for idx, row in df.iterrows():
        skip_cols = {"Page_Num", "Y_Coord", "Validation_Status", "Validation_Notes", "Completeness_Status"}
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
        
        if len(numeric_vals) >= 3:
            value = numeric_vals[-1]
            qty_or_rate1 = numeric_vals[-2]
            qty_or_rate2 = numeric_vals[-3]
            
            expected_value = round(qty_or_rate1 * qty_or_rate2, 4)
            
            if expected_value == 0:
                is_match = abs(value) < 0.01
            else:
                diff_ratio = abs(value - expected_value) / abs(expected_value)
                is_match = diff_ratio <= 0.02
                
            if is_match:
                statuses.append("PASS")
                notes.append("")
            else:
                statuses.append("FAIL")
                notes.append(f"Math mismatch: {qty_or_rate2} * {qty_or_rate1} != {value}")
        else:
            statuses.append("FAIL")
            notes.append("Insufficient numeric columns for validation")
            
    df = df.copy()
    df["Validation_Status"] = statuses
    df["Validation_Notes"] = notes
    
    return df

def validate_text_layer(text: str) -> bool:
    if not text.strip():
        return False
        
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return True 
        
    spell = SpellChecker()
    tokens = re.findall(r'\b[A-Za-z]{3,}\b', text)
    
    if not tokens:
        return True
        
    mean_len = sum(len(t) for t in tokens) / len(tokens)
    if mean_len < 3 or mean_len > 12:
        return False
        
    known_words = spell.known(tokens)
    hit_rate = len(known_words) / len(tokens)
    
    return hit_rate > 0.70

def extract_qr_payload(pil_image: Image.Image) -> list[str]:
    try:
        from pyzbar.pyzbar import decode
    except ImportError:
        return []
        
    decoded_objects = decode(pil_image)
    payloads = []
    for obj in decoded_objects:
        try:
            payloads.append(obj.data.decode("utf-8"))
        except Exception:
            pass
    return payloads

def validate_critical_entities(text: str, confidence: float) -> list[dict]:
    exceptions = []
    if confidence >= 85.0:
        return exceptions
        
    pan_pattern = r'\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b'
    date_pattern = r'\b\d{2}[-/]\d{2}[-/]\d{4}\b'
    gstin_pattern = r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b'
    
    found_entities = []
    if re.search(pan_pattern, text):
        found_entities.append("PAN Card")
    if re.search(date_pattern, text):
        found_entities.append("Date")
    if re.search(gstin_pattern, text):
        found_entities.append("GSTIN")
        
    for entity in found_entities:
        exceptions.append({
            "table": "ENTITY_SCAN",
            "row": "ALL",
            "note": f"Low confidence (< 85.0%) on critical entity type: {entity}",
            "data": {}
        })
        
    return exceptions

def filter_devanagari_noise(text_str: str) -> str:
    return re.sub(r'(?<![\u0900-\u097F])[\u0900-\u097F]{1,2}(?![\u0900-\u097F])', '', text_str)

def extract_grand_total(text: str) -> float | None:
    if not text:
        return None

    pattern = r"(?i)\b(?:Grand\s+Total|Total\s+Amount|Net\s+Amount|Amount\s+Due|Total\s*:?)\s*[:=\-]?\s*([₹\$Rs\.]*\s*[\d,]+\.\d{2})\b"
    keyword_matches = re.findall(pattern, text)
    
    for match in keyword_matches:
        parsed = parse_indian_currency(match)
        if isinstance(parsed, float) and parsed > 0:
            return parsed

    lines = text.split('\n')
    bottom_30_idx = int(len(lines) * 0.70)
    bottom_text = "\n".join(lines[bottom_30_idx:])
    
    candidates = re.findall(r'\b[\d,]+\.\d{2}\b', bottom_text)
    parsed_candidates = []
    
    for c in candidates:
        result = parse_indian_currency(c)
        if isinstance(result, float) and result > 0:
            parsed_candidates.append(result)
            
    if parsed_candidates:
        return max(parsed_candidates)
        
    return None

def _extract_value_by_keyword(text: str, keywords: list[str]) -> float | None:
    if not text:
        return None
        
    kw_pattern = "|".join([re.escape(k) for k in keywords])
    pattern = rf"(?i)\b(?:{kw_pattern})\s*[:=\-]?\s*([₹\$Rs\.]*\s*[\d,]+\.\d{{2}})\b"
    matches = re.findall(pattern, text)
    
    parsed_vals = []
    for match in matches:
        parsed = parse_indian_currency(match)
        if isinstance(parsed, float) and parsed > 0:
            parsed_vals.append(parsed)
            
    return max(parsed_vals) if parsed_vals else None

def _validate_running_totals(dfs: list[pd.DataFrame]) -> list[dict]:
    exceptions = []
    
    for table_idx, df in enumerate(dfs, start=1):
        cum_sum = 0.0
        
        skip_cols = {"Page_Num", "Y_Coord", "Validation_Status", "Validation_Notes", "Completeness_Status"}
        data_cols = [c for c in df.columns if c not in skip_cols]
        if not data_cols:
            continue
            
        for row_idx, row in df.iterrows():
            row_str = " ".join(str(val).upper() for val in row[data_cols] if pd.notna(val))
            is_cf_row = any(kw in row_str for kw in ["CARRIED FORWARD", "B/F", "C/F", "SUB-TOTAL"])
            
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
                if abs(cum_sum - cf_value) > 2.0:
                    exceptions.append({
                        "table": table_idx,
                        "row": row_idx + 1,
                        "note": f"Running-Total Drift: Expected {cum_sum:.2f}, got {cf_value:.2f}",
                        "data": {}
                    })
                cum_sum = cf_value
            elif numeric_vals:
                cum_sum += numeric_vals[-1]
                
    return exceptions

def detect_table_from_text(text: str) -> bool:
    indicators = 0
    for line in text.split("\n"):
        nums = re.findall(r"\b\d+(?:[.,]\d+)?\b", line)
        if len(nums) >= 2:
            indicators += 1
        elif re.search(r" {4,}", line):
            indicators += 1
        elif "|" in line:
            indicators += 1
    return indicators >= 3

import pytesseract
def _triage_and_rotate(pil_image: Image.Image) -> tuple[Image.Image, dict]:
    osd_data = {}
    try:
        osd_dict = pytesseract.image_to_osd(pil_image, output_type=pytesseract.Output.DICT)
        osd_data = osd_dict
        angle = osd_dict.get('rotate', 0)
        if angle != 0:
            pil_image = pil_image.rotate(-angle, expand=True)
    except Exception:
        pass
        
    return pil_image, osd_data

import logging
import os
from datetime import datetime

def create_exception_logger(output_folder: str) -> logging.Logger:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"OCR_ExceptionLog_{timestamp}.txt"
    log_path = os.path.join(output_folder, log_name)

    logger = logging.getLogger("ocr_exception")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s  [%(levelname)s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(fh)
    return logger
