"""
File handler for scanning, reading, and writing tab-delimited text files.
Handles nested directories, special characters in filenames (~, ', etc.), and varied encodings.
"""

import os
from pathlib import Path
from typing import List, Tuple, Optional
import pandas as pd


SUPPORTED_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1", "iso-8859-1"]


def scan_txt_files(root_dir: str) -> List[Tuple[str, str]]:
    """
    Recursively scans the root directory for .txt files.
    Returns a list of tuples: (relative_path, absolute_path).
    
    Correctly handles filenames with special characters like ~, ', spaces, brackets.
    """
    root_path = Path(root_dir).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"Directory not found: {root_dir}")

    found_files = []
    # Walk directory tree
    for dirpath, _, filenames in os.walk(root_path):
        for fname in filenames:
            # We match .txt files (case-insensitive extension)
            if fname.lower().endswith(".txt"):
                # Ignore Excel temp lock files like ~$filename
                if fname.startswith("~$"):
                    continue
                abs_file = Path(dirpath) / fname
                rel_file = abs_file.relative_to(root_path)
                found_files.append((str(rel_file), str(abs_file)))

    # Sort files naturally for consistent ordering
    found_files.sort(key=lambda x: x[0].lower())
    return found_files


def read_tab_delimited_file(filepath: str, sep: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    """
    Reads a tab-separated text/csv file into a DataFrame.
    All columns are loaded as string (dtype=str) to preserve leading zeros, codes, and IDs.
    Returns (df, encoding_used).
    """
    path = Path(filepath).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {filepath}")

    last_error = None
    delimiter = sep if sep is not None else "\t"

    for enc in SUPPORTED_ENCODINGS:
        try:
            # Try fast C engine first
            df = pd.read_csv(
                str(path),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                encoding=enc,
                engine="c",
                on_bad_lines="skip"
            )
            # If sep was auto and table has only 1 column, check if comma or semicolon was used
            if sep is None and len(df.columns) == 1 and ("\t" not in df.columns[0]):
                # Check line sample
                with open(str(path), "r", encoding=enc, errors="ignore") as f:
                    first_line = f.readline()
                if "\t" not in first_line:
                    for alt_sep in [",", ";", "|"]:
                        if alt_sep in first_line:
                            df = pd.read_csv(
                                str(path),
                                sep=alt_sep,
                                dtype=str,
                                keep_default_na=False,
                                encoding=enc,
                                engine="c",
                                on_bad_lines="skip"
                            )
                            break
            return df, enc
        except UnicodeDecodeError as e:
            last_error = e
            continue
        except Exception:
            # Try python engine if c engine fails (e.g., unusual quotes or embedded delimiters)
            try:
                df = pd.read_csv(
                    str(path),
                    sep=delimiter,
                    dtype=str,
                    keep_default_na=False,
                    encoding=enc,
                    engine="python",
                    on_bad_lines="skip"
                )
                return df, enc
            except Exception as e:
                last_error = e
                continue

    raise ValueError(f"Failed to read file {filepath} with supported encodings. Last error: {last_error}")


def write_tab_delimited_file(df: pd.DataFrame, dest_filepath: str, encoding: str = "utf-8") -> None:
    """
    Writes DataFrame to destination file with tab separation (\t).
    Creates parent directories if they don't exist.
    """
    dest_path = Path(dest_filepath).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(
        str(dest_path),
        sep="\t",
        index=False,
        encoding=encoding,
        lineterminator="\r\n"
    )
