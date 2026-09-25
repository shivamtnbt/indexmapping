"""
Turbo Indexing Engine - Blazing Fast Edition
Powered by DuckDB Vectorized Multi-Threaded C++ Engine.
Processes millions of rows in seconds using all available CPU cores.
"""

import os
import sys
import time
import shutil
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Callable
import duckdb
import pandas as pd

from turbo.date_parser import (
    get_pq_date_macros_sql,
    get_normalization_macro_sql,
    get_valid_date_filter_sql
)


def scan_txt_files(folder_path: str) -> List[Tuple[str, str]]:
    """
    Recursively scans folder_path for .txt files.
    Returns sorted list of (relative_path, absolute_path).
    Handles filenames with special characters (~, ', brackets, unicode).
    """
    root = Path(folder_path).resolve()
    if not root.exists() or not root.is_dir():
        return []

    results = []
    for p in root.rglob("*.txt"):
        if p.is_file() and not p.name.startswith("._") and not p.name.startswith(".~"):
            rel = str(p.relative_to(root))
            results.append((rel, str(p)))

    results.sort(key=lambda x: x[0].lower())
    return results


def find_date_column(columns: List[str]) -> Optional[str]:
    """Identifies the Pstng Date column from a list of column names."""
    for col in columns:
        cleaned = col.strip().lower().replace("_", " ").replace("-", " ")
        if cleaned in ("pstng date", "posting date", "pstngdate", "post date", "postingdate", "budat"):
            return col
    for col in columns:
        cleaned = col.strip().lower()
        if "pstng" in cleaned and "date" in cleaned:
            return col
    for col in columns:
        cleaned = col.strip().lower()
        if "posting" in cleaned and "date" in cleaned:
            return col
    for col in columns:
        cleaned = col.strip().lower()
        if "pstng" in cleaned:
            return col
    for col in columns:
        cleaned = col.strip().lower()
        if "date" in cleaned:
            return col
    return None


def find_index_column(columns: List[str]) -> Optional[str]:
    """Identifies the Index column in Input 2."""
    for col in columns:
        if col.strip().lower() == "index":
            return col
    for col in columns:
        if "index" in col.strip().lower():
            return col
    return None


def detect_file_encoding(path: str) -> str:
    """
    Returns 'utf-8' if the file's bytes are valid UTF-8, else 'cp1252'.

    DuckDB's read_csv(..., ignore_errors=True) does NOT raise on invalid UTF-8
    bytes -- it silently drops the offending row and moves on. SAP GUI text
    exports are commonly Windows-1252 (a stray non-breaking space, smart quote,
    trademark symbol, or accented character in a free-text field like
    Description is enough to trigger this), so without detecting and passing
    the real encoding, entire line items vanish from matching with no warning.
    """
    try:
        with open(path, "rb") as f:
            f.read().decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def is_abs_numeric_column(col_name: Optional[str]) -> bool:
    """
    Checks if a column is a quantity, net value, or subtotal/amount column
    where SAP dumps and consolidated files can differ in sign (+ vs -).
    """
    if not col_name:
        return False
    cl = col_name.strip().lower().replace("_", " ").replace("-", " ")
    return any(k in cl for k in ["quantity", "qty", "net value", "netvalue", "net val", "subtotal", "amount"])


def is_currency_amount_column(col_name: Optional[str]) -> bool:
    """
    Checks if a column is a MONETARY amount (net value, subtotal, gross sales,
    credit price...) as opposed to a quantity. The Consolidated Index File can
    carry these already converted to a reporting currency for foreign-currency
    (e.g. Export/EUR) rows via its 'Exchange Rate' column, while the raw SAP
    dump always keeps the original transaction-currency amount -- so these
    columns (and only these, not quantities) need FX-normalizing back to the
    original currency before they're used as part of the match key.
    """
    if not col_name:
        return False
    cl = col_name.strip().lower().replace("_", " ").replace("-", " ")
    return any(k in cl for k in ["net value", "netvalue", "net val", "subtotal", "gross sales", "credit price"])


class TurboAnalysisResult:
    def __init__(self):
        self.input_folder: str = ""
        self.input_index_file: str = ""
        self.output_folder: str = ""
        self.input1_files: List[Tuple[str, str]] = []
        self.common_columns_input1: List[str] = []
        self.common_columns_input2: List[str] = []
        self.date_col_input1: Optional[str] = None
        self.index_col_input2: Optional[str] = None
        
        self.total_input1_files: int = 0
        self.total_input1_rows: int = 0
        self.total_input2_rows: int = 0
        self.total_matched_rows: int = 0
        self.total_unmatched_rows: int = 0
        self.total_removed_blank_date_rows: int = 0
        self.match_percentage: float = 0.0
        self.duplicate_keys_in_input2: int = 0
        
        self.elapsed_analysis_sec: float = 0.0
        self.rows_per_second: float = 0.0
        
        self.month_summary_data: List[Dict[str, Any]] = []
        self.month_summary_df: Optional[pd.DataFrame] = None
        
        # In-memory DuckDB connection holding the state
        self.con: Optional[duckdb.DuckDBPyConnection] = None
        self.has_unmatched: bool = False
        self.total_unmatched_index_rows: int = 0
        self.has_unmatched_indexes: bool = False
        self.target_index_file: Optional[str] = None


