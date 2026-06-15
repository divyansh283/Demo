import configparser
import io
import logging
import os
import queue
import re
import threading
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
from azure.core.credentials import AzureKeyCredential
from PIL import Image

from azure.ai.documentintelligence import DocumentIntelligenceClient
from src.utils.constants import TARGET_DPI, SUPPORTED_FILES
from src.utils.helpers import create_exception_logger, detect_table_from_text, extract_qr_payload, validate_critical_entities
from src.utils.image_processing import prepare_image_for_azure, mask_stamp_ink, remove_grid_lines
from src.engines.tesseract_engine import run_tesseract
from src.engines.azure_engine import run_azure_ocr
from src.utils.helpers import _triage_and_rotate, validate_text_layer
from src.core.reconciliation import reconcile_document

class OCRPipeline:
    """
    Orchestrates the full hybrid OCR pipeline for a list of files.

    Handles batch OCR processing. Orchestrates Tesseract and Azure.
    """

    def __init__(
        self,
        cfg: configparser.ConfigParser,
        log_queue: queue.Queue,
        stop_event: threading.Event,
        balance_sheet: bool = False,
    ):
        self.cfg = cfg
        self.log_queue = log_queue
        self.stop_event = stop_event
        self.balance_sheet = balance_sheet

        # Settings
        self.tess_lang = cfg.get("LANGUAGES", "tesseract_lang", fallback="eng+hin+mar")
        self.risk_thresh = cfg.getfloat(
            "THRESHOLDS", "high_risk_threshold", fallback=60.0
        )
        self.warn_thresh = cfg.getfloat(
            "THRESHOLDS", "azure_fallback_threshold", fallback=93.0
        )

        self._az_client_cache: DocumentIntelligenceClient | None = None

        # State for reporting
        self.current_metrics = []

        # Resolve config values
        self.input_folder = cfg.get("FOLDERS", "input_folder").strip()
        self.output_folder = cfg.get("FOLDERS", "output_folder").strip()
        self.azure_ep = os.environ.get(
            "AZURE_DOCUMENT_ENDPOINT", cfg.get("AZURE", "endpoint", fallback="")
        ).strip()
        self.azure_key = os.environ.get(
            "AZURE_DOCUMENT_KEY", cfg.get("AZURE", "api_key", fallback="")
        ).strip()
        self.warn_thresh = cfg.getint("THRESHOLDS", "warning_threshold", fallback=60)
        self.risk_thresh = cfg.getint("THRESHOLDS", "high_risk_threshold", fallback=30)

        # Ensure output directory exists
        os.makedirs(self.output_folder, exist_ok=True)

        # Exception logger (plain-text file)
        self.exc_log = create_exception_logger(self.output_folder)

        # Lazy Azure client — only instantiated on first cloud call
        self._azure_client: DocumentIntelligenceClient | None = None

        # Accumulates reconciliation data across the whole batch run
        self.exceptions_list: list[dict] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _log(self, level: str, message: str):
        """Push a message to the GUI log queue and the exception log file."""
        self.log_queue.put((level, message))
        if level in ("WARNING", "ERROR"):
            self.exc_log.log(
                logging.WARNING if level == "WARNING" else logging.ERROR, message
            )
        else:
            self.exc_log.info(message)

    def _get_azure_client(self) -> DocumentIntelligenceClient:
        """Lazy-load the Azure client so credentials are validated only when needed."""
        if not self.azure_ep or not self.azure_key:
            raise RuntimeError(
                "Azure credentials are missing. Set AZURE_DOCUMENT_ENDPOINT and "
                "AZURE_DOCUMENT_KEY, or fill the [AZURE] section in config.ini."
            )
        if self._azure_client is None:
            self._azure_client = DocumentIntelligenceClient(
                endpoint=self.azure_ep,
                credential=AzureKeyCredential(self.azure_key),
            )
        return self._azure_client

    def _collect_files(self) -> list[Path]:
        """Return supported files from the input folder and its subfolders."""
        files = []
        input_root = Path(self.input_folder)
        for entry in sorted(input_root.rglob("*")):
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_FILES:
                files.append(entry)
            elif entry.is_file() and entry.suffix.lower() not in SUPPORTED_FILES:
                self._log(
                    "WARNING",
                    f"Unsupported file type skipped: '{entry.name}' "
                    f"(extension '{entry.suffix}'). "
                    "Only PDF, JPG, PNG, and TIFF files are processed.",
                )
        return files

    def _crop_and_retry(
        self,
        pil_image: Image.Image,
        y_min: float,
        y_max: float,
        azure_client: DocumentIntelligenceClient,
        page_num: int
    ) -> list[pd.DataFrame]:
        """
        Crops the image to the specified vertical bounds with a safety padding,
        then resubmits to Azure Document Intelligence.
        """
        padding = 50
        top = max(0, int(y_min) - padding)
        bottom = min(pil_image.height, int(y_max) + padding)
        
        cropped = pil_image.crop((0, top, pil_image.width, bottom))
        
        try:
            img_bytes = prepare_image_for_azure(cropped)
            _, retry_dfs = run_azure_ocr(img_bytes, azure_client, page_num=page_num)
            return retry_dfs
        except Exception as e:
            self._log("ERROR", f"  Auto-retry Azure API call failed: {e}")
            return []

    def _output_path(self, src: Path, extension: str, status: str = "RECONCILED") -> Path:
        """
        Build the output path for a processed file.
        UNRECONCILED documents are routed to a Quarantine subfolder.
        """
        if status == "UNRECONCILED":
            quarantine_dir = Path(self.output_folder) / "Quarantine"
            os.makedirs(quarantine_dir, exist_ok=True)
            return quarantine_dir / (src.stem + extension)
        return Path(self.output_folder) / (src.stem + extension)

    def _save_claude_payload(
        self, src: Path, combined_text: str, all_dfs: list[pd.DataFrame], status: str, exc_entry: dict
    ):
        """Generates a structured XML payload optimized for LLM downstream consumption."""
        import textwrap
        xml_path = self._output_path(src, "_payload.xml", status)
        os.makedirs(xml_path.parent, exist_ok=True)
        
        calc_total = exc_entry.get("Calculated_Total")
        printed_total = exc_entry.get("Printed_Grand_Total")
        
        xml_content = [
            "<document>",
            "  <metadata>",
            f"    <status>{status}</status>",
            f"    <Calculated_Total>{calc_total if calc_total is not None else ''}</Calculated_Total>",
            f"    <Printed_Grand_Total>{printed_total if printed_total is not None else ''}</Printed_Grand_Total>",
            "  </metadata>",
            "  <exceptions>"
        ]
        
        row_exceptions = exc_entry.get("row_exceptions", [])
        if row_exceptions:
            for exc in row_exceptions:
                t_idx = exc.get("table", "")
                r_idx = exc.get("row", "")
                note = exc.get("note", "")
                xml_content.append(f"    <error table=\"{t_idx}\" row=\"{r_idx}\">{note}</error>")
        else:
            xml_content[-1] = "  <exceptions />"
            
        if row_exceptions:
            xml_content.append("  </exceptions>")
            
        xml_content.append("  <tables>")
        
        for idx, df in enumerate(all_dfs, start=1):
            xml_content.append(f'    <table id="{idx}">')
            # Convert pandas DataFrame to Markdown
            md_table = df.to_markdown(index=False)
            xml_content.append(textwrap.indent(md_table, "      "))
            xml_content.append("    </table>")
            
        xml_content.append("  </tables>")
        xml_content.append("  <raw_text>")
        xml_content.append("<![CDATA[")
        xml_content.append(combined_text)
        xml_content.append("]]>")
        xml_content.append("  </raw_text>")
        xml_content.append("</document>")
        
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(xml_content))
            
        self._log("INFO", f"  LLM Payload saved → {xml_path.name}")

    def _save_text_output(self, src: Path, combined_text: str, status: str):
        """Save the raw extracted text for quick review and downstream use."""
        txt_path = self._output_path(src, "_text.txt", status)
        os.makedirs(txt_path.parent, exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(combined_text)
        self._log("INFO", f"  Text saved → {txt_path.name}")

    def _save_tables_csv(self, src: Path, all_dfs: list[pd.DataFrame], status: str):
        """Save all extracted tables into one labeled CSV file."""
        if not all_dfs:
            return

        csv_path = self._output_path(src, "_tables.csv", status)
        os.makedirs(csv_path.parent, exist_ok=True)

        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            for idx, df in enumerate(all_dfs, start=1):
                f.write(f"--- TABLE {idx} ---\n")
                df.to_csv(f, index=False)
                f.write("\n")

        self._log("INFO", f"  Tables saved → {csv_path.name}")

    # ------------------------------------------------------------------
    # Per-page processing helpers
    # ------------------------------------------------------------------
    def _process_pil_page(
        self,
        pil_image: Image.Image,
        src_file: Path,
        page_label: str,
        page_num: int = 1,
    ) -> tuple[str, list[pd.DataFrame], bool, list[dict]]:
        """
        Run the Local→Cloud pipeline on a single PIL Image.
        Returns (text, dataframes, is_handwritten, entity_exceptions).
        """
        text = ""
        dfs = []
        conf = 0.0
        has_table = False
        is_handwritten = False
        entity_exceptions = []

        self._last_conf = 0.0
        self._last_engine = "Unknown"
        self._last_tables = 0

        # --- PATH 0: Layer 2 Triage & Layer 5 Handwriting Check ---
        pil_image, osd_data = _triage_and_rotate(pil_image)
        script_conf = osd_data.get('script_conf', 100.0)
        
        # Handwriting heuristic: exceptionally low script confidence
        if script_conf < 2.0 and osd_data:
            self._log("WARNING", f"  {page_label}: Handwriting detected (OSD script confidence {script_conf}). Bypassing OCR.")
            self._last_engine = "Handwriting Lane"
            return "[HANDWRITTEN PAGE - REQUIRES AI VISION LANE]", [], True, []

        # --- PATH 1: Balance Sheet Mode is ON (Force Azure) ---
        if self.balance_sheet:
            self._log(
                "INFO",
                f"  {page_label}: Skipping local OCR (Balance Sheet Mode ON). Invoking Azure immediately.",
            )
            try:
                img_bytes = prepare_image_for_azure(pil_image)
                azure_text, dfs = run_azure_ocr(img_bytes, self._get_azure_client(), page_num=page_num)

                if azure_text:
                    text = azure_text
                    self._last_engine = "Azure"
                    self._last_conf = 100.0  # Placeholder for direct Azure extraction
                    self._log(
                        "INFO", f"  {page_label}: Azure text extraction successful."
                    )
                else:
                    self._log(
                        "WARNING",
                        f"  {page_label}: Azure returned no text. Falling back to local Tesseract OCR.",
                    )

                if dfs:
                    self._last_tables = len(dfs)
                    self._log(
                        "INFO",
                        f"  {page_label}: {len(dfs)} table(s) extracted and saved as CSV.",
                    )
                    for i, df in enumerate(dfs):
                        text += f"\n\n--- EXTRACTED TABLE {i+1} ---\n"
                        text += df.to_string(index=False)
                        text += "\n-------------------------\n"
                else:
                    self._log("INFO", f"  {page_label}: No tables detected by Azure.")

            except Exception as e:
                import traceback
                msg = e.error.message if (hasattr(e, "error") and e.error) else str(e)
                self._log(
                    "ERROR",
                    f"  {page_label}: Azure API error — {msg}. Traceback: {traceback.format_exc()}. Falling back to Tesseract.",
                )

        # --- PATH 2: Normal Mode (Or Azure Failed) ---
        if not text:
            # Step A: Local Tesseract OCR
            tess_img = mask_stamp_ink(pil_image)
            tess_img = remove_grid_lines(tess_img)
            
            # --- R20: Dynamic Script Selection ---
            page_script = osd_data.get('script', 'Unknown')
            if page_script == 'Gujarati':
                dynamic_lang = 'guj+eng'
            elif page_script == 'Devanagari':
                dynamic_lang = 'hin+mar+eng'
            elif page_script == 'Latin':
                dynamic_lang = 'eng'
            else:
                dynamic_lang = self.tess_lang
                
            self._log("INFO", f"  {page_label}: Dynamic Language Selection -> script: {page_script}, lang: {dynamic_lang}")
            
            text, conf = run_tesseract(tess_img, dynamic_lang)
            self._last_conf = conf
            self._last_engine = "Tesseract"

            if not text:
                self._log(
                    "WARNING",
                    f"  {page_label}: No text detected by Tesseract. Page may be blank.",
                )
                return "", [], False, []

            if conf < self.risk_thresh:
                self._log(
                    "WARNING",
                    f"  {page_label}: HIGH RISK — Tesseract confidence {conf}%.",
                )
            elif conf < self.warn_thresh:
                self._log(
                    "WARNING",
                    f"  {page_label}: WARNING — Tesseract confidence {conf}%. Sending to Azure.",
                )
            else:
                self._log("INFO", f"  {page_label}: Tesseract confidence {conf}% — OK.")

            # Auto-detect tables
            has_table = detect_table_from_text(text)

            # Step C: Decide whether to invoke Azure
            use_azure = has_table or (conf < self.warn_thresh)

            if use_azure:
                mode_reason = (
                    "Auto-detected tabular data"
                    if has_table
                    else f"low confidence ({conf}%)"
                )
                self._log(
                    "INFO",
                    f"  {page_label}: Invoking Azure Document Intelligence ({mode_reason}).",
                )
                try:
                    img_bytes = prepare_image_for_azure(pil_image)
                    azure_text, dfs = run_azure_ocr(img_bytes, self._get_azure_client(), page_num=page_num)

                    if azure_text:
                        text = azure_text  # Azure result takes precedence
                        self._last_engine = "Azure"
                        self._log(
                            "INFO", f"  {page_label}: Azure text extraction successful."
                        )
                    else:
                        self._log(
                            "WARNING",
                            f"  {page_label}: Azure returned no text. Using Tesseract fallback.",
                        )

                    if dfs:
                        self._last_tables = len(dfs)
                        self._log(
                            "INFO",
                            f"  {page_label}: {len(dfs)} table(s) extracted and saved as CSV.",
                        )
                        for i, df in enumerate(dfs):
                            text += f"\n\n--- EXTRACTED TABLE {i+1} ---\n"
                            text += df.to_string(index=False)
                            text += "\n-------------------------\n"
                    else:
                        self._log(
                            "INFO", f"  {page_label}: No tables detected by Azure."
                        )

                except Exception as e:
                    msg = (
                        e.error.message if (hasattr(e, "error") and e.error) else str(e)
                    )
                    self._log(
                        "ERROR",
                        f"  {page_label}: Azure API error — {msg}. Falling back to Tesseract.",
                    )

        # --- PATH 3: R11 Exception-Driven Escalation ---
        if dfs:
            for i in range(len(dfs)):
                df = dfs[i]
                needs_retry = False
                
                if "Validation_Status" in df.columns and (df["Validation_Status"] == "FAIL").any():
                    needs_retry = True
                elif "Completeness_Status" in df.columns and (df["Completeness_Status"] == "FAIL (Rows Dropped)").any():
                    needs_retry = True
                
                if needs_retry and "Y_Coord" in df.columns:
                    y_series = pd.to_numeric(df["Y_Coord"], errors='coerce').dropna()
                    if not y_series.empty:
                        y_min = y_series.min()
                        y_max = y_series.max()
                        
                        self._log("WARNING", f"  {page_label}: Table {i+1} failed validation/completeness. Initiating auto-retry.")
                        retry_dfs = self._crop_and_retry(pil_image, y_min, y_max, self._get_azure_client(), page_num)
                        
                        if retry_dfs:
                            retry_df = retry_dfs[0]
                            retry_fails = False
                            if "Validation_Status" in retry_df.columns and (retry_df["Validation_Status"] == "FAIL").any():
                                retry_fails = True
                            if "Completeness_Status" in retry_df.columns and (retry_df["Completeness_Status"] == "FAIL (Rows Dropped)").any():
                                retry_fails = True
                                
                            if not retry_fails:
                                self._log("INFO", f"  {page_label}: Auto-retry successful! Seamlessly replacing table.")
                                dfs[i] = retry_df
                            else:
                                self._log("WARNING", f"  {page_label}: Auto-retry also failed. Keeping original data.")
                        else:
                            self._log("WARNING", f"  {page_label}: Auto-retry returned no tables. Keeping original data.")

        # --- Layer 6: QR/Barcode Extraction ---
        qr_payloads = extract_qr_payload(pil_image)
        if qr_payloads:
            self._log("INFO", f"  {page_label}: QR/Barcode detected and decoded.")
            qr_text = "\n".join(qr_payloads)
            text = f"--- DECODED QR PAYLOAD ---\n{qr_text}\n\n{text}"
            
        # --- Layer 6: Entity-Criticality Validation ---
        if text:
            entity_exc = validate_critical_entities(text, self._last_conf)
            if entity_exc:
                self._log("WARNING", f"  {page_label}: Critical entity found in low-confidence text. Flagging for Quarantine.")
                entity_exceptions.extend(entity_exc)

        return text, dfs, is_handwritten, entity_exceptions

    # ------------------------------------------------------------------
    # File-level handlers
    # ------------------------------------------------------------------
    def _handle_pdf(self, src: Path):
        """Process a single PDF file through the hybrid pipeline."""
        import time

        start_time = time.perf_counter()
        self.current_metrics = []
        self._doc_requires_vision = False

        try:
            doc = fitz.open(str(src))
        except Exception:
            self._log(
                "ERROR",
                f"Could not open PDF '{src.name}'. "
                "The file may be password-protected, corrupted, or unsupported.",
            )
            return

        all_text_parts = []
        all_dfs = []
        all_entity_exceptions = []

        for page_num in range(len(doc)):
            if self.stop_event.is_set():
                break

            page = doc[page_num]
            page_label = f"Page {page_num + 1}/{len(doc)}"

            # --- Digital text extraction (PyMuPDF) ---
            digital_text = page.get_text("text").strip()
            if digital_text:
                if validate_text_layer(digital_text):
                    self._log(
                        "INFO",
                        f"  {page_label}: Digital text layer found and validated "
                        f"({len(digital_text)} chars) — skipping OCR.",
                    )

                    self.current_metrics.append(
                        {
                            "page": page_num + 1,
                            "engine": "Digital PDF",
                            "confidence": 100.0,
                            "tables": 0,
                            "time": 0.01,
                        }
                    )

                    all_text_parts.append(digital_text)
                    continue  # Skip OCR entirely for this page
                else:
                    self._log(
                        "WARNING",
                        f"  {page_label}: Digital text layer rejected (garbage encoding). Forcing OCR."
                    )

            # --- Render scanned page to PIL Image at 300 DPI ---
            mat = fitz.Matrix(TARGET_DPI / 72, TARGET_DPI / 72)  # 72 pt = 1 inch
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pil_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            page_start = time.perf_counter()
            page_text, page_dfs, is_hw, entity_exc = self._process_pil_page(
                pil_image, src, page_label, page_num=page_num + 1
            )
            if is_hw:
                self._doc_requires_vision = True
            if entity_exc:
                all_entity_exceptions.extend(entity_exc)
            page_time = time.perf_counter() - page_start

            # Since _process_pil_page handles logging, we just guess the engine used based on confidence
            # A more robust way would be to return metrics from _process_pil_page, but this works:
            text_conf = getattr(
                self, "_last_conf", 0.0
            )  # We'll set this inside _process_pil_page
            engine_used = getattr(self, "_last_engine", "Tesseract")
            tables_found = getattr(self, "_last_tables", 0)

            self.current_metrics.append(
                {
                    "page": page_num + 1,
                    "engine": engine_used,
                    "confidence": text_conf,
                    "tables": tables_found,
                    "time": page_time,
                }
            )

            if page_text:
                all_text_parts.append(page_text)
            if page_dfs:
                all_dfs.extend(page_dfs)

        total_pages = len(doc)
        doc.close()

        # Evaluate combined text extraction
        combined = "\n\n".join(all_text_parts).strip()
        if not combined:
            self._log(
                "WARNING",
                f"  '{src.name}': No text could be extracted from any page. "
                "No output file created.",
            )

        total_time = time.perf_counter() - start_time

        # ------------------------------------------------------------------
        # Document-level reconciliation
        # ------------------------------------------------------------------
        status, exc_entry = reconcile_document(
            src, combined, all_dfs, all_entity_exceptions, self.balance_sheet
        )
        if getattr(self, "_doc_requires_vision", False):
            status = "UNRECONCILED"
            exc_entry["status"] = "UNRECONCILED"
            exc_entry["note"] = "Requires AI Vision Lane"
        self.exceptions_list.append(exc_entry)

        dest_label = "Quarantine" if status == "UNRECONCILED" else "Output"
        self._log(
            "WARNING" if status == "UNRECONCILED" else "INFO",
            f"  '{src.name}': Reconciliation → {status} (routed to {dest_label}).",
        )

        if combined:
            self._save_text_output(src, combined, status)
            self._save_tables_csv(src, all_dfs, status)
            self._save_claude_payload(src, combined, all_dfs, status, exc_entry)

        self._generate_pdf_report(src, total_time, total_pages, combined, status)

    def _handle_image(self, src: Path):
        """Process a single image file (JPG, PNG, TIFF) through the hybrid pipeline."""
        import time

        start_time = time.perf_counter()
        self.current_metrics = []
        self._doc_requires_vision = False

        try:
            pil_image = Image.open(str(src))
        except Exception:
            self._log(
                "ERROR",
                f"Could not open image '{src.name}'. "
                "The file may be corrupted or in an unsupported variant.",
            )
            return

        page_text, page_dfs, is_hw, entity_exc = self._process_pil_page(pil_image, src, "Image")
        if is_hw:
            self._doc_requires_vision = True

        text_conf = getattr(self, "_last_conf", 0.0)
        engine_used = getattr(self, "_last_engine", "Tesseract")
        tables_found = getattr(self, "_last_tables", 0)

        self.current_metrics.append(
            {
                "page": 1,
                "engine": engine_used,
                "confidence": text_conf,
                "tables": tables_found,
                "time": time.perf_counter() - start_time,
            }
        )

        if not page_text:
            self._log(
                "WARNING",
                f"  '{src.name}': No text could be extracted. "
                "No output file created.",
            )

        combined_text = page_text if page_text else ""

        # ------------------------------------------------------------------
        # Document-level reconciliation
        # ------------------------------------------------------------------
        status, exc_entry = reconcile_document(src, combined_text, page_dfs, entity_exc, getattr(self, 'balance_sheet', False))
        if getattr(self, "_doc_requires_vision", False):
            status = "UNRECONCILED"
            exc_entry["status"] = "UNRECONCILED"
            exc_entry["note"] = "Requires AI Vision Lane"
        self.exceptions_list.append(exc_entry)

        dest_label = "Quarantine" if status == "UNRECONCILED" else "Output"
        self._log(
            "WARNING" if status == "UNRECONCILED" else "INFO",
            f"  '{src.name}': Reconciliation → {status} (routed to {dest_label}).",
        )

        if combined_text:
            self._save_text_output(src, combined_text, status)
            self._save_tables_csv(src, page_dfs, status)
            self._save_claude_payload(src, combined_text, page_dfs, status, exc_entry)

        self._generate_pdf_report(
            src, time.perf_counter() - start_time, 1, combined_text, status
        )

    def _generate_pdf_report(
        self, src: Path, total_time: float, total_pages: int, combined_text: str,
        status: str = "RECONCILED"
    ):
        """Generates a human-readable PDF report containing metrics and the full extracted text."""
        import textwrap

        try:
            doc = fitz.open()
            page = doc.new_page()

            y_pos = 50

            # Title
            page.insert_text(
                (50, y_pos), "OCR Conversion Report", fontname="hebo", fontsize=18
            )
            y_pos += 30

            word_count = len(combined_text.split())
            char_count = len(combined_text)
            line_count = len(combined_text.splitlines())

            # Metadata
            page.insert_text(
                (50, y_pos), f"File: {src.name}", fontname="hebo", fontsize=12
            )
            y_pos += 20
            page.insert_text(
                (50, y_pos),
                f"Date Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                fontname="helv",
                fontsize=12,
            )
            y_pos += 20
            
            # Left column
            page.insert_text(
                (50, y_pos), f"Total Pages: {total_pages}", fontname="helv", fontsize=12
            )
            # Right column
            page.insert_text(
                (300, y_pos), f"Estimated Tokens (Words): {word_count:,}", fontname="helv", fontsize=12
            )
            y_pos += 20
            
            page.insert_text(
                (50, y_pos),
                f"Processing Time: {total_time:.2f} seconds",
                fontname="helv",
                fontsize=12,
            )
            page.insert_text(
                (300, y_pos), f"Character Count: {char_count:,}", fontname="helv", fontsize=12
            )
            y_pos += 20
            
            page.insert_text(
                (300, y_pos), f"Line Count: {line_count:,}", fontname="helv", fontsize=12
            )
            y_pos += 40

            # Table Header
            page.insert_text((50, y_pos), "Page Details:", fontname="hebo", fontsize=14)
            y_pos += 20
            page.insert_text(
                (50, y_pos),
                "Page | Engine | Confidence | Tables | Time",
                fontname="cobo",
                fontsize=10,
            )
            y_pos += 15
            page.insert_text((50, y_pos), "-" * 65, fontname="cour", fontsize=10)
            y_pos += 15

            # Table Rows
            avg_conf = 0.0
            for m in self.current_metrics:
                avg_conf += m["confidence"]
                row_str = f"P {m['page']:<3}| {m['engine']:<8} | {m['confidence']:>8.2f}% | {m['tables']:>6} | {m['time']:>5.2f}s"
                page.insert_text((50, y_pos), row_str, fontname="cour", fontsize=10)
                y_pos += 15

            y_pos += 20
            if len(self.current_metrics) > 0:
                page.insert_text(
                    (50, y_pos),
                    f"Average Confidence: {(avg_conf / len(self.current_metrics)):.2f}%",
                    fontname="hebo",
                    fontsize=12,
                )

            y_pos += 40
            page.insert_text(
                (50, y_pos), "Extracted Text:", fontname="hebo", fontsize=14
            )
            y_pos += 20

            # Load universal font to support Hindi/Marathi/Gujarati if present
            font_path = Path(__file__).resolve().parents[2] / "FreeSans.ttf"
            txt_font = "cour"
            try:
                if font_path.exists():
                    page.insert_font(fontname="freesans", fontfile=str(font_path))
                    txt_font = "freesans"
            except Exception:
                pass

            for line in combined_text.split("\n"):
                # Wrap long lines so they don't go off the PDF edge
                wrapped_lines = textwrap.wrap(line, width=85) if line.strip() else [""]
                for w_line in wrapped_lines:
                    if y_pos > 800:  # Bottom margin
                        page = doc.new_page()
                        y_pos = 50
                        if txt_font == "freesans":
                            page.insert_font(
                                fontname="freesans", fontfile=str(font_path)
                            )
                    page.insert_text(
                        (50, y_pos), w_line, fontname=txt_font, fontsize=10
                    )
                    y_pos += 12

            report_path = self._output_path(src, "_human_report.pdf", status)
            os.makedirs(report_path.parent, exist_ok=True)
            doc.save(str(report_path))
            doc.close()
            self._log("INFO", f"  Report saved → {report_path.name}")
        except Exception as e:
            self._log("ERROR", f"Failed to generate PDF report: {e}")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, progress_callback=None):
        """
        Execute the pipeline for all files in input_folder.

        Parameters
        ----------
        progress_callback : callable(current: int, total: int) | None
            Called after each file completes so the GUI can update its progress bar.
        """
        self._log("INFO", "=" * 60)
        self._log("INFO", "OCR Pipeline started.")
        self._log("INFO", f"Input  folder : {self.input_folder}")
        self._log("INFO", f"Output folder : {self.output_folder}")
        self._log("INFO", f"Tesseract lang: {self.tess_lang}")
        self._log(
            "INFO", f"Balance Sheet Mode: {'ON' if self.balance_sheet else 'OFF'}"
        )
        self._log("INFO", "=" * 60)

        files = self._collect_files()
        total = len(files)

        if total == 0:
            self._log(
                "WARNING",
                "No supported files found in the input folder. "
                "Please add PDF, JPG, PNG, or TIFF files and try again.",
            )
            return

        self._log("INFO", f"Found {total} file(s) to process.")

        for idx, src in enumerate(files, start=1):
            if self.stop_event.is_set():
                self._log("INFO", "Processing cancelled by user.")
                break

            self._log("INFO", f"\n[{idx}/{total}] Processing: {src.name}")

            if src.suffix.lower() == ".pdf":
                self._handle_pdf(src)
            else:
                self._handle_image(src)

            if progress_callback:
                progress_callback(idx, total)

        self._log("INFO", "\n" + "=" * 60)
        self._log("INFO", "OCR Pipeline finished.")
        self._log("INFO", "=" * 60)

        # Write machine-readable exceptions.json for the entire batch
        self._write_exceptions_json()

    def _write_exceptions_json(self):
        """Serialise self.exceptions_list to exceptions.json in the output folder."""
        import json
        json_path = Path(self.output_folder) / "exceptions.json"
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.exceptions_list, f, indent=2, ensure_ascii=False, default=str)
            reconciled = sum(1 for e in self.exceptions_list if e["status"] == "RECONCILED")
            unreconciled = len(self.exceptions_list) - reconciled
            self._log(
                "INFO",
                f"  Exceptions report saved → {json_path.name} "
                f"({reconciled} RECONCILED, {unreconciled} UNRECONCILED)",
            )
        except Exception as e:
            self._log("ERROR", f"Failed to write exceptions.json: {e}")
