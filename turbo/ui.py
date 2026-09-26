"""
PBI Indexing Tool - Turbo Blazing Fast GUI
Powered by DuckDB Vectorized Multi-Threaded C++ Engine.
"""

import os
import sys
import json
import time
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk

from turbo.engine import TurboIndexerEngine, TurboAnalysisResult

CONFIG_FILE = Path(__file__).resolve().parent.parent / "turbo_config.json"
ORIGINAL_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


class TurboPBIIndexerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("⚡ PBI Indexing Tool - TURBO EDITION (Blazing Fast C++ Engine)")
        self.geometry("1300x890")
        self.minsize(1050, 720)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.engine: Optional[TurboIndexerEngine] = None
        self.analysis_result: Optional[TurboAnalysisResult] = None
        self.worker_thread: Optional[threading.Thread] = None

        self._load_paths()
        self._setup_style()
        self._build_ui()

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background="#1E1E24",
            foreground="#F3F4F6",
            fieldbackground="#1E1E24",
            rowheight=26,
            font=("Segoe UI", 10),
            borderwidth=0
        )
        style.configure(
            "Treeview.Heading",
            background="#27272A",
            foreground="#F9FAFB",
            font=("Segoe UI", 10, "bold"),
            borderwidth=1,
            relief="flat"
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#3F3F46")]
        )
        style.map(
            "Treeview",
            background=[("selected", "#0284C7")],
            foreground=[("selected", "#FFFFFF")]
        )

    def _load_paths(self):
        self.saved_input_folder = ""
        self.saved_index_file = ""
        self.saved_target_index_file = ""
        self.saved_output_folder = ""

        # Load from turbo_config.json or fallback to config.json
        cfg_path = CONFIG_FILE if CONFIG_FILE.exists() else ORIGINAL_CONFIG_FILE
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.saved_input_folder = data.get("input_folder", "")
                    self.saved_index_file = data.get("index_file", "")
                    self.saved_target_index_file = data.get("target_index_file", "")
                    self.saved_output_folder = data.get("output_folder", "")
            except Exception:
                pass

    def _save_current_paths(self):
        data = {
            "input_folder": self.input_folder_entry.get().strip(),
            "index_file": self.index_file_entry.get().strip(),
            "target_index_file": self.target_index_file_entry.get().strip(),
            "output_folder": self.output_folder_entry.get().strip()
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def _build_ui(self):
        # 1. Header Frame
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1E293B", "#0F172A"), height=64)
        header.pack(fill="x", side="top")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=10)

        title_lbl = ctk.CTkLabel(
            title_box,
            text="⚡ PBI INDEXING TOOL — TURBO EDITION",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#38BDF8"
        )
        title_lbl.pack(anchor="w")

        cpu_threads = os.cpu_count() or 4
        sub_lbl = ctk.CTkLabel(
            title_box,
            text=f"Powered by DuckDB Vectorized Multi-Threaded Engine ({cpu_threads} CPU Threads Active) • Blazing Fast Reconciliations",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        sub_lbl.pack(anchor="w")

        badge = ctk.CTkLabel(
            header,
            text="⚡ ULTRA PERFORMANCE",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284C7",
            text_color="#FFFFFF",
            corner_radius=6,
            padx=12,
            pady=4
        )
        badge.pack(side="right", padx=20)

        # 2. Main Scrollable Container
        main_content = ctk.CTkFrame(self, fg_color="transparent")
        main_content.pack(fill="both", expand=True, padx=20, pady=10)

        # Path Selectors Card
        path_card = ctk.CTkFrame(main_content, corner_radius=8, fg_color=("#F8FAFC", "#1E293B"))
        path_card.pack(fill="x", pady=(0, 8))

        path_card.columnconfigure(1, weight=1)

        # Row 0: Input Folder
        lbl_in = ctk.CTkLabel(path_card, text="Input Folder (Nested .txt):", font=ctk.CTkFont(weight="bold"))
        lbl_in.grid(row=0, column=0, padx=12, pady=6, sticky="w")

        self.input_folder_entry = ctk.CTkEntry(path_card, placeholder_text="Path to folder containing subfolders of .txt files")
        self.input_folder_entry.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        if self.saved_input_folder:
            self.input_folder_entry.insert(0, self.saved_input_folder)

        btn_browse_in = ctk.CTkButton(path_card, text="Browse...", width=95, command=self._browse_input_folder)
        btn_browse_in.grid(row=0, column=2, padx=12, pady=6)

        # Row 1: Consolidated Index File
        lbl_idx = ctk.CTkLabel(path_card, text="Consolidated Index File:", font=ctk.CTkFont(weight="bold"))
        lbl_idx.grid(row=1, column=0, padx=12, pady=6, sticky="w")

        self.index_file_entry = ctk.CTkEntry(path_card, placeholder_text="Path to consolidated index file (.txt, .tsv, .csv)")
        self.index_file_entry.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        if self.saved_index_file:
            self.index_file_entry.insert(0, self.saved_index_file)

        btn_browse_idx = ctk.CTkButton(path_card, text="Browse...", width=95, command=self._browse_index_file)
        btn_browse_idx.grid(row=1, column=2, padx=12, pady=6)

        # Row 2: Target / Filter Index CSV (Optional)
        lbl_target = ctk.CTkLabel(path_card, text="Target Index List (Optional CSV):", font=ctk.CTkFont(weight="bold"))
        lbl_target.grid(row=2, column=0, padx=12, pady=6, sticky="w")

        self.target_index_file_entry = ctk.CTkEntry(path_card, placeholder_text="Optional CSV with target Index numbers to reconcile (e.g. 1 Lakh list)")
        self.target_index_file_entry.grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        if self.saved_target_index_file:
            self.target_index_file_entry.insert(0, self.saved_target_index_file)

        btn_browse_target = ctk.CTkButton(path_card, text="Browse...", width=95, command=self._browse_target_index_file)
        btn_browse_target.grid(row=2, column=2, padx=12, pady=6)

        # Row 3: Output Folder
        lbl_out = ctk.CTkLabel(path_card, text="Output Folder:", font=ctk.CTkFont(weight="bold"))
        lbl_out.grid(row=3, column=0, padx=12, pady=6, sticky="w")

        self.output_folder_entry = ctk.CTkEntry(path_card, placeholder_text="Path where indexed subfolder hierarchy will be saved")
        self.output_folder_entry.grid(row=3, column=1, padx=6, pady=6, sticky="ew")
        if self.saved_output_folder:
            self.output_folder_entry.insert(0, self.saved_output_folder)

        btn_browse_out = ctk.CTkButton(path_card, text="Browse...", width=95, command=self._browse_output_folder)
        btn_browse_out.grid(row=3, column=2, padx=12, pady=6)

        # 3. Actions & Progress Bar
        action_card = ctk.CTkFrame(main_content, corner_radius=8, fg_color=("#F1F5F9", "#0F172A"))
        action_card.pack(fill="x", pady=(0, 8))

        btn_box = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=12, pady=8)

        self.btn_analyze = ctk.CTkButton(
            btn_box,
            text="⚡ Step 1: Turbo Analyze & Match",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=36,
            command=self._start_analysis
        )
        self.btn_analyze.pack(side="left", padx=(0, 6))

        self.btn_generate = ctk.CTkButton(
            btn_box,
            text="⚡ Step 2: Turbo Generate Indexed Files",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=36,
            state="disabled",
            command=self._confirm_and_generate
        )
        self.btn_generate.pack(side="left", padx=6)

        self.btn_cancel = ctk.CTkButton(
            btn_box,
            text="✕ Cancel",
            font=ctk.CTkFont(size=13),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            height=36,
            state="disabled",
            command=self._cancel_task
        )
        self.btn_cancel.pack(side="left", padx=6)

        self.btn_open_output = ctk.CTkButton(
            btn_box,
            text="📂 Open Output Folder",
            font=ctk.CTkFont(size=13),
            fg_color="#475569",
            hover_color="#334155",
            height=36,
            command=self._open_output_dir
        )
        self.btn_open_output.pack(side="right")

        # Progress
        prog_box = ctk.CTkFrame(action_card, fg_color="transparent")
        prog_box.pack(fill="x", padx=12, pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(prog_box, progress_color="#38BDF8")
        self.progress_bar.pack(fill="x", side="top", pady=(2, 4))
        self.progress_bar.set(0.0)

        self.progress_lbl = ctk.CTkLabel(
            prog_box,
            text="Ready. Select paths and click '⚡ Step 1: Turbo Analyze & Match'.",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8"
        )
        self.progress_lbl.pack(side="left")

        # 4. Metrics Bar (6 Cards)
        self.metrics_frame = ctk.CTkFrame(main_content, corner_radius=8, fg_color=("#F1F5F9", "#1E293B"))
        self.metrics_frame.pack(fill="x", pady=(0, 8))

        for i in range(7):
            self.metrics_frame.columnconfigure(i, weight=1)

        self.card_files = self._create_metric_card(self.metrics_frame, 0, "Input Files", "0", "#38BDF8")
        self.card_rows = self._create_metric_card(self.metrics_frame, 1, "Valid Rows", "0", "#C084FC")
        self.card_filtered_dates = self._create_metric_card(self.metrics_frame, 2, "Blank Dates Removed", "0", "#F59E0B")
        self.card_matched = self._create_metric_card(self.metrics_frame, 3, "Matched", "0 (0.0%)", "#34D399")
        self.card_unmatched = self._create_metric_card(self.metrics_frame, 4, "Unmatched (Input 1)", "0 (0.0%)", "#F87171")
        self.card_unmatched_indexes = self._create_metric_card(self.metrics_frame, 5, "Unmatched (Index File)", "0", "#E879F9")
        self.card_speed = self._create_metric_card(self.metrics_frame, 6, "Processing Speed", "0 rows/sec", "#FBBF24")

        # 5. Tabs
        self.tabview = ctk.CTkTabview(main_content, corner_radius=8)
        self.tabview.pack(fill="both", expand=True)

        self.tab_summary = self.tabview.add("📊 Month-wise Summary")
        self.tab_columns = self.tabview.add("📋 Common Columns")
        self.tab_logs = self.tabview.add("📜 Turbo Activity Log")

        self._setup_summary_tab()
        self._setup_columns_tab()
        self._setup_logs_tab()

    def _create_metric_card(self, parent, col, title, initial_val, color):
        card = ctk.CTkFrame(parent, corner_radius=6, fg_color=("#E2E8F0", "#0F172A"))
        card.grid(row=0, column=col, padx=4, pady=6, sticky="nsew")

        lbl_t = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#94A3B8")
        lbl_t.pack(anchor="w", padx=8, pady=(4, 1))

        lbl_v = ctk.CTkLabel(card, text=initial_val, font=ctk.CTkFont(size=15, weight="bold"), text_color=color)
        lbl_v.pack(anchor="w", padx=8, pady=(0, 4))
        return lbl_v

    def _setup_summary_tab(self):
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
            fg_color="#7C3AED",
            hover_color="#6D28D9"
        )
        self.btn_export_unmatched_indexes.pack(side="right", padx=(6, 0))

        self.btn_export_unmatched_separate = ctk.CTkButton(
            tb,
            text="📁 Export Each Month to Separate CSVs...",
            width=230,
            command=self._export_all_months_separate_csvs,
            state="disabled",
            fg_color="#475569",
            hover_color="#334155"
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

        # Treeview
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

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_summary.yview)
        self.tree_summary.configure(yscrollcommand=sb.set)

        self.tree_summary.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Bindings for single click on action cell, hover pointer cursor, double-click, right-click, selection
        self.tree_summary.bind("<Button-1>", self._on_summary_click)
        self.tree_summary.bind("<Motion>", self._on_summary_motion)
        self.tree_summary.bind("<Double-1>", self._on_summary_row_double_click)
        self.tree_summary.bind("<Button-3>", self._on_summary_right_click)
        self.tree_summary.bind("<<TreeviewSelect>>", self._on_summary_select)

        # Selected Month Action Bar against the table
        self.selected_month_bar = ctk.CTkFrame(self.tab_summary, corner_radius=6, fg_color=("#E2E8F0", "#0F172A"))
        self.selected_month_bar.pack(fill="x", padx=10, pady=(2, 6))

        self.lbl_selected_month_info = ctk.CTkLabel(
            self.selected_month_bar,
            text="👉 Click any month row above (or click '📥 Download CSV' in that row) to download its unmatched CSV",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94A3B8"
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

        cols = ("idx", "input1_col", "arrow", "index_col")
        self.tree_cols = ttk.Treeview(c_frame, columns=cols, show="headings", height=12)
        self.tree_cols.heading("idx", text="#")
        self.tree_cols.heading("input1_col", text="Input 1 Column Name")
        self.tree_cols.heading("arrow", text="Match")
        self.tree_cols.heading("index_col", text="Consolidated Index File Column Name")

        self.tree_cols.column("idx", width=50, anchor="center")
        self.tree_cols.column("input1_col", width=280, anchor="w")
        self.tree_cols.column("arrow", width=60, anchor="center")
        self.tree_cols.column("index_col", width=280, anchor="w")

        sb = ttk.Scrollbar(c_frame, orient="vertical", command=self.tree_cols.yview)
        self.tree_cols.configure(yscrollcommand=sb.set)

        self.tree_cols.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _setup_logs_tab(self):
        l_frame = ctk.CTkFrame(self.tab_logs, fg_color="transparent")
        l_frame.pack(fill="both", expand=True, padx=15, pady=10)

        self.log_textbox = ctk.CTkTextbox(
            l_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#090D16",
            text_color="#E2E8F0"
        )
        self.log_textbox.pack(fill="both", expand=True)

        tb_box = ctk.CTkFrame(l_frame, fg_color="transparent")
        tb_box.pack(fill="x", pady=(6, 0))

        btn_clear = ctk.CTkButton(tb_box, text="Clear Log", width=90, command=self._clear_log)
        btn_clear.pack(side="right")

    def log(self, msg: str):
        def _append():
            timestamp = time.strftime("[%H:%M:%S] ")
            self.log_textbox.insert("end", timestamp + msg + "\n")
            self.log_textbox.see("end")
        self.after(0, _append)

    def _clear_log(self):
        self.log_textbox.delete("1.0", "end")

    def set_progress(self, pct: float, status: str):
        def _update():
            self.progress_bar.set(pct)
            self.progress_lbl.configure(text=status)
        self.after(0, _update)

    def _set_ui_state(self, is_running: bool):
        st = "disabled" if is_running else "normal"
        self.btn_analyze.configure(state=st)
        self.btn_cancel.configure(state="normal" if is_running else "disabled")
        if not is_running and self.analysis_result:
            self.btn_generate.configure(state="normal")
            self.btn_export_summary.configure(state="normal")
            self.btn_export_unmatched.configure(state="normal" if self.analysis_result.has_unmatched else "disabled")
            self.btn_export_unmatched_separate.configure(state="normal" if self.analysis_result.has_unmatched else "disabled")
        else:
            self.btn_generate.configure(state="disabled")

    def _browse_input_folder(self):
        path = filedialog.askdirectory(title="Select Input Folder Containing Nested .txt Files")
        if path:
            self.input_folder_entry.delete(0, "end")
            self.input_folder_entry.insert(0, path)
            self._auto_fill_output()
            self._save_current_paths()

    def _browse_index_file(self):
        path = filedialog.askopenfilename(
            title="Select Consolidated Index File",
            filetypes=[("Tab-delimited / CSV Files", "*.txt;*.tsv;*.csv"), ("All Files", "*.*")]
        )
        if path:
            self.index_file_entry.delete(0, "end")
            self.index_file_entry.insert(0, path)
            self._save_current_paths()

    def _browse_target_index_file(self):
        path = filedialog.askopenfilename(
            title="Select Target Index List CSV (Optional)",
            filetypes=[("CSV Files", "*.csv"), ("Text Files", "*.txt;*.tsv"), ("All Files", "*.*")]
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
            auto_path = str(Path(in_path).parent / f"{Path(in_path).name}_Turbo_Indexed")
            self.output_folder_entry.delete(0, "end")
            self.output_folder_entry.insert(0, auto_path)
            self._save_current_paths()

    def _open_output_dir(self):
        out_dir = self.output_folder_entry.get().strip()
        if not out_dir or not Path(out_dir).exists():
            messagebox.showinfo("Folder Not Found", "Output folder does not exist yet or path is empty.")
            return
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
        self.engine = TurboIndexerEngine(log_callback=self.log, progress_callback=self.set_progress)

        def worker():
            try:
                res = self.engine.analyze(in_folder, index_file, target_index_file)
                self.after(0, lambda: self._on_analysis_success(res))
            except Exception as e:
                self.after(0, lambda: self._on_error("Analysis Error", str(e)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_analysis_success(self, res: TurboAnalysisResult):
        self.analysis_result = res
        self._set_ui_state(is_running=False)

        # Update Metrics Cards
        self.card_files.configure(text=f"{res.total_input1_files:,}")
        self.card_rows.configure(text=f"{res.total_input1_rows:,}")
        self.card_filtered_dates.configure(text=f"{res.total_removed_blank_date_rows:,}")
        self.card_matched.configure(text=f"{res.total_matched_rows:,} ({res.match_percentage:.1f}%)")
        self.card_unmatched.configure(text=f"{res.total_unmatched_rows:,} ({100.0 - res.match_percentage:.1f}%)")
        unmatched_idx_cnt = getattr(res, "total_unmatched_index_rows", 0)
        self.card_unmatched_indexes.configure(text=f"{unmatched_idx_cnt:,}")
        self.card_speed.configure(text=f"{res.rows_per_second:,.0f} rows/s ({res.elapsed_analysis_sec:.2f}s)")

        self.btn_export_summary.configure(state="normal")
        self.btn_export_unmatched.configure(state="normal" if res.has_unmatched else "disabled")
        self.btn_export_unmatched_separate.configure(state="normal" if res.has_unmatched else "disabled")
        self.btn_export_unmatched_indexes.configure(state="normal" if unmatched_idx_cnt > 0 else "disabled")

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
            text=f"Posting Date Column: '{res.date_col_input1 or 'None'}'   |   "
                 f"Index Column: '{res.index_col_input2}'   |   "
                 f"Matching on {len(res.common_columns_input1)} Common Column(s)"
        )

        for idx, (c1, c2) in enumerate(zip(res.common_columns_input1, res.common_columns_input2), 1):
            self.tree_cols.insert("", "end", values=(idx, c1, "<===>", c2))

        messagebox.showinfo(
            "⚡ Turbo Analysis Complete",
            f"Analyzed {res.total_input1_rows:,} records in {res.elapsed_analysis_sec:.2f} seconds!\n\n"
            f"• Processing Speed: {res.rows_per_second:,.0f} rows/sec\n"
            f"• Blank Date Rows Filtered: {res.total_removed_blank_date_rows:,}\n"
            f"• Matched: {res.total_matched_rows:,} ({res.match_percentage:.2f}%)\n"
            f"• Unmatched: {res.total_unmatched_rows:,}\n\n"
            f"Click '⚡ Step 2: Turbo Generate Indexed Files' to write the output files."
        )

    # Phase 2: Generation
    def _confirm_and_generate(self):
        if not self.analysis_result:
            messagebox.showwarning("Step 1 Required", "Please run Step 1: Turbo Analysis first.")
            return

        out_folder = self.output_folder_entry.get().strip()
        if not out_folder:
            messagebox.showerror("Missing Path", "Please select an Output Folder.")
            return

        msg = (
            f"Ready to generate indexed files using Turbo C++ streams?\n\n"
            f"• Target Output Folder: {out_folder}\n"
            f"• Total Files: {self.analysis_result.total_input1_files}\n"
            f"• Valid Records: {self.analysis_result.total_input1_rows:,}\n"
            f"• Rows sharing the same match key get the same Index (the first\n"
            f"  matching row's Index is used for all of them).\n\n"
            f"Proceed?"
        )
        if not messagebox.askyesno("Confirm Turbo Generation", msg):
            return

        self._save_current_paths()
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
        messagebox.showinfo(
            "⚡ Turbo Generation Complete",
            f"Successfully generated {count} indexed tab-delimited files in:\n{out_folder}\n\n"
            f"All nested subfolders and filenames have been preserved!"
        )

    def _cancel_task(self):
        if self.engine:
            self.engine.cancel()
            self.log("Cancellation requested by user...")
            self.progress_lbl.configure(text="Cancelling...")

    def _on_error(self, title: str, msg: str):
        self._set_ui_state(is_running=False)
        self.log(f"ERROR: {msg}")
        messagebox.showerror(title, msg)

    # Export Handlers
    def _export_summary_csv(self):
        if not self.analysis_result or self.analysis_result.month_summary_df is None:
            return
        dest = filedialog.asksaveasfilename(
            title="Save Month-wise Summary Table",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")]
        )
        if dest:
            self.analysis_result.month_summary_df.to_csv(dest, index=False)
            messagebox.showinfo("Export Success", f"Summary saved to {dest}")

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

        menu = tk.Menu(self, tearoff=0, bg="#1E293B", fg="#F8FAFC", activebackground="#0284C7", activeforeground="#FFFFFF")
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
        """Downloads unmatched CSV for the month selected in the summary table."""
        selected_items = self.tree_summary.selection()
        selected_month = None
        if selected_items:
            row_vals = self.tree_summary.item(selected_items[0], "values")
            if row_vals and not str(row_vals[0]).startswith("--- TOTAL"):
                selected_month = row_vals[0]

        if not selected_month:
            messagebox.showinfo(
                "Select a Month",
                "Please click on a specific month row in the table below to download its unmatched records."
            )
            return

        self._download_month_unmatched_by_label(selected_month)

    def _download_month_unmatched_by_label(self, month_label: str):
        if not self.analysis_result:
            return
        safe_name = month_label.replace("/", "_").replace(" ", "_").replace("(", "").replace(")", "")
        dest = filedialog.asksaveasfilename(
            title=f"Save Unmatched Records for {month_label}",
            initialfile=f"Unmatched_{safe_name}.csv",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")]
        )
        if dest:
            try:
                cnt = self.engine.export_unmatched_for_month(self.analysis_result, month_label, dest)
                if cnt > 0:
                    messagebox.showinfo("Export Complete", f"Exported {cnt:,} unmatched records for {month_label} to:\n{dest}")
                else:
                    messagebox.showinfo("No Unmatched Records", f"There are 0 unmatched records for {month_label}!")
            except Exception as e:
                messagebox.showerror("Export Failed", str(e))

    def _export_all_months_separate_csvs(self):
        if not self.analysis_result or not self.analysis_result.has_unmatched:
            messagebox.showinfo("No Data", "No unmatched records to export.")
            return

        dest_dir = filedialog.askdirectory(title="Select Folder to Save Separate CSV for Each Month")
        if not dest_dir:
            return

        dest_folder = Path(dest_dir)
        months_with_unm = [
            r["Month / Period"] for r in self.analysis_result.month_summary_data
            if r.get("_unmatched_raw", 0) > 0 and "TOTAL" not in r["Month / Period"]
        ]

        if not months_with_unm:
            messagebox.showinfo("No Unmatched Records", "No months have unmatched records.")
            return

        created = 0
        for m_lbl in months_with_unm:
            safe_name = m_lbl.replace("/", "_").replace(" ", "_").replace("(", "").replace(")", "")
            csv_path = dest_folder / f"Unmatched_{safe_name}.csv"
            cnt = self.engine.export_unmatched_for_month(self.analysis_result, m_lbl, str(csv_path))
            if cnt > 0:
                created += 1

        messagebox.showinfo(
            "Export Complete",
            f"Successfully exported separate CSVs for {created} month(s) into:\n{dest_folder}"
        )

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


def launch():
    app = TurboPBIIndexerApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
