import queue
import threading
import os
from datetime import datetime
import configparser

import customtkinter as ctk

from src.utils.constants import CONFIG_FILE
from src.utils.config import load_config
from src.core.pipeline import OCRPipeline

class OCRApp(ctk.CTk):
    # Enhanced Colour palette (Modern Slate/Indigo Dark Theme with more vibrancy)
    CLR_ACCENT = "#4F46E5"  # Deep Indigo
    CLR_WARN = "#F59E0B"  # Amber warning
    CLR_ERROR = "#EF4444"  # Soft red
    CLR_SUCCESS = "#10B981"  # Emerald success
    CLR_BG = "#0B0F19"  # Deep slate background
    CLR_SIDEBAR = "#1E293B"  # Slightly lighter sidebar for contrast
    CLR_SURFACE = "#334155"  # Surface slate
    CLR_TEXT = "#F8FAFC"  # White text

    def __init__(self):
        super().__init__()

        # ---- Window setup ----
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("OCR Utility — Enterprise Hybrid Processor")
        self.geometry("1100x750")
        self.minsize(900, 650)
        self.configure(fg_color=self.CLR_BG)

        # ---- State ----
        self.input_folder = ctk.StringVar(value="")
        self.output_folder = ctk.StringVar(value="")
        self.balance_sheet = ctk.BooleanVar(value=False)
        self.is_running = False
        self.had_error = False
        self.stop_event = threading.Event()
        self.log_queue: queue.Queue = queue.Queue()

        self.cfg: configparser.ConfigParser | None = None

        self._load_default_folders()
        self._build_ui()
        self._poll_log_queue()

    def _load_default_folders(self):
        try:
            cfg = load_config(CONFIG_FILE)
        except FileNotFoundError:
            return

        self.input_folder.set(cfg.get("FOLDERS", "input_folder", fallback=""))
        self.output_folder.set(cfg.get("FOLDERS", "output_folder", fallback=""))

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # =========================================================
        # 1. LEFT SIDEBAR
        # =========================================================
        sidebar = ctk.CTkFrame(
            self, fg_color=self.CLR_SIDEBAR, corner_radius=0, width=320
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(5, weight=1)

        # --- Logo / Title ---
        ctk.CTkLabel(
            sidebar,
            text="⚡ RCB OCR",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=self.CLR_ACCENT,
        ).pack(pady=(35, 5), padx=25, anchor="w")

        ctk.CTkLabel(
            sidebar,
            text="Enterprise Hybrid Processor",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color="#94A3B8",
        ).pack(pady=(0, 40), padx=25, anchor="w")

        # --- Folder Selectors ---
        self._create_folder_selector(sidebar, "INPUT DIRECTORY", self.input_folder, self._browse_input)
        self._create_folder_selector(sidebar, "OUTPUT DIRECTORY", self.output_folder, self._browse_output)

        # --- Settings ---
        ctk.CTkLabel(
            sidebar,
            text="PIPELINE SETTINGS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#64748B",
        ).pack(anchor="w", padx=25, pady=(10, 10))
        
        bs_box = ctk.CTkCheckBox(
            sidebar,
            text="Balance Sheet Mode\n(Force Azure Extraction)",
            variable=self.balance_sheet,
            font=ctk.CTkFont(size=14),
            checkbox_width=24,
            checkbox_height=24,
            fg_color=self.CLR_ACCENT,
            hover_color="#4338CA",
            border_color="#475569",
        )
        bs_box.pack(anchor="w", padx=25, pady=0)

        # --- Action Buttons ---
        btn_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=25, pady=35)
        
        self._start_btn = ctk.CTkButton(
            btn_frame,
            text="▶ LAUNCH PROCESSING",
            height=50,
            width=270,
            corner_radius=8,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=self.CLR_SUCCESS,
            hover_color="#059669",
            command=self._start_processing,
        )
        self._start_btn.pack(fill="x", pady=(0, 15))

        self._stop_btn = ctk.CTkButton(
            btn_frame,
            text="⛔ HALT",
            height=50,
            width=270,
            corner_radius=8,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#991B1B",
            hover_color="#7F1D1D",
            state="disabled",
            command=self._request_stop,
        )
        self._stop_btn.pack(fill="x")

        # =========================================================
        # 2. MAIN CONTENT AREA
        # =========================================================
        main_view = ctk.CTkFrame(self, fg_color="transparent")
        main_view.grid(row=0, column=1, sticky="nsew", padx=40, pady=35)

        # --- Header ---
        hdr = ctk.CTkFrame(main_view, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(
            hdr,
            text="Execution Console",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=self.CLR_TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            hdr,
            text="Clear Output",
            width=100,
            height=35,
            corner_radius=8,
            fg_color=self.CLR_SURFACE,
            hover_color="#475569",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._clear_log,
        ).pack(side="right")

        # --- Log Box ---
        self._log_box = ctk.CTkTextbox(
            main_view,
            font=ctk.CTkFont(family="Consolas", size=14),
            fg_color="#0F172A",
            text_color="#E2E8F0",
            corner_radius=12,
            wrap="word",
            state="disabled",
            border_width=1,
            border_color="#334155",
        )
        self._log_box.pack(fill="both", expand=True, pady=(0, 25))

        inner_text = self._log_box._textbox
        inner_text.tag_configure("INFO", foreground="#94A3B8")
        inner_text.tag_configure("WARNING", foreground=self.CLR_WARN)
        inner_text.tag_configure("ERROR", foreground=self.CLR_ERROR)
        inner_text.tag_configure("SUCCESS", foreground=self.CLR_SUCCESS)

        # --- Progress Bar ---
        prog_frame = ctk.CTkFrame(
            main_view, fg_color="#1E293B", corner_radius=12, height=70
        )
        prog_frame.pack(fill="x", side="bottom")
        prog_frame.pack_propagate(False)

        self._progress_label = ctk.CTkLabel(
            prog_frame, text="System Idle", font=ctk.CTkFont(size=14, weight="bold"), text_color="#94A3B8"
        )
        self._progress_label.pack(side="left", padx=25, pady=20)

        self._progress_bar = ctk.CTkProgressBar(
            prog_frame,
            mode="determinate",
            progress_color=self.CLR_ACCENT,
            height=16,
            width=300,
            corner_radius=8,
        )
        self._progress_bar.set(0)
        self._progress_bar.pack(side="right", padx=25, pady=20)

    def _create_folder_selector(self, parent, label_text, var, command):
        ctk.CTkLabel(
            parent,
            text=label_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#64748B",
        ).pack(anchor="w", padx=25, pady=(0, 5))
        
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=25, pady=(0, 25))
        
        entry = ctk.CTkEntry(
            frame,
            textvariable=var,
            placeholder_text="Select path...",
            height=40,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="#0F172A",
            border_color="#334155",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(
            frame,
            text="📁",
            width=40,
            height=40,
            corner_radius=6,
            fg_color=self.CLR_SURFACE,
            hover_color="#475569",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=18),
            command=command,
        ).pack(side="right")

    def _browse_input(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select Input Folder")
        if folder:
            self.input_folder.set(folder)

    def _browse_output(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder.set(folder)

    def _append_log(self, level: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        tag = level if level in ("INFO", "WARNING", "ERROR", "SUCCESS") else "INFO"
        line = f"[{ts}] {level:<8} │ {message}\n"

        self._log_box.configure(state="normal")
        inner = self._log_box._textbox
        inner.insert("end", line, tag)
        inner.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                level, msg = self.log_queue.get_nowait()
                self._append_log(level, msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _start_processing(self):
        if self.is_running:
            return

        gui_input = self.input_folder.get().strip()
        gui_output = self.output_folder.get().strip()

        try:
            self.cfg = load_config(CONFIG_FILE)
        except FileNotFoundError as e:
            self._append_log("ERROR", str(e))
            return

        if gui_input:
            self.cfg["FOLDERS"]["input_folder"] = gui_input
        if gui_output:
            self.cfg["FOLDERS"]["output_folder"] = gui_output

        input_path = self.cfg.get("FOLDERS", "input_folder").strip()
        if not os.path.isdir(input_path):
            self._append_log(
                "ERROR",
                f"Input directory missing: '{input_path}'. "
                "Please select a valid folder.",
            )
            return

        output_path = self.cfg.get("FOLDERS", "output_folder").strip()
        if not output_path:
            self._append_log("ERROR", "Output directory is missing. Please select a valid folder.")
            return
        os.makedirs(output_path, exist_ok=True)

        self.is_running = True
        self.had_error = False
        self.stop_event.clear()
        self._progress_bar.set(0)
        self._progress_label.configure(text="Initialising...", text_color=self.CLR_TEXT)
        self._start_btn.configure(state="disabled", text="⏳ PROCESSING...", fg_color="#475569")
        self._stop_btn.configure(state="normal")
        self._append_log("INFO", "━" * 60)
        self._append_log("INFO", "System Initialising Pipeline...")

        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()

    def _request_stop(self):
        if self.is_running:
            self.stop_event.set()
            self._append_log("WARNING", "Halt requested — gracefully exiting after current file...")
            self._stop_btn.configure(state="disabled", text="⏳ HALTING...")

    def _run_pipeline(self):
        pipeline = OCRPipeline(
            cfg=self.cfg,
            log_queue=self.log_queue,
            stop_event=self.stop_event,
            balance_sheet=self.balance_sheet.get(),
        )

        def progress_cb(current: int, total: int):
            frac = current / total
            self.after(0, self._update_progress, current, total, frac)

        try:
            pipeline.run(progress_callback=progress_cb)
        except Exception as exc:
            self.had_error = True
            self.log_queue.put(
                (
                    "ERROR",
                    f"CRITICAL ERROR: {exc}. "
                    "Check configuration.",
                )
            )
        finally:
            self.after(0, self._on_pipeline_done)

    def _update_progress(self, current: int, total: int, frac: float):
        self._progress_bar.set(frac)
        self._progress_label.configure(
            text=f"Processing {current}/{total} documents ({int(frac * 100)}%)"
        )

    def _on_pipeline_done(self):
        self.is_running = False
        self._start_btn.configure(state="normal", text="▶ LAUNCH PROCESSING", fg_color=self.CLR_SUCCESS)
        self._stop_btn.configure(state="disabled", text="⛔ HALT")

        if self.stop_event.is_set():
            self._progress_label.configure(text="Terminated by operator.", text_color=self.CLR_WARN)
            self._append_log("WARNING", "Pipeline sequence aborted.")
        elif self.had_error:
            self._progress_label.configure(text="Failed. Check error log.", text_color=self.CLR_ERROR)
            self._append_log("ERROR", "Pipeline failed. Please fix the error above and run again.")
        else:
            self._progress_bar.set(1.0)
            self._progress_label.configure(text="✅ Sequence Complete", text_color=self.CLR_SUCCESS)
            self._append_log("SUCCESS", "All tasks executed successfully.")
