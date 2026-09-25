"""
Indexer Engine:
High-performance vectorized two-phase workflow:
Phase 1: Consolidate metadata, detect common columns, cached Power Query date conversion,
         vectorized matching against Input 2, and generating month-wise summary in seconds.
Phase 2: Replicating folder hierarchy and generating updated tab-delimited files with the Index column added.
"""

import os
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Callable
import numpy as np
import pandas as pd

from .date_parser import parse_pstng_date, get_month_key_and_label
from .file_handler import scan_txt_files, read_tab_delimited_file, write_tab_delimited_file


def is_abs_numeric_column(col_name: Optional[str]) -> bool:
    """
    Checks if a column is a quantity, net value, or subtotal/amount column
    where SAP dumps and consolidated files can differ in sign (+ vs -).
    """
    if not col_name:
        return False
    cl = col_name.strip().lower().replace("_", " ").replace("-", " ")
    return any(k in cl for k in ["quantity", "qty", "net value", "netvalue", "net val", "subtotal", "amount"])


def normalize_val(v: Any, is_abs: bool = False) -> str:
    """
    Normalizes a single cell value for case-insensitive, quote-stripped, and numeric-tolerant matching.
    """
    if v is None:
        return ""
    s = str(v).strip().strip('"').strip("'")
    if not s or s.lower() in ("nan", "nat", "none", "null", "<na>", "#n/a"):
        return ""
    
    # Check numeric with commas (e.g., '3,628.57' or '1,000')
    s_no_comma = s.replace(",", "")
    try:
        f = float(s_no_comma)
        if is_abs:
            f = abs(f)
        if f.is_integer() and "." in s_no_comma:
            return str(int(f))
        elif "." in s_no_comma:
            # Strip trailing zeros e.g. 15.50 -> 15.5
            cleaned = s_no_comma.rstrip("0").rstrip(".")
            if is_abs and (cleaned.startswith("-") or cleaned.startswith("+")):
                cleaned = cleaned.lstrip("+-")
            return cleaned.lower()
        res_str = str(int(f)) if f.is_integer() else str(f).lower()
        if is_abs and (res_str.startswith("-") or res_str.startswith("+")):
            res_str = res_str.lstrip("+-")
        return res_str
    except (ValueError, OverflowError):
        pass

    return s.lower()


def prepare_normalized_column_arrays(df: pd.DataFrame, col_names: List[Optional[str]]) -> List[np.ndarray]:
    """
    High-performance vectorized normalization for matching columns.
    1. Strips quotes and whitespace, converts to lowercase.
    2. Removes thousands commas in numeric fields (e.g. '3,628.57' -> '3628.57').
    3. Normalizes trailing zeros in decimal numbers (e.g. '1.00' -> '1', '15.50' -> '15.5').
    4. Handles Option 1: Absolute value matching for quantity & amount columns (e.g. '1.00' vs '-1').
    5. Preserves non-numeric strings with commas and leading zeros (e.g. '0050').
    Runs in milliseconds on millions of rows.
    """
    prepared = []
    num_rows = len(df)
    for c in col_names:
        if c is not None and c in df.columns:
            s = df[c].fillna("").astype(str)

            # Drop the Unicode replacement character (from an upstream export that
            # misread CP1252 bytes as UTF-8 and lost the original character) --
            # it can stand for ANY lost character (space, apostrophe, dash...),
            # so it's dropped entirely, same as quotes/apostrophes are stripped
            # below, rather than guessed as a space. Non-breaking space is
            # dropped the same way for consistency. Lookalike punctuation (curly
            # quotes, en/em dashes -- common when SAP text gets pasted through
            # Excel) is folded to its plain equivalent so two otherwise-identical
            # values don't fail to match purely over which mangled character
            # ended up on which side.
            s = s.str.replace("[� ]+", "", regex=True)
            s = s.str.replace("[‘’]", "'", regex=True)
            s = s.str.replace("[“”]", '"', regex=True)
            s = s.str.replace("[–—]", "-", regex=True)

            s = s.str.strip().str.strip('"').str.strip("'").str.lower()

            # Map literal 'nan', 'null', 'none', 'nat' to empty string
            s = s.replace(["nan", "null", "none", "nat", "<na>", "#n/a"], "")

            # Check numeric with commas
            s_no_comma = s.str.replace(",", "", regex=False)
            is_num = s_no_comma.str.match(r"^[+-]?\d+(\.\d+)?$")
            
            # Clean trailing zeros on decimal numbers (1.00 -> 1, 0.00 -> 0, 15.50 -> 15.5)
            cleaned_num = s_no_comma.str.replace(r"\.0+$", "", regex=True)
            cleaned_num = cleaned_num.str.replace(r"(\.\d*?[1-9])0+$", r"\1", regex=True)
            
            # Option 1: Absolute value matching for quantity & net value columns
            if is_abs_numeric_column(c):
                cleaned_num = cleaned_num.str.lstrip("+-")
            
            final_s = s.where(~is_num, cleaned_num)
            prepared.append(final_s.values)
        else:
            prepared.append(np.full(num_rows, "", dtype=object))
    return prepared