class TurboIndexerEngine:
    def __init__(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ):
        self.log_callback = log_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda pct, status: None)
        self.is_cancelled: bool = False
        self.con: Optional[duckdb.DuckDBPyConnection] = None

    def log(self, msg: str):
        self.log_callback(msg)

    def set_progress(self, pct: float, status: str):
        self.progress_callback(pct, status)

    def cancel(self):
        self.is_cancelled = True

    def _init_db(self) -> duckdb.DuckDBPyConnection:
        """Initializes high-performance in-memory DuckDB instance."""
        con = duckdb.connect(":memory:")
        cpu_count = os.cpu_count() or 4
        con.execute(f"PRAGMA threads={cpu_count};")
        con.execute("PRAGMA enable_progress_bar=false;")
        
        # Load C++ macros
        con.execute(get_normalization_macro_sql())
        con.execute(get_pq_date_macros_sql())
        return con

    def _read_file_schema_and_detect_delim(self, file_path: str) -> Tuple[List[str], str]:
        """Detects delimiter and column headers from first few lines."""
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    first_line = f.readline()
                    if not first_line:
                        return [], "\t"
                    delim = "\t" if "\t" in first_line else ("," if "," in first_line else "\t")
                    cols = [c.strip().strip('"').strip("'") for c in first_line.rstrip("\r\n").split(delim)]
                    return cols, delim
            except UnicodeDecodeError:
                continue
        return [], "\t"

    def analyze(self, input_folder: str, input_index_file: str, target_index_file: Optional[str] = None) -> TurboAnalysisResult:
        """
        Phase 1: Blazing fast DuckDB-accelerated analysis.
        Reads 4M+ rows in 1-2 seconds using all CPU threads.
        """
        start_time = time.time()
        self.is_cancelled = False
        res = TurboAnalysisResult()
        res.input_folder = str(Path(input_folder).resolve())
        res.input_index_file = str(Path(input_index_file).resolve())
        if target_index_file and Path(target_index_file).is_file():
            res.target_index_file = str(Path(target_index_file).resolve())

        self.con = self._init_db()
        res.con = self.con

        cpu_threads = os.cpu_count() or 4
        self.log("=" * 60)
        self.log(f"⚡ TURBO ENGINE ACTIVE: Running with {cpu_threads} CPU Threads")
        self.log(f"Input Folder: {res.input_folder}")
        self.log(f"Consolidated Index File: {res.input_index_file}")

        # 1. Scan files in Input 1
        self.set_progress(0.05, "Scanning Input Folder for .txt files...")
        input1_files = scan_txt_files(res.input_folder)
        if not input1_files:
            raise ValueError(f"No .txt files found in input folder: {res.input_folder}")

        res.input1_files = input1_files
        res.total_input1_files = len(input1_files)
        self.log(f"Found {res.total_input1_files} .txt file(s) across subfolders.")

        # 2. Inspect first Input 1 file to get schema
        first_rel, first_abs = input1_files[0]
        input1_cols, input1_delim = self._read_file_schema_and_detect_delim(first_abs)
        if not input1_cols:
            raise ValueError(f"First file is empty or unreadable: {first_rel}")

        date_col = find_date_column(input1_cols)
        res.date_col_input1 = date_col
        if date_col:
            self.log(f"Identified Posting Date Column in Input 1: '{date_col}'")
        else:
            self.log("WARNING: Could not automatically detect a 'Pstng Date' column.")

        # 3. Read Consolidated Index File header and detect schema
        self.set_progress(0.12, "Inspecting Consolidated Index File schema...")
        idx_cols, idx_delim = self._read_file_schema_and_detect_delim(res.input_index_file)
        if not idx_cols:
            raise ValueError(f"Consolidated Index File is empty: {res.input_index_file}")
        idx_encoding = detect_file_encoding(res.input_index_file)
        if idx_encoding != "utf-8":
            self.log(f"Note: Consolidated Index File is not UTF-8 -- reading as {idx_encoding}.")

        index_col = find_index_column(idx_cols)
        if not index_col:
            raise ValueError(
                f"Could not find an 'Index' column in {Path(res.input_index_file).name}.\n"
                f"Available columns: {idx_cols}"
            )
        res.index_col_input2 = index_col
        self.log(f"Identified Index Column in consolidated file: '{index_col}'")

        # 4. Determine Common Columns (case-insensitive matching)
        norm_idx_map = {c.strip().lower(): c for c in idx_cols if c != index_col}
        common_cols_input1 = []
        common_cols_input2 = []
        for c1 in input1_cols:
            c1_norm = c1.strip().lower()
            if c1_norm in norm_idx_map:
                common_cols_input1.append(c1)
                common_cols_input2.append(norm_idx_map[c1_norm])

        if not common_cols_input1:
            raise ValueError(
                "No common columns found between Input 1 files and the Consolidated Index File!\n"
                f"Input 1 columns: {input1_cols}\n"
                f"Index file columns: {idx_cols}"
            )

        res.common_columns_input1 = common_cols_input1
        res.common_columns_input2 = common_cols_input2
        self.log(f"Found {len(common_cols_input1)} Common Column(s) to match:")
        for c1, c2 in zip(common_cols_input1, common_cols_input2):
            self.log(f"  • Input 1: '{c1}'  <===>  Index File: '{c2}'")

        # Detect an 'Exchange Rate' column in the Index File. For foreign-currency
        # rows (e.g. Export/EUR), the Index File's monetary columns (Net value,
        # Subtotal 3, ...) are stored already converted to a reporting currency,
        # while the raw SAP dump always keeps the ORIGINAL transaction-currency
        # amount -- so those two will never numerically agree unless the Index
        # File's amount is divided back by its own Exchange Rate first. Domestic
        # (e.g. INR) rows have a blank Exchange Rate and are left untouched.
        exchange_rate_col = None
        for c in idx_cols:
            if c.strip().lower() in ("exchange rate", "exchangerate", "exch. rate", "fx rate"):
                exchange_rate_col = c
                break
        if exchange_rate_col and any(is_currency_amount_column(c) for c in common_cols_input2):
            self.log(
                f"Detected '{exchange_rate_col}' column in Index File -- monetary columns will be "
                f"converted back to original transaction currency (Amount / {exchange_rate_col}) "
                f"for foreign-currency rows before matching."
            )

        def clean_num_sql(col_expr: str) -> str:
            return (
                f"TRY_CAST(REPLACE(REPLACE(REPLACE(CAST({col_expr} AS VARCHAR), "
                f"chr(34), ''), chr(39), ''), ',', '') AS DOUBLE)"
            )

        def fx_adjusted_expr(c: str) -> str:
            """Raw SQL expression for column `c`, converted back to original
            transaction currency when it's a monetary column and the row has a
            real Exchange Rate; otherwise just the column itself."""
            if exchange_rate_col and is_currency_amount_column(c):
                amt = clean_num_sql(f'"{c}"')
                fx = clean_num_sql(f'"{exchange_rate_col}"')
                # ROUND to currency precision -- plain division leaves floating-point
                # noise (e.g. 118010.12 / 90.7365327736521 = 1300.5800022619726)
                # that would never string-match the source's clean '1300.58'.
                return (
                    f"CASE WHEN {fx} IS NOT NULL AND {fx} NOT IN (0, 1) AND {amt} IS NOT NULL "
                    f'THEN CAST(ROUND({amt} / {fx}, 2) AS VARCHAR) ELSE "{c}" END'
                )
            return f'"{c}"'

        def idx_key_select(c: str, i: int) -> str:
            fn = "norm_abs_v" if is_abs_numeric_column(c) else "norm_v"
            return f'{fn}({fx_adjusted_expr(c)}) AS k_{i}'

        # 5. Build in-memory lookup index in DuckDB C++
        self.set_progress(0.20, "Loading Consolidated Index File into C++ Multi-Threaded Hash Table...")
        t_idx_start = time.time()

        # Check for fallback original columns (e.g. BilledQtyO for Billed Quantity, NetvalueO for Net value)
        from core.indexer_engine import find_fallback_original_columns
        fallback_map = find_fallback_original_columns(idx_cols)
        fallback_cols_info = []
        for c2 in common_cols_input2:
            if c2 in fallback_map:
                fallback_cols_info.append(f"'{c2}' -> '{fallback_map[c2]}'")
        if fallback_cols_info:
            self.log(f"Detected Original Fallback Column(s) for zeroed rows: {', '.join(fallback_cols_info)}")

        # Build column selection expressions (Option 1: norm_abs_v for quantity and amount
        # columns; monetary columns also get FX-normalized back to original currency -- see
        # idx_key_select above)
        key_selects = [idx_key_select(c, i) for i, c in enumerate(common_cols_input2)]
        partition_keys = [f'k_{i}' for i in range(len(common_cols_input2))]
        part_str = ", ".join(partition_keys)

        # Create table from Index File
        # Check if file can be read directly by DuckDB C++ reader
        is_csv_direct = True
        try:
            self.con.execute(f"""
                CREATE TABLE raw_index AS 
                SELECT {", ".join(key_selects)}, "{index_col}" AS mapped_index
                FROM read_csv(?, delim=?, all_varchar=True, auto_detect=True, header=True, ignore_errors=True, encoding='{idx_encoding}');
            """, [res.input_index_file, idx_delim])
        except Exception:
            # Fallback to pandas with multi-encoding
            is_csv_direct = False
            df_idx = pd.read_csv(res.input_index_file, sep=idx_delim, dtype=str, encoding="cp1252", low_memory=False)
            self.con.register("df_idx_pandas", df_idx)
            self.con.execute(f"""
                CREATE TABLE raw_index AS 
                SELECT {", ".join(key_selects)}, "{index_col}" AS mapped_index
                FROM df_idx_pandas;
            """)

        total_idx_rows = self.con.execute("SELECT COUNT(*) FROM raw_index").fetchone()[0]
        res.total_input2_rows = total_idx_rows

        # Index fallback keys if any fallback column exists
        fallback_added = 0
        if fallback_cols_info:
            fb_key_selects = []
            where_conditions = []
            for i, c in enumerate(common_cols_input2):
                norm_fn = "norm_abs_v" if is_abs_numeric_column(c) else "norm_v"
                c_expr = fx_adjusted_expr(c)
                if c in fallback_map:
                    fb_col = fallback_map[c]
                    fb_fn = "norm_abs_v" if is_abs_numeric_column(fb_col) else "norm_v"
                    fb_expr = fx_adjusted_expr(fb_col) if is_currency_amount_column(c) else f'"{fb_col}"'
                    fb_key_selects.append(
                        f'CASE WHEN {norm_fn}({c_expr}) IN (\'0\', \'\') AND {fb_fn}({fb_expr}) NOT IN (\'0\', \'\') '
                        f'THEN {fb_fn}({fb_expr}) ELSE {norm_fn}({c_expr}) END AS k_{i}'
                    )
                    where_conditions.append(
                        f'({norm_fn}({c_expr}) IN (\'0\', \'\') AND {fb_fn}({fb_expr}) NOT IN (\'0\', \'\'))'
                    )
                else:
                    fb_key_selects.append(f'{norm_fn}({c_expr}) AS k_{i}')

            if where_conditions:
                fb_where = " OR ".join(where_conditions)
                try:
                    if is_csv_direct:
                        self.con.execute(f"""
                            INSERT INTO raw_index
                            SELECT {", ".join(fb_key_selects)}, "{index_col}" AS mapped_index
                            FROM read_csv(?, delim=?, all_varchar=True, auto_detect=True, header=True, ignore_errors=True, encoding='{idx_encoding}')
                            WHERE {fb_where};
                        """, [res.input_index_file, idx_delim])
                    else:
                        self.con.execute(f"""
                            INSERT INTO raw_index
                            SELECT {", ".join(fb_key_selects)}, "{index_col}" AS mapped_index
                            FROM df_idx_pandas
                            WHERE {fb_where};
                        """)
                    count_after = self.con.execute("SELECT COUNT(*) FROM raw_index").fetchone()[0]
                    fallback_added = count_after - total_idx_rows
                    if fallback_added > 0:
                        self.log(f"Indexed {fallback_added:,} fallback keys for zeroed/MatTypeConsider rows.")
                except Exception as ex:
                    self.log(f"Warning: Fallback key indexing encountered error: {ex}")

        if not is_csv_direct:
            try:
                self.con.unregister("df_idx_pandas")
            except Exception:
                pass

        # Retain first occurrence for duplicate keys in Input 2
        self.con.execute(f"""
            CREATE TABLE index_lookup AS
            SELECT {", ".join(partition_keys)}, mapped_index
            FROM raw_index
            QUALIFY ROW_NUMBER() OVER (PARTITION BY {part_str} ORDER BY rowid) = 1;
        """)

        unique_idx_keys = self.con.execute("SELECT COUNT(*) FROM index_lookup").fetchone()[0]
        dup_keys = total_idx_rows - unique_idx_keys
        res.duplicate_keys_in_input2 = dup_keys

        t_idx_sec = time.time() - t_idx_start
        self.log(f"⚡ In-Memory Index Hash Table built in {t_idx_sec:.2f}s ({total_idx_rows:,} rows -> {unique_idx_keys:,} unique keys).")
        if dup_keys > 0:
            self.log(f"Note: Found {dup_keys:,} duplicate composite keys in Index File. First occurrence retained.")

        # Create master table for unmatched records
        self.con.execute("""
            CREATE TABLE master_unmatched (
                "File" VARCHAR,
                "Line_Number" BIGINT,
                "Month" VARCHAR,
                "_month_sort" VARCHAR,
                data_json VARCHAR
            );
        """)

        # Create temporary table to track matched index values from Input 2
        self.con.execute("""
            CREATE TEMP TABLE IF NOT EXISTS matched_index_ids (
                idx_val VARCHAR
            );
        """)

        # Create temporary table to track matched composite KEYS (not just one
        # representative Index value per key) so that when several Index-file
        # rows share the same composite key (true duplicate rows), every one
        # of their Index numbers is treated as matched -- not just the first.
        key_col_defs = ", ".join(f"k_{i} VARCHAR" for i in range(len(common_cols_input1)))
        self.con.execute(f"""
            CREATE TEMP TABLE IF NOT EXISTS matched_keys (
                {key_col_defs}
            );
        """)

        # 6. Process Input 1 Files
        self.set_progress(0.40, "Reconciling files and compiling month-wise summary...")
        month_summary_map: Dict[str, Dict[str, Any]] = {}
        total_valid_rows = 0
        total_matched_rows = 0
        total_unmatched_rows = 0
        total_dropped_date_rows = 0

        # Construct key matching join condition
        join_conditions = [f"c.k_{i} = l.k_{i}" for i in range(len(common_cols_input1))]
        join_cond_str = " AND ".join(join_conditions)
        key_cols_str = ", ".join(f"k_{i}" for i in range(len(common_cols_input1)))

        # File loop
        num_files = len(input1_files)
        for f_idx, (rel_path, abs_path) in enumerate(input1_files):
            if self.is_cancelled:
                raise InterruptedError("Analysis cancelled by user.")

            progress_val = 0.40 + (0.50 * (f_idx / num_files))
            self.set_progress(progress_val, f"⚡ Reconciling [{f_idx + 1}/{num_files}]: {Path(rel_path).name}")

            # Inspect columns of current file
            c_cols, c_delim = self._read_file_schema_and_detect_delim(abs_path)
            if not c_cols:
                continue

            curr_encoding = detect_file_encoding(abs_path)
            if curr_encoding != "utf-8":
                self.log(f"Note: '{Path(rel_path).name}' is not UTF-8 -- reading as {curr_encoding}.")

            curr_cols_map = {c.strip().lower(): c for c in c_cols}
            file_match_cols = [curr_cols_map.get(c1.strip().lower()) for c1 in common_cols_input1]
            missing_cols = [c1 for c1, c in zip(common_cols_input1, file_match_cols) if c is None]
            if missing_cols:
                # This file's header doesn't have every column the reference schema has
                # (e.g. an "additional"/manually-exported file with fewer columns). Don't
                # drop the whole file -- treat the missing column(s) as blank for this file,
                # same as the classic engine does, so its rows still get a chance to match.
                self.log(
                    f"Note: '{Path(rel_path).name}' is missing column(s) {missing_cols} "
                    f"(present in the reference schema) -- treating as blank for matching."
                )

            # Detect posting date col for current file
            curr_date_col = None
            if date_col and date_col.strip().lower() in curr_cols_map:
                curr_date_col = curr_cols_map[date_col.strip().lower()]
            else:
                curr_date_col = find_date_column(c_cols)

            date_filter_clause = get_valid_date_filter_sql(curr_date_col) if curr_date_col else "1=1"
            date_col_sql = f'"{curr_date_col}"' if curr_date_col else "NULL"

            # Prepare key normalization expressions for current file (Option 1: norm_abs_v for quantity/amounts)
            curr_key_selects = [
                (f"'' AS k_{i}" if c is None else
                 f'{"norm_abs_v" if is_abs_numeric_column(c) else "norm_v"}("{c}") AS k_{i}')
                for i, c in enumerate(file_match_cols)
            ]

            # Load current file into temporary DuckDB table
            try:
                self.con.execute("DROP TABLE IF EXISTS raw_curr;")
                self.con.execute(f"""
                    CREATE TEMP TABLE raw_curr AS
                    SELECT *, rowid AS _orig_row_id
                    FROM read_csv(?, delim=?, all_varchar=True, auto_detect=True, header=True, ignore_errors=True, encoding='{curr_encoding}');
                """, [abs_path, c_delim])
            except Exception:
                df_curr = pd.read_csv(abs_path, sep=c_delim, dtype=str, encoding="cp1252", low_memory=False)
                df_curr["_orig_row_id"] = range(len(df_curr))
                self.con.register("df_curr_pandas", df_curr)
                self.con.execute("DROP TABLE IF EXISTS raw_curr;")
                self.con.execute("CREATE TEMP TABLE raw_curr AS SELECT * FROM df_curr_pandas;")
                self.con.unregister("df_curr_pandas")

            total_file_rows = self.con.execute("SELECT COUNT(*) FROM raw_curr").fetchone()[0]

            # Filter out blank/null/0 date rows
            self.con.execute("DROP TABLE IF EXISTS valid_curr;")
            self.con.execute(f"""
                CREATE TEMP TABLE valid_curr AS 
                SELECT 
                    _orig_row_id,
                    {", ".join(curr_key_selects)},
                    {date_col_sql} AS _d_val
                FROM raw_curr
                WHERE {date_filter_clause};
            """)

            valid_file_rows = self.con.execute("SELECT COUNT(*) FROM valid_curr").fetchone()[0]
            dropped_in_file = total_file_rows - valid_file_rows
            total_dropped_date_rows += dropped_in_file
            total_valid_rows += valid_file_rows

            if valid_file_rows == 0:
                continue

            # Join with lookup table and aggregate month breakdown in C++
            self.con.execute("DROP TABLE IF EXISTS joined_curr;")
            self.con.execute(f"""
                CREATE TEMP TABLE joined_curr AS
                SELECT
                    c._orig_row_id,
                    pq_month_key(c._d_val) AS _m_key,
                    pq_month_label(c._d_val) AS _m_lbl,
                    l.mapped_index,
                    {", ".join(f"c.k_{i}" for i in range(len(common_cols_input1)))}
                FROM valid_curr c
                LEFT JOIN index_lookup l
                  ON {join_cond_str};
            """)

            # Track matched index IDs from this file
            self.con.execute("""
                INSERT INTO matched_index_ids
                SELECT DISTINCT mapped_index
                FROM joined_curr
                WHERE mapped_index IS NOT NULL;
            """)

            # Track matched composite KEYS from this file (covers every Index
            # value that shares a matched key, not just the retained first one)
            self.con.execute(f"""
                INSERT INTO matched_keys
                SELECT DISTINCT {key_cols_str}
                FROM joined_curr
                WHERE mapped_index IS NOT NULL;
            """)

            # Get month stats for current file
            f_stats = self.con.execute("""
                SELECT 
                    _m_key,
                    _m_lbl,
                    COUNT(*) AS total,
                    COUNT(mapped_index) AS matched,
                    COUNT(*) - COUNT(mapped_index) AS unmatched
                FROM joined_curr
                GROUP BY _m_key, _m_lbl;
            """).fetchall()

            for m_key, m_lbl, tot, m_cnt, u_cnt in f_stats:
                if m_key not in month_summary_map:
                    month_summary_map[m_key] = {
                        "sort_key": m_key,
                        "month_label": m_lbl,
                        "total": 0,
                        "matched": 0,
                        "unmatched": 0
                    }
                month_summary_map[m_key]["total"] += tot
                month_summary_map[m_key]["matched"] += m_cnt
                month_summary_map[m_key]["unmatched"] += u_cnt
                total_matched_rows += m_cnt
                total_unmatched_rows += u_cnt

            # Store unmatched indices for fast month-wise download
            unmatched_in_file = self.con.execute("SELECT COUNT(*) FROM joined_curr WHERE mapped_index IS NULL").fetchone()[0]
            if unmatched_in_file > 0:
                res.has_unmatched = True
                # Insert unmatched rows into master_unmatched table
                self.con.execute(f"""
                    INSERT INTO master_unmatched
                    SELECT 
                        ? AS "File",
                        (j._orig_row_id + 2) AS "Line_Number",
                        j._m_lbl AS "Month",
                        j._m_key AS "_month_sort",
                        to_json(r) AS data_json
                    FROM joined_curr j
                    JOIN raw_curr r ON j._orig_row_id = r._orig_row_id
                    WHERE j.mapped_index IS NULL;
                """, [rel_path])

        # Drop temporary tables
        self.con.execute("DROP TABLE IF EXISTS raw_curr;")
        self.con.execute("DROP TABLE IF EXISTS valid_curr;")
        self.con.execute("DROP TABLE IF EXISTS joined_curr;")

        # Identify rows in Consolidated Index File (or Target Index CSV) that were NOT matched by Input 1.
        # Expand matched_keys back against the FULL raw_index (not just the deduped
        # first-occurrence index_lookup) so that when several Index-file rows are
        # true duplicates (identical on every common column), every one of their
        # Index numbers is counted as matched -- not only the first row's.
        key_join_cond = " AND ".join(f"r.k_{i} = mk.k_{i}" for i in range(len(common_cols_input1)))
        self.con.execute("DROP TABLE IF EXISTS distinct_matched_indexes;")
        self.con.execute(f"""
            CREATE TABLE distinct_matched_indexes AS
            SELECT DISTINCT r.mapped_index AS idx_val
            FROM raw_index r
            JOIN matched_keys mk ON {key_join_cond}
            WHERE r.mapped_index IS NOT NULL AND r.mapped_index != ''
            UNION
            SELECT DISTINCT idx_val
            FROM matched_index_ids
            WHERE idx_val IS NOT NULL AND idx_val != '';
        """)

        self.con.execute("DROP TABLE IF EXISTS unmatched_index_records;")
        if res.target_index_file and Path(res.target_index_file).is_file():
            df_tgt = pd.read_csv(res.target_index_file, dtype=str, low_memory=False)
            tgt_col = find_index_column(list(df_tgt.columns)) or df_tgt.columns[0]
            df_tgt_clean = pd.DataFrame({index_col: df_tgt[tgt_col].fillna("").astype(str).str.strip()})
            self.con.register("df_target_pandas", df_tgt_clean)
            self.con.execute(f"""
                CREATE TABLE unmatched_index_records AS
                SELECT "{index_col}"
                FROM df_target_pandas
                WHERE "{index_col}" NOT IN (SELECT idx_val FROM distinct_matched_indexes)
                  AND "{index_col}" != '';
            """)
            try:
                self.con.unregister("df_target_pandas")
            except Exception:
                pass
        elif is_csv_direct:
            self.con.execute(f"""
                CREATE TABLE unmatched_index_records AS
                SELECT *
                FROM read_csv(?, delim=?, all_varchar=True, auto_detect=True, header=True, ignore_errors=True, encoding='{idx_encoding}')
                WHERE "{index_col}" NOT IN (SELECT idx_val FROM distinct_matched_indexes);
            """, [res.input_index_file, idx_delim])
        else:
            self.con.execute(f"""
                CREATE TABLE unmatched_index_records AS
                SELECT *
                FROM df_idx_pandas
                WHERE "{index_col}" NOT IN (SELECT idx_val FROM distinct_matched_indexes);
            """)

        unmatched_idx_cnt = self.con.execute("SELECT COUNT(*) FROM unmatched_index_records;").fetchone()[0]
        res.total_unmatched_index_rows = unmatched_idx_cnt
        res.has_unmatched_indexes = (unmatched_idx_cnt > 0)

        elapsed = time.time() - start_time
        res.elapsed_analysis_sec = elapsed
        res.total_input1_rows = total_valid_rows
        res.total_matched_rows = total_matched_rows
        res.total_unmatched_rows = total_unmatched_rows
        res.total_removed_blank_date_rows = total_dropped_date_rows
        res.match_percentage = (total_matched_rows / total_valid_rows * 100.0) if total_valid_rows > 0 else 0.0
        res.rows_per_second = (total_valid_rows / elapsed) if elapsed > 0 else 0.0

        # Build Month Summary Table
        sorted_keys = sorted(month_summary_map.keys())
        summary_rows = []
        for k in sorted_keys:
            st = month_summary_map[k]
            tot = st["total"]
            m_pct = (st["matched"] / tot * 100.0) if tot > 0 else 0.0
            summary_rows.append({
                "Month / Period": st["month_label"],
                "Total Records": tot,
                "Matched Records": st["matched"],
                "Unmatched Records": st["unmatched"],
                "Match %": f"{m_pct:.2f}%",
                "_sort_key": st["sort_key"],
                "_matched_raw": st["matched"],
                "_unmatched_raw": st["unmatched"],
                "_total_raw": tot,
            })

        res.month_summary_data = summary_rows
        res.month_summary_df = pd.DataFrame(summary_rows)

        self.set_progress(1.0, f"⚡ Turbo Analysis Completed in {elapsed:.2f}s!")
        self.log("=" * 60)
        self.log(f"⚡ TURBO RECO FINISHED in {elapsed:.2f} seconds ({res.rows_per_second:,.0f} rows/sec):")
        self.log(f"  • Total Input 1 Files: {res.total_input1_files}")
        if res.total_removed_blank_date_rows > 0:
            self.log(f"  • Filtered out {res.total_removed_blank_date_rows:,} row(s) with blank/null/0 Posting Date before matching.")
        self.log(f"  • Total Valid Rows: {res.total_input1_rows:,}")
        self.log(f"  • Total Matched: {res.total_matched_rows:,} ({res.match_percentage:.2f}%)")
        self.log(f"  • Total Unmatched in Input 1: {res.total_unmatched_rows:,} ({100.0 - res.match_percentage:.2f}%)")
        self.log(f"  • Total Unmatched in Index File (not found in Input 1): {res.total_unmatched_index_rows:,}")
        self.log("=" * 60)

        return res

    def export_unmatched_indexes_csv(self, analysis_result: TurboAnalysisResult, export_path: str) -> int:
        """
        Exports only the not found Index numbers from the Consolidated Index File (Input 2)
        that were NEVER matched by any record in Input 1 via high-speed DuckDB COPY stream.
        """
        con = analysis_result.con
        if con is None:
            raise ValueError("DuckDB session is closed. Please re-run Step 1 Analysis.")
        
        out_path = Path(export_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        cnt = con.execute("SELECT COUNT(*) FROM unmatched_index_records").fetchone()[0]
        if cnt == 0:
            out_path.write_text("", encoding="utf-8")
            return 0
        
        index_col = analysis_result.index_col_input2 or "Index"
        sql_path = str(out_path).replace("'", "''")
        con.execute(f"COPY (SELECT TRIM(\"{index_col}\") FROM unmatched_index_records) TO '{sql_path}' (HEADER FALSE, DELIMITER ',');")
        return cnt

    def generate_indexed_files(self, analysis_result: TurboAnalysisResult, output_folder: str) -> int:
        """
        Phase 2: Ultra-fast generation using DuckDB C++ COPY streams.
        Writes all output files with matching Index column repeated for duplicate line items,
        preserving nested subfolder hierarchy.
        """
        start_time = time.time()
        self.is_cancelled = False
        out_root = Path(output_folder).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        analysis_result.output_folder = str(out_root)

        con = analysis_result.con
        if con is None:
            raise ValueError("DuckDB session is closed. Please re-run Step 1 Analysis.")

        common_cols_input1 = analysis_result.common_columns_input1
        input1_files = analysis_result.input1_files
        date_col = analysis_result.date_col_input1

        join_conditions = [f"c.k_{i} = l.k_{i}" for i in range(len(common_cols_input1))]
        join_cond_str = " AND ".join(join_conditions)

        total_files = len(input1_files)
        files_written = 0

        self.log(f"⚡ Starting Turbo Generation into: {out_root}")

        for f_idx, (rel_path, abs_path) in enumerate(input1_files):
            if self.is_cancelled:
                raise InterruptedError("Generation cancelled by user.")

            progress_val = (f_idx / total_files)
            self.set_progress(progress_val, f"⚡ Writing [{f_idx + 1}/{total_files}]: {Path(rel_path).name}")

            dest_file = out_root / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            c_cols, c_delim = self._read_file_schema_and_detect_delim(abs_path)
            if not c_cols:
                continue

            curr_encoding = detect_file_encoding(abs_path)

            curr_cols_map = {c.strip().lower(): c for c in c_cols}
            file_match_cols = [curr_cols_map.get(c1.strip().lower()) for c1 in common_cols_input1]

            curr_date_col = None
            if date_col and date_col.strip().lower() in curr_cols_map:
                curr_date_col = curr_cols_map[date_col.strip().lower()]
            else:
                curr_date_col = find_date_column(c_cols)

            date_filter_clause = get_valid_date_filter_sql(curr_date_col) if curr_date_col else "1=1"

            # Option 1: norm_abs_v for quantity and amount columns.
            # A column missing from this file's header (vs. the reference schema) is
            # treated as blank rather than referencing a non-existent column -- keeps this
            # in sync with the matching phase in analyze() so Step 2 doesn't drop/crash on
            # files with fewer columns than the reference file.
            curr_key_selects = [
                ("'' AS k_{}".format(i) if c is None else
                 f'{"norm_abs_v" if is_abs_numeric_column(c) else "norm_v"}("{c}") AS k_{i}')
                for i, c in enumerate(file_match_cols)
            ]

            # Load file in DuckDB
            try:
                con.execute("DROP TABLE IF EXISTS raw_file_out;")
                con.execute(f"""
                    CREATE TEMP TABLE raw_file_out AS
                    SELECT *, rowid AS _orig_row_id
                    FROM read_csv(?, delim=?, all_varchar=True, auto_detect=True, header=True, ignore_errors=True, encoding='{curr_encoding}');
                """, [abs_path, c_delim])
            except Exception:
                df_curr = pd.read_csv(abs_path, sep=c_delim, dtype=str, encoding="cp1252", low_memory=False)
                df_curr["_orig_row_id"] = range(len(df_curr))
                con.register("df_curr_pandas", df_curr)
                con.execute("DROP TABLE IF EXISTS raw_file_out;")
                con.execute("CREATE TEMP TABLE raw_file_out AS SELECT * FROM df_curr_pandas;")
                con.unregister("df_curr_pandas")

            # Filter blank dates and prepare join keys
            k_cols_list = [f"k_{i}" for i in range(len(common_cols_input1))]
            con.execute("DROP TABLE IF EXISTS valid_file_out;")
            con.execute(f"""
                CREATE TEMP TABLE valid_file_out AS 
                SELECT 
                    *,
                    {", ".join(curr_key_selects)}
                FROM raw_file_out
                WHERE {date_filter_clause};
            """)

            # Join with index_lookup to attach Index column
            con.execute("DROP TABLE IF EXISTS file_joined_out;")
            con.execute(f"""
                CREATE TEMP TABLE file_joined_out AS 
                SELECT 
                    r.* EXCLUDE (_orig_row_id, {", ".join(k_cols_list)}),
                    COALESCE(l.mapped_index, '') AS "Index"
                FROM valid_file_out r
                LEFT JOIN index_lookup l
                  ON {join_cond_str.replace('c.', 'r.')}
                ORDER BY r._orig_row_id;
            """)

            # Direct C++ streaming output to tab-separated text file (escape single quotes for SQL)
            dest_str = str(dest_file).replace("\\", "/").replace("'", "''")
            con.execute(f"""
                COPY file_joined_out TO '{dest_str}' (HEADER, DELIMITER '\t');
            """)
            files_written += 1

        con.execute("DROP TABLE IF EXISTS raw_file_out;")
        con.execute("DROP TABLE IF EXISTS file_joined_out;")

        elapsed = time.time() - start_time
        self.set_progress(1.0, f"⚡ Successfully generated {files_written} indexed files in {elapsed:.2f}s!")
        self.log(f"⚡ Phase 2 Turbo Complete: {files_written} files written in {elapsed:.2f}s!")
        return files_written

    def export_unmatched_for_month(
        self,
        analysis_result: TurboAnalysisResult,
        month_label: str,
        dest_csv_path: str
    ) -> int:
        """Exports unmatched records for a specific month to CSV."""
        con = analysis_result.con
        if con is None:
            raise ValueError("DuckDB session is closed.")

        dest_str = str(Path(dest_csv_path).resolve()).replace("\\", "/")
        
        # Extract json data into tabular format
        con.execute("""
            CREATE TEMP TABLE temp_unm_export AS 
            SELECT 
                "File",
                "Line_Number",
                "Month",
                json_extract_string(data_json, '$.*')
            FROM master_unmatched
            WHERE "Month" = ?;
        """, [month_label])

        # Simpler and robust: fetch from master_unmatched and convert to dataframe
        res = con.execute("""
            SELECT "File", "Line_Number", "Month", data_json 
            FROM master_unmatched 
            WHERE "Month" = ?
            ORDER BY "File", "Line_Number";
        """, [month_label]).fetchall()

        if not res:
            return 0

        import json
        rows = []
        for r_file, r_line, r_month, r_json in res:
            d = json.loads(r_json)
            # Remove internal row id if present
            d.pop("_orig_row_id", None)
            row_dict = {"File": r_file, "Line_Number": r_line, "Month": r_month, **d}
            rows.append(row_dict)

        df_out = pd.DataFrame(rows)
        df_out.to_csv(dest_csv_path, index=False)
        return len(df_out)
