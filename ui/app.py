"""
Modern CustomTkinter GUI for PBI Indexing Tool
Two-phase workflow:
1. Analyze & Match: Consolidate files, detect common columns, calculate month-wise stats from Pstng Date.
2. Review & Generate: Inspect matched/unmatched summary, and generate indexed files preserving nested directory structure.
"""

import os
import sys
import re
import json
import threading
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import pandas as pd

from core.indexer_engine import IndexerEngine, AnalysisResult

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


class ModernTreeview(ttk.Treeview):
    """Custom styled Treeview with alternate row coloring and sorted headers."""
    pass


class PBIIndexerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Appearance & Theme
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.title("PBI Indexer - Consolidation, Month-wise Matching & Index Generator")
        self.geometry("1150 x 820")
        self.minsize(980, 700)

        # State
        self.engine: Optional[IndexerEngine] = None
        self.analysis_result: Optional[AnalysisResult] = None
        self.is_processing: bool = False
        self.worker_thread: Optional[threading.Thread] = None

        # Build UI
        self._init_styles()
        self._build_header()
        self._build_input_section()
        self._build_action_section()
        self._build_metrics_cards()
        self._build_tabs_section()
        self._build_status_bar()

        # Load remembered paths from previous session
        self._load_saved_paths()

        # Save paths on window close
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Configure dark treeview
        style.configure(
            "Treeview",
            background="#242424",
            foreground="#EDEDED",
            fieldbackground="#242424",
            rowheight=28,
            font=("Segoe UI", 10),
            borderwidth=0
        )
        style.configure(
            "Treeview.Heading",
            background="#1E1E1E",
            foreground="#4DA8DA",
            font=("Segoe UI", 10, "bold"),
            borderwidth=1,
            relief="flat"
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#2D2D2D")]
        )
        style.map(
            "Treeview",
            background=[("selected", "#1F4068")],
            foreground=[("selected", "#FFFFFF")]
        )

    def _build_header(self):
        header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#18181B")
        header_frame.pack(fill="x", padx=0, pady=0)

        title_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_container.pack(fill="x", padx=20, pady=12)

        title_lbl = ctk.CTkLabel(
            title_container,
            text="PBI Indexing & Consolidation Tool",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#60A5FA"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = ctk.CTkLabel(
            title_container,
            text="   |   Multi-folder TSV Consolidation  •  Power Query Date Matching  •  Index Mapping",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF"
        )
        subtitle_lbl.pack(side="left", padx=5)

        # Theme toggle
        self.theme_btn = ctk.CTkButton(
            title_container,
            text="Light / Dark",
            width=90,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#374151",
            hover_color="#4B5563",
            command=self._toggle_theme
        )
        self.theme_btn.pack(side="right")

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        new_mode = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        # Adjust ttk styles for light/dark
        style = ttk.Style(self)
        if new_mode == "Light":
            style.configure("Treeview", background="#FFFFFF", foreground="#1F2937", fieldbackground="#FFFFFF")
            style.configure("Treeview.Heading", background="#E5E7EB", foreground="#1F2937")
            style.map("Treeview", background=[("selected", "#DBEAFE")], foreground=[("selected", "#1E3A8A")])
        else:
            style.configure("Treeview", background="#242424", foreground="#EDEDED", fieldbackground="#242424")
            style.configure("Treeview.Heading", background="#1E1E1E", foreground="#4DA8DA")
            style.map("Treeview", background=[("selected", "#1F4068")], foreground=[("selected", "#FFFFFF")])

    def _build_input_section(self):
        input_card = ctk.CTkFrame(self, corner_radius=8, fg_color=("#F3F4F6", "#212124"))
        input_card.pack(fill="x", padx=20, pady=(12, 6))

        # Grid configuration
        input_card.columnconfigure(1, weight=1)

        # 1. Input Folder
        lbl1 = ctk.CTkLabel(input_card, text="Input Folder (Nested TXT):", font=ctk.CTkFont(weight="bold"))
        lbl1.grid(row=0, column=0, padx=(15, 10), pady=(12, 6), sticky="w")

        self.input_folder_entry = ctk.CTkEntry(
            input_card,
            placeholder_text="Select root folder containing nested subfolders with .txt files..."
        )
        self.input_folder_entry.grid(row=0, column=1, padx=5, pady=(12, 6), sticky="ew")

        btn_browse_folder = ctk.CTkButton(
            input_card,
            text="Browse Folder...",
            width=120,
            command=self._browse_input_folder
        )
        btn_browse_folder.grid(row=0, column=2, padx=(5, 15), pady=(12, 6))

        # 2. Consolidated Index File
        lbl2 = ctk.CTkLabel(input_card, text="Consolidated Index File:", font=ctk.CTkFont(weight="bold"))
        lbl2.grid(row=1, column=0, padx=(15, 10), pady=6, sticky="w")

        self.index_file_entry = ctk.CTkEntry(
            input_card,
            placeholder_text="Select tab-separated consolidated CSV/TXT file with Index column..."
        )
        self.index_file_entry.grid(row=1, column=1, padx=5, pady=6, sticky="ew")

        btn_browse_file = ctk.CTkButton(
            input_card,
            text="Browse File...",
            width=120,
            command=self._browse_index_file
        )
        btn_browse_file.grid(row=1, column=2, padx=(5, 15), pady=6)

        # 3. Target / Filter Index CSV (Optional)
        lbl_target = ctk.CTkLabel(input_card, text="Target Index List (Optional CSV):", font=ctk.CTkFont(weight="bold"))
        lbl_target.grid(row=2, column=0, padx=(15, 10), pady=6, sticky="w")

        self.target_index_file_entry = ctk.CTkEntry(
            input_card,
            placeholder_text="Optional CSV with target Index numbers to reconcile (e.g. 1 Lakh list)..."
        )
        self.target_index_file_entry.grid(row=2, column=1, padx=5, pady=6, sticky="ew")

        btn_browse_target = ctk.CTkButton(
            input_card,
            text="Browse CSV...",
            width=120,
            command=self._browse_target_index_file
        )
        btn_browse_target.grid(row=2, column=2, padx=(5, 15), pady=6)

        # 4. Output Folder
        lbl3 = ctk.CTkLabel(input_card, text="Output Folder:", font=ctk.CTkFont(weight="bold"))
        lbl3.grid(row=3, column=0, padx=(15, 10), pady=(6, 12), sticky="w")

        self.output_folder_entry = ctk.CTkEntry(
            input_card,
            placeholder_text="Target folder to save indexed files in exact directory structure..."
        )
        self.output_folder_entry.grid(row=3, column=1, padx=5, pady=(6, 12), sticky="ew")

        out_btn_box = ctk.CTkFrame(input_card, fg_color="transparent")
        out_btn_box.grid(row=3, column=2, padx=(5, 15), pady=(6, 12), sticky="e")

        btn_auto_out = ctk.CTkButton(
            out_btn_box,
            text="Auto",
            width=45,
            fg_color="#4B5563",
            hover_color="#6B7280",
            command=self._auto_fill_output
        )
        btn_auto_out.pack(side="left", padx=(0, 5))

        btn_browse_out = ctk.CTkButton(
            out_btn_box,
            text="Browse Folder...",
            width=120,
            command=self._browse_output_folder
        )
        btn_browse_out.pack(side="left")

    def _build_action_section(self):
        action_card = ctk.CTkFrame(self, corner_radius=8, fg_color=("#F3F4F6", "#212124"))
        action_card.pack(fill="x", padx=20, pady=6)

        # Action Buttons
        btn_container = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_container.pack(fill="x", padx=15, pady=(10, 8))

        self.btn_analyze = ctk.CTkButton(
            btn_container,
            text="⚡ Step 1: Analyze & Match",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            height=36,
            command=self._start_analysis
        )
        self.btn_analyze.pack(side="left", padx=(0, 10))

        self.btn_generate = ctk.CTkButton(
            btn_container,
            text="📁 Step 2: Generate Indexed Files",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=36,
            state="disabled",
            command=self._confirm_and_generate
        )
        self.btn_generate.pack(side="left", padx=5)

        self.btn_cancel = ctk.CTkButton(
            btn_container,
            text="✕ Cancel",
            font=ctk.CTkFont(size=13),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            height=36,
            state="disabled",
            command=self._cancel_task
        )
        self.btn_cancel.pack(side="left", padx=5)

        self.btn_open_output = ctk.CTkButton(
            btn_container,
            text="📂 Open Output Folder",
            font=ctk.CTkFont(size=13),
            fg_color="#4B5563",
            hover_color="#6B7280",
            height=36,
            command=self._open_output_dir
        )
        self.btn_open_output.pack(side="right")

        # Progress bar & label
        prog_container = ctk.CTkFrame(action_card, fg_color="transparent")
        prog_container.pack(fill="x", padx=15, pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(prog_container)
        self.progress_bar.pack(fill="x", side="top", pady=(2, 4))
        self.progress_bar.set(0.0)

        self.progress_lbl = ctk.CTkLabel(
            prog_container,
            text="Ready. Select paths and click 'Step 1: Analyze & Match'.",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF"
        )
        self.progress_lbl.pack(side="left")

    def _build_metrics_cards(self):
        self.metrics_frame = ctk.CTkFrame(self, corner_radius=8, fg_color=("#F3F4F6", "#212124"))
        self.metrics_frame.pack(fill="x", padx=20, pady=6)

        # 7 Stat Cards
        for i in range(7):
            self.metrics_frame.columnconfigure(i, weight=1)

        self.card_files = self._create_metric_card(self.metrics_frame, 0, "Input Files", "0", "#60A5FA")
        self.card_rows = self._create_metric_card(self.metrics_frame, 1, "Valid Rows", "0", "#A78BFA")
        self.card_filtered_dates = self._create_metric_card(self.metrics_frame, 2, "Blank Dates Removed", "0", "#F59E0B")
        self.card_matched = self._create_metric_card(self.metrics_frame, 3, "Matched", "0 (0.0%)", "#34D399")
        self.card_unmatched = self._create_metric_card(self.metrics_frame, 4, "Unmatched (Input 1)", "0 (0.0%)", "#F87171")
        self.card_unmatched_indexes = self._create_metric_card(self.metrics_frame, 5, "Unmatched (Index File)", "0", "#E879F9")
        self.card_cols = self._create_metric_card(self.metrics_frame, 6, "Common Columns", "0", "#38BDF8")

    def _create_metric_card(self, parent, col, title, initial_val, color):
        card = ctk.CTkFrame(parent, corner_radius=6, fg_color=("#E5E7EB", "#18181B"))
        card.grid(row=0, column=col, padx=6, pady=8, sticky="nsew")

        lbl_t = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#9CA3AF")
        lbl_t.pack(anchor="w", padx=10, pady=(6, 2))

        lbl_v = ctk.CTkLabel(card, text=initial_val, font=ctk.CTkFont(size=16, weight="bold"), text_color=color)
        lbl_v.pack(anchor="w", padx=10, pady=(0, 6))
        return lbl_v

    def _build_tabs_section(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=8)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(6, 10))

        self.tab_summary = self.tabview.add("📊 Month-wise Summary")
        self.tab_columns = self.tabview.add("📋 Common Columns")
        self.tab_unmatched = self.tabview.add("🔍 Unmatched Preview")
        self.tab_logs = self.tabview.add("📜 Activity Log")

        self._setup_summary_tab()
        self._setup_columns_tab()
        self._setup_unmatched_tab()
        self._setup_logs_tab()

    def _setup_summary_tab(self):
        # Top toolbar of summary tab
        tb = ctk.CTkFrame(self.tab_summary, fg_color="transparent")
        tb.pack(fill="x", padx=10, pady=(6, 8))

        lbl = ctk.CTkLabel(
            tb,
            text="Month-wise matching breakdown derived from Pstng Date (Power Query conversion logic):",
            font=ctk.CTkFont(weight="bold")
        )
        lbl.pack(side="left")

        self.btn_export_unmatched_indexes = ctk.CTkButton(
            tb,
            text="📑 Download Unmatched from Index File (CSV)",
            width=280,
            command=self._download_unmatched_indexes_csv,
            state="disabled",
            fg_color="#8B5CF6",
            hover_color="#7C3AED"
        )
        self.btn_export_unmatched_indexes.pack(side="right", padx=(6, 0))

        self.btn_export_unmatched_separate = ctk.CTkButton(
            tb,
            text="📁 Export Each Month to Separate CSVs...",
            width=230,
            command=self._export_all_months_separate_csvs,
            state="disabled",
            fg_color="#4B5563",
            hover_color="#374151"
        )
        self.btn_export_unmatched_separate.pack(side="right", padx=(6, 0))

        self.btn_export_unmatched = ctk.CTkButton(
            tb,
            text="📥 Download Selected Month Unmatched (CSV)",
            width=245,
            command=self._download_selected_month_unmatched_csv,
            state="disabled",
            fg_color="#DC2626",
            hover_color="#B91C1C"
        )
        self.btn_export_unmatched.pack(side="right", padx=(6, 0))

        self.btn_export_summary = ctk.CTkButton(
            tb,
            text="💾 Export Summary Table (CSV)",
            width=175,
            command=self._export_summary_csv,
            state="disabled"
        )
        self.btn_export_summary.pack(side="right")

        # Treeview Container
        tree_frame = ctk.CTkFrame(self.tab_summary, corner_radius=6, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        columns = ("month", "total", "matched", "unmatched", "pct", "action")
        self.tree_summary = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree_summary.heading("month", text="Month / Period")
        self.tree_summary.heading("total", text="Total Records")
        self.tree_summary.heading("matched", text="Matched Records")
        self.tree_summary.heading("unmatched", text="Unmatched Records")
        self.tree_summary.heading("pct", text="Match %")
        self.tree_summary.heading("action", text="📥 Download CSV")

        self.tree_summary.column("month", width=190, anchor="w")
        self.tree_summary.column("total", width=110, anchor="e")
        self.tree_summary.column("matched", width=110, anchor="e")
        self.tree_summary.column("unmatched", width=120, anchor="e")
        self.tree_summary.column("pct", width=95, anchor="center")
        self.tree_summary.column("action", width=220, anchor="center")

        # Scrollbar
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_summary.yview)
        self.tree_summary.configure(yscrollcommand=sb.set)

        self.tree_summary.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Bindings for single click on action column, hover hand cursor, double-click, and right-click
        self.tree_summary.bind("<Button-1>", self._on_summary_click)
        self.tree_summary.bind("<Motion>", self._on_summary_motion)
        self.tree_summary.bind("<Double-1>", self._on_summary_row_double_click)
        self.tree_summary.bind("<Button-3>", self._on_summary_right_click)
        self.tree_summary.bind("<<TreeviewSelect>>", self._on_summary_select)

        # Selected Month Action Bar against the table
        self.selected_month_bar = ctk.CTkFrame(self.tab_summary, corner_radius=6, fg_color=("#E5E7EB", "#18181B"))
        self.selected_month_bar.pack(fill="x", padx=10, pady=(2, 6))

        self.lbl_selected_month_info = ctk.CTkLabel(
            self.selected_month_bar,
            text="👉 Click any month row above (or click '📥 Download CSV' in that row) to download its unmatched CSV",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9CA3AF"
        )
        self.lbl_selected_month_info.pack(side="left", padx=12, pady=6)

        self.btn_download_row_month = ctk.CTkButton(
            self.selected_month_bar,
            text="📥 Download Unmatched CSV for Selected Month",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            height=32,
            state="disabled",
            command=self._download_selected_month_unmatched_csv
        )
        self.btn_download_row_month.pack(side="right", padx=10, pady=6)

    def _setup_columns_tab(self):
        c_frame = ctk.CTkFrame(self.tab_columns, fg_color="transparent")
        c_frame.pack(fill="both", expand=True, padx=15, pady=10)

        self.lbl_schema_info = ctk.CTkLabel(
            c_frame,
            text="No analysis performed yet. Run Step 1 to inspect common columns and mappings.",
            font=ctk.CTkFont(size=13),
            justify="left"
        )
        self.lbl_schema_info.pack(anchor="w", pady=(5, 10))

        # Treeview for columns
        cols = ("idx", "input1_col", "arrow", "index_col")
        self.tree_cols = ttk.Treeview(c_frame, columns=cols, show="headings", height=12)
        self.tree_cols.heading("idx", text="#")
        self.tree_cols.heading("input1_col", text="Input 1 Column Name")
        self.tree_cols.heading("arrow", text="Match")
        self.tree_cols.heading("index_col", text="Consolidated Index File Column Name")

        self.tree_cols.column("idx", width=50, anchor="center")
        self.tree_cols.column("input1_col", width=260, anchor="w")
        self.tree_cols.column("arrow", width=60, anchor="center")
        self.tree_cols.column("index_col", width=260, anchor="w")

        sb = ttk.Scrollbar(c_frame, orient="vertical", command=self.tree_cols.yview)
        self.tree_cols.configure(yscrollcommand=sb.set)

        self.tree_cols.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _setup_unmatched_tab(self):
        u_frame = ctk.CTkFrame(self.tab_unmatched, fg_color="transparent")
        u_frame.pack(fill="both", expand=True, padx=15, pady=10)

        # Toolbar with Month selector & download buttons
        tb_unm = ctk.CTkFrame(u_frame, fg_color="transparent")
        tb_unm.pack(fill="x", pady=(0, 8))

        lbl_filter = ctk.CTkLabel(tb_unm, text="Select Month:", font=ctk.CTkFont(weight="bold"))
        lbl_filter.pack(side="left", padx=(0, 6))

        self.unmatched_month_var = tk.StringVar(value="Select Month")
        self.unmatched_month_dropdown = ctk.CTkOptionMenu(
            tb_unm,
            values=["Select Month"],
            variable=self.unmatched_month_var,
            command=self._on_unmatched_filter_change,
            width=210
        )
        self.unmatched_month_dropdown.pack(side="left", padx=5)

        self.lbl_unmatched_count = ctk.CTkLabel(
            tb_unm,
            text="0 records",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF"
        )
        self.lbl_unmatched_count.pack(side="left", padx=10)

        self.btn_export_unmatched_separate_2 = ctk.CTkButton(
            tb_unm,
            text="📁 Export Each Month to Separate CSVs...",
            width=230,
            command=self._export_all_months_separate_csvs,
            state="disabled",
            fg_color="#4B5563",
            hover_color="#374151"
        )
        self.btn_export_unmatched_separate_2.pack(side="right", padx=(5, 0))

        self.btn_download_month_unmatched = ctk.CTkButton(
            tb_unm,
            text="📥 Download This Month's CSV",
            width=190,
            command=self._download_filtered_unmatched_csv,
            state="disabled",
            fg_color="#DC2626",
            hover_color="#B91C1C"
        )
        self.btn_download_month_unmatched.pack(side="right", padx=5)

        # Treeview for unmatched records
        cols = ("file", "row", "date", "month", "sample_vals")
        self.tree_unmatched = ttk.Treeview(u_frame, columns=cols, show="headings")
        self.tree_unmatched.heading("file", text="File Relative Path")
        self.tree_unmatched.heading("row", text="Line #")
        self.tree_unmatched.heading("date", text="Pstng Date")
        self.tree_unmatched.heading("month", text="Detected Month")
        self.tree_unmatched.heading("sample_vals", text="Key Attributes Sample")

        self.tree_unmatched.column("file", width=240, anchor="w")
        self.tree_unmatched.column("row", width=60, anchor="center")
        self.tree_unmatched.column("date", width=110, anchor="center")
        self.tree_unmatched.column("month", width=150, anchor="w")
        self.tree_unmatched.column("sample_vals", width=380, anchor="w")

        sb = ttk.Scrollbar(u_frame, orient="vertical", command=self.tree_unmatched.yview)
        self.tree_unmatched.configure(yscrollcommand=sb.set)

        self.tree_unmatched.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _setup_logs_tab(self):
        log_frame = ctk.CTkFrame(self.tab_logs, fg_color="transparent")
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tb = ctk.CTkFrame(log_frame, fg_color="transparent")
        tb.pack(fill="x", pady=(0, 6))

        btn_clear = ctk.CTkButton(tb, text="Clear Log", width=90, command=self._clear_logs)
        btn_clear.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
            fg_color=("#FFFFFF", "#18181B")
        )
        self.log_textbox.pack(fill="both", expand=True)

    def _build_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color="#18181B")
        self.status_bar.pack(fill="x", side="bottom")

        self.status_lbl = ctk.CTkLabel(
            self.status_bar,
            text="Antigravity PBI Indexer v1.0 • Offline Desktop Engine",
            font=ctk.CTkFont(size=11),
            text_color="#6B7280"
        )
        self.status_lbl.pack(side="left", padx=15)

    # Logging & Progress Helpers
    def log(self, message: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{now_str}] {message}\n"
        self.after(0, lambda: self._append_log_text(formatted))

    def _append_log_text(self, text: str):
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def set_progress(self, pct: float, status_msg: str):
        self.after(0, lambda: self._update_progress_ui(pct, status_msg))

    def _update_progress_ui(self, pct: float, status_msg: str):
        self.progress_bar.set(pct)
        self.progress_lbl.configure(text=f"{int(pct * 100)}% - {status_msg}")

    # Path Persistence Helpers
    def _load_saved_paths(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                in_folder = data.get("input_folder", "")
                idx_file = data.get("index_file", "")
                target_idx = data.get("target_index_file", "")
                out_folder = data.get("output_folder", "")

                if in_folder:
                    self.input_folder_entry.delete(0, "end")
                    self.input_folder_entry.insert(0, in_folder)

                if idx_file:
                    self.index_file_entry.delete(0, "end")
                    self.index_file_entry.insert(0, idx_file)

                if target_idx:
                    self.target_index_file_entry.delete(0, "end")
                    self.target_index_file_entry.insert(0, target_idx)

                if out_folder:
                    self.output_folder_entry.delete(0, "end")
                    self.output_folder_entry.insert(0, out_folder)
        except Exception:
            pass

    def _save_current_paths(self):
        try:
            cfg = {
                "input_folder": self.input_folder_entry.get().strip(),
                "index_file": self.index_file_entry.get().strip(),
                "target_index_file": self.target_index_file_entry.get().strip(),
                "output_folder": self.output_folder_entry.get().strip(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _on_window_close(self):
        self._save_current_paths()
        self.destroy()

    # Browsing Actions
    def _browse_input_folder(self):
        path = filedialog.askdirectory(title="Select Input Folder Containing Nested TXT Files")
        if path:
            self.input_folder_entry.delete(0, "end")
            self.input_folder_entry.insert(0, path)
            if not self.output_folder_entry.get().strip():
                self._auto_fill_output()
            self._save_current_paths()

    def _browse_index_file(self):
        path = filedialog.askopenfilename(
            title="Select Consolidated Index File",
            filetypes=[
                ("Tab-delimited / CSV Files", "*.txt;*.tsv;*.csv"),
                ("All Files", "*.*")
            ]
        )
        if path:
            self.index_file_entry.delete(0, "end")
            self.index_file_entry.insert(0, path)
            self._save_current_paths()

    def _browse_target_index_file(self):
        path = filedialog.askopenfilename(
            title="Select Target Index List CSV (Optional)",
            filetypes=[
                ("CSV Files", "*.csv"),
                ("Text Files", "*.txt;*.tsv"),
                ("All Files", "*.*")
            ]
        )
        if path:
            self.target_index_file_entry.delete(0, "end")
            self.target_index_file_entry.insert(0, path)
            self._save_current_paths()

    def _browse_output_folder(self):
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_folder_entry.delete(0, "end")
            self.output_folder_entry.insert(0, path)
            self._save_current_paths()

    def _auto_fill_output(self):
        in_path = self.input_folder_entry.get().strip()
        if in_path:
            auto_path = str(Path(in_path).parent / f"{Path(in_path).name}_Indexed")
            self.output_folder_entry.delete(0, "end")
            self.output_folder_entry.insert(0, auto_path)
            self._save_current_paths()

    def _open_output_dir(self):
        out_dir = self.output_folder_entry.get().strip()
        if not out_dir or not Path(out_dir).exists():
            messagebox.showinfo("Folder Not Found", "Output folder does not exist yet or path is empty.")
            return
        # Open in Windows Explorer
        if sys.platform == "win32":
            os.startfile(out_dir)
        else:
            subprocess.run(["xdg-open", out_dir])

    # Phase 1: Analysis
    def _start_analysis(self):
        self._save_current_paths()
        in_folder = self.input_folder_entry.get().strip()
        index_file = self.index_file_entry.get().strip()
        target_index_file = self.target_index_file_entry.get().strip() or None

        if not in_folder or not Path(in_folder).is_dir():
            messagebox.showerror("Invalid Input", "Please select a valid Input Folder.")
            return

        if not index_file or not Path(index_file).is_file():
            messagebox.showerror("Invalid Input", "Please select a valid Consolidated Index File.")
            return

        self._set_ui_state(is_running=True)
        self.engine = IndexerEngine(
            log_callback=self.log,
            progress_callback=self.set_progress
        )

        def worker():
            try:
                res = self.engine.analyze(in_folder, index_file, target_index_file)
                self.after(0, lambda: self._on_analysis_success(res))
            except Exception as e:
                self.after(0, lambda: self._on_error("Analysis Error", str(e)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_analysis_success(self, res: AnalysisResult):
        self.analysis_result = res
        self._set_ui_state(is_running=False)

        # Update Metrics Cards
        self.card_files.configure(text=f"{res.total_input1_files:,}")
        self.card_rows.configure(text=f"{res.total_input1_rows:,}")
        self.card_filtered_dates.configure(text=f"{res.total_removed_blank_date_rows:,}")
        self.card_matched.configure(text=f"{res.total_matched_rows:,} ({res.match_percentage:.1f}%)")
        self.card_unmatched.configure(text=f"{res.total_unmatched_rows:,} ({100.0 - res.match_percentage:.1f}%)")
        unfound_idx_cnt = getattr(res, "total_unmatched_index_rows", 0)
        self.card_unmatched_indexes.configure(text=f"{unfound_idx_cnt:,}")
        self.card_cols.configure(text=f"{len(res.common_columns_input1):,}")
        self.btn_export_unmatched_indexes.configure(state="normal" if unfound_idx_cnt > 0 else "disabled")

        # Populate Month Summary Treeview
        for item in self.tree_summary.get_children():
            self.tree_summary.delete(item)

        for row in res.month_summary_data:
            unm_cnt = row.get("_unmatched_raw", 0)
            act_text = f"📥 Download CSV ({unm_cnt:,})" if unm_cnt > 0 else "✓ 0 Unmatched"
            self.tree_summary.insert(
                "",
                "end",
                values=(
                    row["Month / Period"],
                    f"{row['Total Records']:,}",
                    f"{row['Matched Records']:,}",
                    f"{row['Unmatched Records']:,}",
                    row["Match %"],
                    act_text
                )
            )

        # Add bold Total Row
        tot_unm = res.total_unmatched_rows
        tot_act = f"📁 Export All ({tot_unm:,})..." if tot_unm > 0 else "—"
        self.tree_summary.insert(
            "",
            "end",
            values=(
                "--- TOTAL ALL MONTHS ---",
                f"{res.total_input1_rows:,}",
                f"{res.total_matched_rows:,}",
                f"{res.total_unmatched_rows:,}",
                f"{res.match_percentage:.2f}%",
                tot_act
            )
        )

        # Populate Common Columns Tab
        for item in self.tree_cols.get_children():
            self.tree_cols.delete(item)

        self.lbl_schema_info.configure(
            text=f"Detected Posting Date Column: '{res.date_col_input1 or 'None'}'   |   "
                 f"Target Index Column: '{res.index_col_input2}'   |   "
                 f"Matching on {len(res.common_columns_input1)} Common Column(s)"
        )

        for idx, (c1, c2) in enumerate(zip(res.common_columns_input1, res.common_columns_input2), 1):
            self.tree_cols.insert("", "end", values=(idx, c1, "<===>", c2))

        # Populate Unmatched Preview Tab & Month Filter
        months_with_unmatched = [
            r["Month / Period"] for r in res.month_summary_data if r.get("_unmatched_raw", 0) > 0
        ]
        all_month_choices = [r["Month / Period"] for r in res.month_summary_data]
        if not all_month_choices:
            all_month_choices = ["No Data"]

        self.unmatched_month_dropdown.configure(values=all_month_choices)
        
        # Default to first month with unmatched records if available
        first_choice = months_with_unmatched[0] if months_with_unmatched else all_month_choices[0]
        self.unmatched_month_var.set(first_choice)

        unmatched_count = len(res.unmatched_df) if res.unmatched_df is not None else 0
        self.lbl_unmatched_count.configure(text=f"{unmatched_count:,} total unmatched")

        if res.unmatched_df is not None and not res.unmatched_df.empty:
            self._on_unmatched_filter_change(first_choice)
            self.btn_export_unmatched.configure(state="normal")
            self.btn_export_unmatched_separate.configure(state="normal")
            self.btn_download_month_unmatched.configure(state="normal")
            self.btn_export_unmatched_separate_2.configure(state="normal")
        else:
            for item in self.tree_unmatched.get_children():
                self.tree_unmatched.delete(item)
            self.btn_export_unmatched.configure(state="disabled")
            self.btn_export_unmatched_separate.configure(state="disabled")
            self.btn_download_month_unmatched.configure(state="disabled")
            self.btn_export_unmatched_separate_2.configure(state="disabled")

        # Enable Step 2 & Export buttons
        self.btn_generate.configure(state="normal")
        self.btn_export_summary.configure(state="normal")
        self.tabview.set("📊 Month-wise Summary")

        messagebox.showinfo(
            "Step 1 Analysis Complete",
            f"Analysis finished successfully!\n\n"
            f"• Files scanned: {res.total_input1_files}\n"
            f"• Total Rows: {res.total_input1_rows:,}\n"
            f"• Matched: {res.total_matched_rows:,} ({res.match_percentage:.2f}%)\n"
            f"• Unmatched: {res.total_unmatched_rows:,}\n\n"
            f"Please review the Month-wise Summary before generating the files in Step 2."
        )

    def _on_summary_row_double_click(self, event):
        selected_items = self.tree_summary.selection()
        if not selected_items:
            return
        row_vals = self.tree_summary.item(selected_items[0], "values")
        if row_vals and not str(row_vals[0]).startswith("--- TOTAL"):
            unm_str = str(row_vals[3]).replace(",", "").strip()
            if unm_str == "0":
                messagebox.showinfo("100% Matched", f"'{row_vals[0]}' has 0 unmatched records (100% matched!).")
                return
            self._download_selected_month_unmatched_csv()

    def _on_unmatched_filter_change(self, choice: str):
        if not self.analysis_result or self.analysis_result.unmatched_df is None or self.analysis_result.unmatched_df.empty:
            return
        df_all = self.analysis_result.unmatched_df
        df_sub = df_all[df_all["Month"] == choice]

        self.lbl_unmatched_count.configure(text=f"{len(df_sub):,} record(s) in {choice}")
        self._populate_unmatched_tree(df_sub)

    def _populate_unmatched_tree(self, df_subset: pd.DataFrame):
        for item in self.tree_unmatched.get_children():
            self.tree_unmatched.delete(item)

        sample_rows = df_subset.head(200)
        for _, row in sample_rows.iterrows():
            row_dict = row.to_dict()
            sample_keys = []
            for k, v in row_dict.items():
                if k not in ("File", "Line_Number", "Pstng Date", "Month", "Pstng_Date", "PSTNG DATE", "pstng date"):
                    sample_keys.append(f"{k}={v}")

            p_date = ""
            for dk in ["Pstng Date", "PSTNG DATE", "pstng date", "Pstng_Date"]:
                if dk in row_dict and pd.notna(row_dict[dk]):
                    p_date = str(row_dict[dk])
                    break

            self.tree_unmatched.insert(
                "",
                "end",
                values=(
                    row_dict.get("File", ""),
                    row_dict.get("Line_Number", ""),
                    p_date,
                    row_dict.get("Month", ""),
                    ", ".join(sample_keys[:4])
                )
            )

    def _download_month_unmatched_by_label(self, month_label: str):
        """Downloads unmatched CSV for a specific month label."""
        if not self.analysis_result or self.analysis_result.unmatched_df is None or self.analysis_result.unmatched_df.empty:
            messagebox.showinfo("No Unmatched Items", "There are no unmatched records to download.")
            return

        df_all = self.analysis_result.unmatched_df
        df_sub = df_all[df_all["Month"] == month_label]
        if df_sub.empty:
            messagebox.showinfo("0 Unmatched", f"There are 0 unmatched records for '{month_label}'.")
            return

        clean_m = re.sub(r'[^\w\-_]', '_', str(month_label)).strip('_')
        default_fn = f"Unmatched_{clean_m}.csv"
        save_path = filedialog.asksaveasfilename(
            title=f"Save Unmatched Records - {month_label}",
            initialfile=default_fn,
            defaultextension=".csv",
            filetypes=[("CSV File", "*.csv"), ("Excel File", "*.xlsx")]
        )
        if not save_path:
            return

        try:
            if save_path.lower().endswith(".xlsx"):
                df_sub.to_excel(save_path, index=False)
            else:
                df_sub.to_csv(save_path, index=False)
            messagebox.showinfo("Export Successful", f"Saved {len(df_sub):,} unmatched records for '{month_label}' to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to save CSV: {e}")

    def _on_summary_click(self, event):
        """Single click handler: if user clicks on Action column (#6), download CSV immediately."""
        row_id = self.tree_summary.identify_row(event.y)
        col_id = self.tree_summary.identify_column(event.x)
        if not row_id:
            return

        vals = self.tree_summary.item(row_id, "values")
        if not vals:
            return

        month_label = vals[0]
        self._update_selected_month_bar(month_label, vals)

        # If user clicked directly on the Action column (#6)
        if col_id == "#6":
            if str(month_label).startswith("--- TOTAL"):
                self._export_all_months_separate_csvs()
            else:
                self._download_month_unmatched_by_label(month_label)

    def _on_summary_motion(self, event):
        """Shows pointing hand cursor when hovering over actionable Download CSV cells."""
        row_id = self.tree_summary.identify_row(event.y)
        col_id = self.tree_summary.identify_column(event.x)
        if row_id and col_id == "#6":
            vals = self.tree_summary.item(row_id, "values")
            if vals and len(vals) > 5 and "0 Unmatched" not in str(vals[5]) and str(vals[5]) != "—":
                self.tree_summary.configure(cursor="hand2")
                return
        self.tree_summary.configure(cursor="")

    def _on_summary_row_double_click(self, event):
        """Double click anywhere on a month row downloads its unmatched CSV."""
        row_id = self.tree_summary.identify_row(event.y)
        if not row_id:
            item_id = self.tree_summary.focus()
            if item_id:
                row_id = item_id
        if not row_id:
            return
        vals = self.tree_summary.item(row_id, "values")
        if not vals:
            return
        month_label = vals[0]
        if str(month_label).startswith("--- TOTAL"):
            self._export_all_months_separate_csvs()
        else:
            self._download_month_unmatched_by_label(month_label)

    def _on_summary_right_click(self, event):
        """Right-click context menu on any month row."""
        row_id = self.tree_summary.identify_row(event.y)
        if not row_id:
            return
        self.tree_summary.selection_set(row_id)
        vals = self.tree_summary.item(row_id, "values")
        if not vals:
            return
        month_label = vals[0]
        if str(month_label).startswith("--- TOTAL"):
            return

        menu = tk.Menu(self, tearoff=0, bg="#27272A", fg="#F9FAFB", activebackground="#0284C7", activeforeground="#FFFFFF")
        menu.add_command(
            label=f"📥 Download Unmatched CSV for {month_label}",
            command=lambda: self._download_month_unmatched_by_label(month_label)
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _on_summary_select(self, event):
        """Updates the action bar when selection changes in the summary table."""
        selected_items = self.tree_summary.selection()
        if not selected_items:
            return
        vals = self.tree_summary.item(selected_items[0], "values")
        if not vals:
            return
        self._update_selected_month_bar(vals[0], vals)

    def _update_selected_month_bar(self, month_label: str, vals: tuple):
        """Updates the highlighted action bar directly below the table."""
        if str(month_label).startswith("--- TOTAL"):
            self.lbl_selected_month_info.configure(
                text=f"Total Across All Months: {vals[1]} Total | {vals[2]} Matched | {vals[3]} Unmatched ({vals[4]})"
            )
            self.btn_download_row_month.configure(
                text="📁 Export Each Month to Separate CSVs...",
                state="normal",
                command=self._export_all_months_separate_csvs
            )
            return

        unm_str = vals[3] if len(vals) > 3 else "0"
        has_unm = (unm_str != "0")
        self.lbl_selected_month_info.configure(
            text=f"Selected Month: {month_label}  •  Total: {vals[1]}  •  Matched: {vals[2]}  •  Unmatched: {unm_str} ({vals[4]})"
        )
        self.btn_download_row_month.configure(
            text=f"📥 Download Unmatched CSV for {month_label}",
            state="normal" if has_unm else "disabled",
            command=lambda: self._download_month_unmatched_by_label(month_label)
        )
        self.btn_export_unmatched.configure(
            text=f"📥 Download {month_label} Unmatched (CSV)",
            state="normal" if has_unm else "disabled"
        )

    def _download_selected_month_unmatched_csv(self):
        """Downloads unmatched CSV for the month selected in the summary table or active in dropdown."""
        if not self.analysis_result or self.analysis_result.unmatched_df is None or self.analysis_result.unmatched_df.empty:
            messagebox.showinfo("No Unmatched Items", "There are no unmatched records to download.")
            return

        # Check if user selected a month row in tree_summary
        selected_items = self.tree_summary.selection()
        selected_month = None
        if selected_items:
            row_vals = self.tree_summary.item(selected_items[0], "values")
            if row_vals and not str(row_vals[0]).startswith("--- TOTAL"):
                selected_month = row_vals[0]

        # If not selected in table, fall back to dropdown selection
        if not selected_month:
            current_choice = self.unmatched_month_var.get()
            if current_choice and current_choice not in ("Select Month", "No Data"):
                selected_month = current_choice

        if not selected_month:
            messagebox.showinfo(
                "Select a Month",
                "Please click on a specific month row in the table below to download its unmatched records."
            )
            return

        self._download_month_unmatched_by_label(selected_month)

    def _download_filtered_unmatched_csv(self):
        """Downloads unmatched CSV for the currently selected month in the dropdown."""
        choice = self.unmatched_month_var.get()
        if not self.analysis_result or self.analysis_result.unmatched_df is None or self.analysis_result.unmatched_df.empty:
            messagebox.showinfo("No Unmatched Items", "There are no unmatched records to download.")
            return

        if not choice or choice in ("Select Month", "No Data"):
            messagebox.showinfo("Select a Month", "Please select a specific month from the dropdown first.")
            return

        df_all = self.analysis_result.unmatched_df
        df_sub = df_all[df_all["Month"] == choice]
        if df_sub.empty:
            messagebox.showinfo("0 Unmatched", f"No unmatched records found for '{choice}'.")
            return

        clean_name = re.sub(r'[^\w\-_]', '_', str(choice)).strip('_')
        default_fn = f"Unmatched_{clean_name}.csv"
        save_path = filedialog.asksaveasfilename(
            title=f"Save Unmatched Records - {choice}",
            initialfile=default_fn,
            defaultextension=".csv",
            filetypes=[("CSV File", "*.csv"), ("Excel File", "*.xlsx")]
        )
        if not save_path:
            return

        try:
            if save_path.lower().endswith(".xlsx"):
                df_sub.to_excel(save_path, index=False)
            else:
                df_sub.to_csv(save_path, index=False)
            messagebox.showinfo("Export Successful", f"Saved {len(df_sub):,} unmatched records to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to save CSV: {e}")

    def _download_unmatched_indexes_csv(self):
        """Exports not found Index numbers from the Consolidated Index File."""
        if not self.analysis_result or getattr(self.analysis_result, "total_unmatched_index_rows", 0) == 0:
            messagebox.showinfo("No Unmatched Indexes", "All records in the Consolidated Index file were matched to Input 1!")
            return

        unfound_cnt = self.analysis_result.total_unmatched_index_rows
        default_name = f"NotFound_Index_Numbers_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        
        file_path = filedialog.asksaveasfilename(
            title=f"Save Not Found Index Numbers ({unfound_cnt:,} numbers) as CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        try:
            self.progress_lbl.configure(text=f"Exporting {unfound_cnt:,} not found index numbers...")
            self.update_idletasks()
            written = self.engine.export_unmatched_indexes_csv(self.analysis_result, file_path)
            messagebox.showinfo(
                "Export Successful",
                f"Successfully exported {written:,} not found index number(s) to:\n{file_path}"
            )
            self.log(f"Exported {written:,} not found Index numbers to: {file_path}")
            self.progress_lbl.configure(text=f"Exported {written:,} not found index numbers.")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to export not found index numbers:\n{e}")
            self.log(f"ERROR exporting not found index numbers: {e}")

    def _export_all_months_separate_csvs(self):
        """Exports each month's unmatched records as its own separate CSV file inside a chosen folder."""
        if not self.analysis_result or self.analysis_result.unmatched_df is None or self.analysis_result.unmatched_df.empty:
            messagebox.showinfo("No Unmatched Items", "There are no unmatched records to download.")
            return

        df_all = self.analysis_result.unmatched_df
        target_dir = filedialog.askdirectory(title="Select Destination Folder to Save Month-wise Unmatched CSV Files")
        if not target_dir:
            return

        dest_dir = Path(target_dir).resolve()
        unique_months = [m for m in df_all["Month"].unique() if m]
        files_saved = 0
        total_rows_saved = 0

        for m in unique_months:
            df_m = df_all[df_all["Month"] == m]
            if len(df_m) == 0:
                continue
            clean_m = re.sub(r'[^\w\-_]', '_', str(m)).strip('_')
            filename = f"Unmatched_{clean_m}.csv"
            out_file = dest_dir / filename
            df_m.to_csv(str(out_file), index=False, encoding="utf-8")
            files_saved += 1
            total_rows_saved += len(df_m)

        ans = messagebox.askyesno(
            "Month-wise Export Complete",
            f"Successfully saved {files_saved} individual month-wise CSV files ({total_rows_saved:,} total rows) in:\n{dest_dir}\n\n"
            f"Would you like to open the destination folder now?"
        )
        if ans:
            if sys.platform == "win32":
                os.startfile(str(dest_dir))
            else:
                subprocess.run(["xdg-open", str(dest_dir)])

    # Phase 2: Generation
    def _confirm_and_generate(self):
        if not self.analysis_result:
            messagebox.showwarning("Warning", "Please run Step 1 Analysis first.")
            return

        out_folder = self.output_folder_entry.get().strip()
        if not out_folder:
            self._auto_fill_output()
            out_folder = self.output_folder_entry.get().strip()

        # Confirmation dialog
        msg = (
            f"Ready to generate indexed files.\n\n"
            f"• Target Folder: {out_folder}\n"
            f"• Total Files: {self.analysis_result.total_input1_files}\n"
            f"• Matched Rows: {self.analysis_result.total_matched_rows:,}\n"
            f"• Unmatched Rows (blank index): {self.analysis_result.total_unmatched_rows:,}\n\n"
            f"Do you want to proceed and generate the indexed files now?"
        )
        if not messagebox.askyesno("Confirm File Generation", msg):
            return

        self._set_ui_state(is_running=True)

        def worker():
            try:
                written = self.engine.generate_indexed_files(self.analysis_result, out_folder)
                self.after(0, lambda: self._on_generation_success(written, out_folder))
            except Exception as e:
                self.after(0, lambda: self._on_error("Generation Error", str(e)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_generation_success(self, count: int, out_folder: str):
        self._set_ui_state(is_running=False)
        self.set_progress(1.0, f"Generated {count} indexed files successfully!")

        ans = messagebox.askyesno(
            "File Generation Complete!",
            f"Successfully generated {count} files with the 'Index' column added!\n\n"
            f"Saved to:\n{out_folder}\n\n"
            f"Would you like to open the output folder now?"
        )
        if ans:
            self._open_output_dir()

    def _export_summary_csv(self):
        if not self.analysis_result or self.analysis_result.month_summary_df is None:
            return

        save_path = filedialog.asksaveasfilename(
            title="Save Month-wise Summary",
            defaultextension=".csv",
            filetypes=[("CSV File", "*.csv"), ("Excel File", "*.xlsx")]
        )
        if not save_path:
            return

        try:
            clean_df = self.analysis_result.month_summary_df[
                ["Month / Period", "Total Records", "Matched Records", "Unmatched Records", "Match %"]
            ].copy()

            if save_path.lower().endswith(".xlsx"):
                clean_df.to_excel(save_path, index=False)
            else:
                clean_df.to_csv(save_path, index=False)

            messagebox.showinfo("Export Successful", f"Month summary exported to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to export summary: {e}")

    def _cancel_task(self):
        if self.engine:
            self.engine.cancel()
            self.log("Cancellation requested by user...")
            self.btn_cancel.configure(state="disabled")

    def _on_error(self, title: str, error_msg: str):
        self._set_ui_state(is_running=False)
        self.log(f"ERROR: {error_msg}")
        messagebox.showerror(title, error_msg)

    def _set_ui_state(self, is_running: bool):
        self.is_processing = is_running
        if is_running:
            self.btn_analyze.configure(state="disabled")
            self.btn_generate.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
            self.btn_export_summary.configure(state="disabled")
            self.btn_export_unmatched.configure(state="disabled")
            self.btn_export_unmatched_separate.configure(state="disabled")
            self.btn_download_month_unmatched.configure(state="disabled")
            self.btn_export_unmatched_separate_2.configure(state="disabled")
        else:
            self.btn_analyze.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            if self.analysis_result:
                self.btn_generate.configure(state="normal")
                self.btn_export_summary.configure(state="normal")
                if self.analysis_result.unmatched_df is not None and not self.analysis_result.unmatched_df.empty:
                    self.btn_export_unmatched.configure(state="normal")
                    self.btn_export_unmatched_separate.configure(state="normal")
                    self.btn_download_month_unmatched.configure(state="normal")
                    self.btn_export_unmatched_separate_2.configure(state="normal")


def run_app():
    app = PBIIndexerApp()
    app.mainloop()


if __name__ == "__main__":
    run_app()