def find_date_column(columns: List[str]) -> Optional[str]:
    """
    Finds the Pstng Date column from a list of column names (case-insensitive).
    """
    # 1. Exact priority matches
    for col in columns:
        cleaned = col.strip().lower().replace("_", " ").replace("-", " ")
        if cleaned in ("pstng date", "posting date", "pstngdate", "post date", "postingdate", "budat"):
            return col

    # 2. Substring matches
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

    # Fallback: any column with "date"
    for col in columns:
        cleaned = col.strip().lower()
        if "date" in cleaned:
            return col

    return None


def find_index_column(columns: List[str]) -> Optional[str]:
    """
    Identifies the Index column in Input 2 (case-insensitive).
    """
    for col in columns:
        if col.strip().lower() == "index":
            return col
    for col in columns:
        if "index" in col.strip().lower():
            return col
    return None


def find_fallback_original_columns(idx_cols: List[str]) -> Dict[str, str]:
    """
    Finds fallback original columns (e.g. BilledQtyO for Billed Quantity, NetvalueO for Net value).
    When Power BI models have zeroed-out values (e.g. MatTypeConsider = False), 
    the raw original numbers are preserved in the '...O' columns.
    """
    fallback_map: Dict[str, str] = {}
    idx_cols_lower_map = {c.strip().lower(): c for c in idx_cols}
    for c in idx_cols:
        c_norm = c.strip().lower()
        candidates = [
            c_norm + "o",
            c_norm.replace(" ", "") + "o",
            c_norm.replace("quantity", "qty").replace(" ", "") + "o",
            c_norm.replace("value", "val").replace(" ", "") + "o",
        ]
        if c_norm in ("billed quantity", "billed qty"):
            candidates.extend(["billedqtyo", "billedquantityo"])
        elif c_norm in ("net value", "net val"):
            candidates.extend(["netvalueo", "netvalo"])
        elif c_norm in ("subtotal 1", "subtotal1"):
            candidates.extend(["subtotal1o"])

        for cand in candidates:
            if cand in idx_cols_lower_map and idx_cols_lower_map[cand] != c:
                fallback_map[c] = idx_cols_lower_map[cand]
                break
    return fallback_map


def filter_valid_pstng_dates(df: pd.DataFrame, date_col: Optional[str]) -> Tuple[pd.DataFrame, int]:
    """
    Removes rows where Pstng Date is blank, null, '0', '0.0', '00.00.0000', etc.
    Returns (filtered_df, num_dropped_rows).
    """
    if date_col is None or date_col not in df.columns or df.empty:
        return df, 0

    s = df[date_col].fillna("").astype(str).str.strip().str.strip('"').str.strip("'")
    
    # 1. Blank / empty string
    cond_empty = (s == "")
    
    # 2. Known zero/null text markers
    cond_zeros = s.str.lower().isin([
        "0", "0.0", "0.00", "00", "nan", "null", "none", "nat", "#n/a", 
        "00-00-0000", "00/00/0000", "00.00.0000", "0000-00-00", "0000/00/00", "00000000"
    ])
    
    # 3. All zeros after removing punctuation (e.g. 00000000 or 00.00.00 or 0-0-0)
    cond_all_zero_digits = s.str.replace(r"[-/\.]", "", regex=True).str.match(r"^0+$").fillna(False)

    invalid_mask = cond_empty | cond_zeros | cond_all_zero_digits
    num_dropped = int(invalid_mask.sum())

    if num_dropped > 0:
        return df.loc[~invalid_mask].reset_index(drop=True), num_dropped
    return df, 0


class AnalysisResult:
    def __init__(self):
        self.input_folder: str = ""
        self.input_index_file: str = ""
        self.output_folder: str = ""
        self.input1_files: List[Tuple[str, str]] = []  # (rel_path, abs_path)
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
        self.month_summary_data: List[Dict[str, Any]] = []
        self.month_summary_df: Optional[pd.DataFrame] = None
        self.lookup_dict: Dict[Tuple[str, ...], str] = {}
        self.unmatched_samples: List[Dict[str, Any]] = []
        self.unmatched_df: Optional[pd.DataFrame] = None
        self.total_unmatched_index_rows: int = 0
        self.unmatched_index_df: Optional[pd.DataFrame] = None
        self.matched_index_set: Set[str] = set()
        self.target_index_file: Optional[str] = None


class IndexerEngine:
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None, progress_callback: Optional[Callable[[float, str], None]] = None):
        self.log_callback = log_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda pct, status: None)
        self.is_cancelled: bool = False

    def log(self, msg: str):
        self.log_callback(msg)

    def set_progress(self, pct: float, status: str):
        self.progress_callback(pct, status)

    def cancel(self):
        self.is_cancelled = True

    def analyze(self, input_folder: str, input_index_file: str, target_index_file: Optional[str] = None) -> AnalysisResult:
        """
        Phase 1: Consolidate metadata, detect common columns, Power Query date conversion,
        and generate month-wise matching summary.
        Vectorized for near-instant processing even on massive datasets.
        """
        self.is_cancelled = False
        res = AnalysisResult()
        res.input_folder = str(Path(input_folder).resolve())
        res.input_index_file = str(Path(input_index_file).resolve())
        if target_index_file and Path(target_index_file).is_file():
            res.target_index_file = str(Path(target_index_file).resolve())

        self.log("Starting Phase 1 Analysis...")
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

        # 2. Read Consolidated Index File (Input 2)
        self.set_progress(0.15, "Reading Consolidated Index File...")
        self.log(f"Reading consolidated index file: {Path(res.input_index_file).name}...")
        df_index, enc2 = read_tab_delimited_file(res.input_index_file)
        res.total_input2_rows = len(df_index)
        self.log(f"Loaded {res.total_input2_rows:,} rows from index file (Encoding: {enc2}).")

        # Identify Index column in Input 2
        index_col = find_index_column(list(df_index.columns))
        if not index_col:
            raise ValueError(
                f"Could not find an 'Index' column in {Path(res.input_index_file).name}. "
                f"Available columns: {list(df_index.columns)}"
            )
        res.index_col_input2 = index_col
        self.log(f"Identified Index Column in consolidated file: '{index_col}'")

        # 3. Read first file from Input 1 to determine schema
        first_rel, first_abs = input1_files[0]
        self.set_progress(0.20, f"Reading sample schema from {first_rel}...")
        df_sample, enc1 = read_tab_delimited_file(first_abs)
        input1_cols = list(df_sample.columns)
        self.log(f"Sample file '{Path(first_rel).name}' has {len(input1_cols)} columns.")

        # Find Pstng Date column in Input 1
        date_col = find_date_column(input1_cols)
        res.date_col_input1 = date_col
        if date_col:
            self.log(f"Identified Posting Date Column in Input 1: '{date_col}'")
        else:
            self.log("WARNING: Could not automatically detect a 'Pstng Date' column. Month will be marked as 'Unknown Date'.")

        # 4. Determine Common Columns (case-insensitive matching)
        norm_input2_cols: Dict[str, str] = {}
        for c in df_index.columns:
            if c != index_col:
                norm_input2_cols[c.strip().lower()] = c

        common_cols_input1 = []
        common_cols_input2 = []
        for c1 in input1_cols:
            c1_norm = c1.strip().lower()
            if c1_norm in norm_input2_cols:
                common_cols_input1.append(c1)
                common_cols_input2.append(norm_input2_cols[c1_norm])

        if not common_cols_input1:
            raise ValueError(
                "No common columns found between Input 1 files and the Consolidated Index File!\n"
                f"Input 1 columns: {input1_cols}\n"
                f"Index file columns: {list(df_index.columns)}"
            )

        res.common_columns_input1 = common_cols_input1
        res.common_columns_input2 = common_cols_input2
        self.log(f"Found {len(common_cols_input1)} Common Column(s) to match:")
        for c1, c2 in zip(common_cols_input1, common_cols_input2):
            self.log(f"  • Input 1: '{c1}'  <===>  Index File: '{c2}'")

        # 5. Build lookup dictionary from Input 2 (Vectorized)
        self.set_progress(0.25, f"Building fast lookup index for {res.total_input2_rows:,} rows...")
        self.log("Vectorizing and building in-memory lookup index...")

        # Detect fallback original columns (e.g. BilledQtyO for Billed Quantity, NetvalueO for Net value)
        fallback_map = find_fallback_original_columns(list(df_index.columns))
        fallback_cols_info = []
        for c2 in common_cols_input2:
            if c2 in fallback_map:
                fallback_cols_info.append(f"'{c2}' -> '{fallback_map[c2]}'")
        if fallback_cols_info:
            self.log(f"Detected Original Fallback Column(s) for zeroed rows: {', '.join(fallback_cols_info)}")

        # Prepare normalized arrays
        index2_col_arrays = prepare_normalized_column_arrays(df_index, common_cols_input2)
        index_vals = df_index[index_col].fillna("").astype(str).values

        # Prepare fallback normalized arrays if any fallback column exists
        fallback_arrays = []
        for i, c2 in enumerate(common_cols_input2):
            if c2 in fallback_map:
                fb_col = fallback_map[c2]
                fb_arr = prepare_normalized_column_arrays(df_index, [fb_col])[0]
                fallback_arrays.append((i, fb_arr))

        lookup: Dict[Tuple[str, ...], str] = {}
        key_to_all_indexes: Dict[Tuple[str, ...], List[str]] = {}
        dup_count = 0
        fallback_keys_indexed = 0

        # Fast zip iteration over vectorized arrays
        for r_idx, (row_tuple, idx_val) in enumerate(zip(zip(*index2_col_arrays), index_vals)):
            idx_str = str(idx_val)
            if row_tuple in lookup:
                dup_count += 1
                key_to_all_indexes[row_tuple].append(idx_str)
            else:
                lookup[row_tuple] = idx_val
                key_to_all_indexes[row_tuple] = [idx_str]

            # Fallback to original columns when primary is zero/blank and fallback is non-zero
            if fallback_arrays:
                needs_fallback = False
                alt_tuple_list = list(row_tuple)
                for col_pos, fb_arr in fallback_arrays:
                    curr_val = alt_tuple_list[col_pos]
                    fb_val = fb_arr[r_idx]
                    if curr_val in ("0", "") and fb_val not in ("0", ""):
                        alt_tuple_list[col_pos] = fb_val
                        needs_fallback = True
                if needs_fallback:
                    alt_tuple = tuple(alt_tuple_list)
                    if alt_tuple not in lookup:
                        lookup[alt_tuple] = idx_val
                        key_to_all_indexes[alt_tuple] = [idx_str]
                        fallback_keys_indexed += 1
                    else:
                        key_to_all_indexes[alt_tuple].append(idx_str)

        res.lookup_dict = lookup
        res.duplicate_keys_in_input2 = dup_count
        self.log(f"Lookup table built in seconds: {len(lookup):,} unique keys indexed.")
        if fallback_keys_indexed > 0:
            self.log(f"Indexed {fallback_keys_indexed:,} fallback keys for zeroed/MatTypeConsider rows.")
        if dup_count > 0:
            self.log(f"Note: Found {dup_count:,} duplicate composite keys in Index File. First occurrence retained.")

        # 6. Scan and Match records across all files in Input 1
        self.set_progress(0.35, "Processing files and calculating month-wise matching...")
        month_stats: Dict[str, Dict[str, Any]] = {}
        total_matched = 0
        total_unmatched = 0
        total_rows_input1 = 0
        matched_index_set: Set[str] = set()

        # Cache for parsed dates so we only parse each unique date string once
        date_cache: Dict[str, Tuple[str, str]] = {}
        unmatched_dfs: List[pd.DataFrame] = []

        for f_idx, (rel_path, abs_path) in enumerate(input1_files):
            if self.is_cancelled:
                raise InterruptedError("Analysis cancelled by user.")

            df_curr, _ = read_tab_delimited_file(abs_path)
            curr_cols_map = {c.strip().lower(): c for c in df_curr.columns}

            # Date column handling
            date_col_curr = None
            if date_col and date_col.strip().lower() in curr_cols_map:
                date_col_curr = curr_cols_map[date_col.strip().lower()]
            else:
                date_col_curr = find_date_column(list(df_curr.columns))

            # Filter out blank, null, or '0' Pstng Date rows before running reco
            df_curr, dropped_date_rows = filter_valid_pstng_dates(df_curr, date_col_curr)
            res.total_removed_blank_date_rows += dropped_date_rows

            num_rows = len(df_curr)
            total_rows_input1 += num_rows

            if num_rows == 0:
                continue

            # Map common columns for current file
            file_match_cols = [curr_cols_map.get(c1.strip().lower()) for c1 in common_cols_input1]

            # Vectorized normalized column arrays for current file
            file_col_arrays = prepare_normalized_column_arrays(df_curr, file_match_cols)

            # Pre-extract dates if available
            raw_dates = df_curr[date_col_curr].fillna("").astype(str).values if date_col_curr else None

            # Fast row matching via zip
            file_unmatched_indices = []
            for r_idx, row_key in enumerate(zip(*file_col_arrays)):
                # Ascertain Month using cached Power Query date conversion
                m_sort_key = "9999-99"
                m_label = "Unknown / Missing Date"
                if raw_dates is not None:
                    raw_d = raw_dates[r_idx]
                    if raw_d not in date_cache:
                        dt = parse_pstng_date(raw_d)
                        date_cache[raw_d] = get_month_key_and_label(dt)
                    m_sort_key, m_label = date_cache[raw_d]

                if m_sort_key not in month_stats:
                    month_stats[m_sort_key] = {
                        "sort_key": m_sort_key,
                        "month_label": m_label,
                        "total": 0,
                        "matched": 0,
                        "unmatched": 0,
                    }

                month_stats[m_sort_key]["total"] += 1

                if row_key in lookup:
                    idx_val = lookup[row_key]
                    if row_key in key_to_all_indexes:
                        matched_index_set.update(key_to_all_indexes[row_key])
                    elif idx_val:
                        matched_index_set.add(str(idx_val))
                    month_stats[m_sort_key]["matched"] += 1
                    total_matched += 1
                else:
                    month_stats[m_sort_key]["unmatched"] += 1
                    total_unmatched += 1
                    file_unmatched_indices.append(r_idx)

            # Slice and store unmatched rows for this file
            if file_unmatched_indices:
                df_unm = df_curr.iloc[file_unmatched_indices].copy()
                unm_months = []
                for i in file_unmatched_indices:
                    raw_d = raw_dates[i] if raw_dates is not None else ""
                    m_lbl = date_cache.get(raw_d, ("9999-99", "Unknown / Missing Date"))[1]
                    unm_months.append(m_lbl)

                df_unm.insert(0, "Line_Number", [i + 2 for i in file_unmatched_indices])
                df_unm.insert(0, "File", rel_path)
                df_unm.insert(0, "Month", unm_months)
                unmatched_dfs.append(df_unm)

        res.total_input1_rows = total_rows_input1
        res.total_matched_rows = total_matched
        res.total_unmatched_rows = total_unmatched
        res.match_percentage = (total_matched / total_rows_input1 * 100.0) if total_rows_input1 > 0 else 0.0

        # Combine all unmatched records into a single master DataFrame
        if unmatched_dfs:
            res.unmatched_df = pd.concat(unmatched_dfs, ignore_index=True)
            res.unmatched_samples = res.unmatched_df.head(200).to_dict(orient="records")
        else:
            res.unmatched_df = pd.DataFrame()
            res.unmatched_samples = []

        # Sort months chronologically
        sorted_keys = sorted(month_stats.keys())
        summary_rows = []
        for k in sorted_keys:
            st = month_stats[k]
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

        # Identify rows in Consolidated Index File (or Target Index CSV) that were NOT matched by Input 1
        res.matched_index_set = matched_index_set
        if res.target_index_file and Path(res.target_index_file).is_file():
            df_target, _ = read_tab_delimited_file(res.target_index_file)
            target_col = find_index_column(list(df_target.columns)) or df_target.columns[0]
            target_vals = df_target[target_col].fillna("").astype(str).str.strip().tolist()
            unm_target = [v for v in target_vals if v and v not in matched_index_set]
            res.unmatched_index_df = pd.DataFrame({index_col: unm_target})
            res.total_unmatched_index_rows = len(res.unmatched_index_df)
        else:
            idx_series = df_index[index_col].fillna("").astype(str).str.strip()
            res.unmatched_index_df = df_index.loc[~idx_series.isin(matched_index_set)].copy().reset_index(drop=True)
            res.total_unmatched_index_rows = len(res.unmatched_index_df)

        self.set_progress(1.0, "Analysis completed successfully!")
        self.log("=" * 60)
        self.log(f"Phase 1 Analysis Finished:")
        self.log(f"  • Total Input 1 Files: {res.total_input1_files}")
        if res.total_removed_blank_date_rows > 0:
            self.log(f"  • Filtered out {res.total_removed_blank_date_rows:,} row(s) with blank/null/0 Posting Date before matching.")
        self.log(f"  • Total Valid Rows in Input 1: {res.total_input1_rows:,}")
        self.log(f"  • Total Matched: {res.total_matched_rows:,} ({res.match_percentage:.2f}%)")
        self.log(f"  • Total Unmatched in Input 1: {res.total_unmatched_rows:,} ({100.0 - res.match_percentage:.2f}%)")
        if res.target_index_file:
            self.log(f"  • Target Index CSV Filter Active: {res.total_unmatched_index_rows:,} unmatched index numbers out of target list.")
        else:
            self.log(f"  • Total Unmatched in Index File (not found in Input 1): {res.total_unmatched_index_rows:,}")
        self.log("=" * 60)

        return res

    def export_unmatched_indexes_csv(self, analysis_result: AnalysisResult, export_path: str) -> int:
        """
        Exports only the not found Index numbers from the Consolidated Index File (Input 2)
        that were NEVER matched by any record in Input 1.
        """
        out_path = Path(export_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if analysis_result.unmatched_index_df is None or analysis_result.unmatched_index_df.empty:
            out_path.write_text("", encoding="utf-8")
            return 0

        index_col = analysis_result.index_col_input2 or "Index"
        if index_col in analysis_result.unmatched_index_df.columns:
            series = analysis_result.unmatched_index_df[index_col].fillna("").astype(str).str.strip()
        else:
            series = analysis_result.unmatched_index_df.iloc[:, 0].fillna("").astype(str).str.strip()

        series.to_csv(out_path, index=False, header=False, encoding="utf-8-sig")
        return len(series)

    def generate_indexed_files(self, analysis_result: AnalysisResult, output_folder: str) -> int:
        """
        Phase 2: Reads each original file from Input 1, filters out blank/null/0 date rows,
        maps the Index column using vectorized lookups (only the first matching line item
        for a given key gets the Index; later line items sharing that key are left blank),
        and saves it in the exact nested directory structure inside output_folder.
        """
        self.is_cancelled = False
        out_root = Path(output_folder).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        analysis_result.output_folder = str(out_root)

        self.log(f"Starting Phase 2 Generation into: {out_root}")
        lookup = analysis_result.lookup_dict
        common_cols_input1 = analysis_result.common_columns_input1
        input1_files = analysis_result.input1_files
        index_col_name = "Index"

        total_files = len(input1_files)
        files_written = 0

        for f_idx, (rel_path, abs_path) in enumerate(input1_files):
            if self.is_cancelled:
                raise InterruptedError("Generation cancelled by user.")

            progress_val = (f_idx / total_files)
            self.set_progress(progress_val, f"Writing [{f_idx + 1}/{total_files}]: {Path(rel_path).name}")

            df_curr, enc = read_tab_delimited_file(abs_path)
            curr_cols_map = {c.strip().lower(): c for c in df_curr.columns}

            # Date column handling & remove blank/null/0 date rows
            date_col_curr = None
            if analysis_result.date_col_input1 and analysis_result.date_col_input1.strip().lower() in curr_cols_map:
                date_col_curr = curr_cols_map[analysis_result.date_col_input1.strip().lower()]
            else:
                date_col_curr = find_date_column(list(df_curr.columns))

            df_curr, _ = filter_valid_pstng_dates(df_curr, date_col_curr)

            if len(df_curr) == 0:
                df_curr[index_col_name] = []
                dest_file = out_root / rel_path
                write_tab_delimited_file(df_curr, str(dest_file), encoding=enc)
                files_written += 1
                continue

            file_match_cols = [curr_cols_map.get(c1.strip().lower()) for c1 in common_cols_input1]

            # Vectorized column arrays
            file_col_arrays = prepare_normalized_column_arrays(df_curr, file_match_cols)

            # Fast mapping via dict lookup: only the first line item for a given key
            # gets the Index; later duplicates of the same key are left blank.
            mapped_indices = []
            seen_keys = set()
            for k in zip(*file_col_arrays):
                val = lookup.get(k, "")
                if val and k not in seen_keys:
                    mapped_indices.append(val)
                    seen_keys.add(k)
                else:
                    mapped_indices.append("")

            # Add or update Index column
            df_curr[index_col_name] = mapped_indices

            # Target output file path retaining relative subfolders
            dest_file = out_root / rel_path
            write_tab_delimited_file(df_curr, str(dest_file), encoding=enc)
            files_written += 1

        self.set_progress(1.0, f"Successfully created {files_written} indexed files!")
        self.log(f"Phase 2 Complete: {files_written} files generated in {out_root}")
        return files_written
