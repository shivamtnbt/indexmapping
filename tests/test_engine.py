"""
Comprehensive unit & integration tests for PBI Indexing Engine
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from core.date_parser import parse_pstng_date, get_month_key_and_label
from core.indexer_engine import IndexerEngine, normalize_val


class TestDateParser(unittest.TestCase):
    def test_eu_hyphen_dates(self):
        # Separator - => DD-MM-YYYY
        dt = parse_pstng_date("15-04-2023")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2023)
        self.assertEqual(dt.month, 4)
        self.assertEqual(dt.day, 15)

        # 2-digit year
        dt2 = parse_pstng_date("05-11-23")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.year, 2023)
        self.assertEqual(dt2.month, 11)
        self.assertEqual(dt2.day, 5)

    def test_us_slash_dates(self):
        # Separator / => MM/DD/YYYY
        dt = parse_pstng_date("04/15/2023")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2023)
        self.assertEqual(dt.month, 4)
        self.assertEqual(dt.day, 15)

        # 2-digit year
        dt2 = parse_pstng_date("12/25/24")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.year, 2024)
        self.assertEqual(dt2.month, 12)
        self.assertEqual(dt2.day, 25)

    def test_month_labels(self):
        dt = parse_pstng_date("15-04-2023")
        sort_key, label = get_month_key_and_label(dt)
        self.assertEqual(sort_key, "2023-04")
        self.assertEqual(label, "2023-04 (Apr 2023)")


class TestIndexerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.input_folder = Path(self.test_dir) / "input_root"
        self.output_folder = Path(self.test_dir) / "output_root"
        self.index_file = Path(self.test_dir) / "consolidated_index.txt"

        # Create nested folders in input_root
        sub1 = self.input_folder / "Region A" / "Subfolder 1"
        sub2 = self.input_folder / "Region B"
        sub1.mkdir(parents=True, exist_ok=True)
        sub2.mkdir(parents=True, exist_ok=True)

        # File 1 with ~ and ' in name: EU dates
        # Tab separated
        f1_path = sub1 / "data~2023'apr.txt"
        with open(f1_path, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDoc No\tAccount\tAmount\n")
            f.write("10-04-2023\t1001\t0050\t150.00\n")
            f.write("15-04-2023\t1002\t0060\t250.00\n")
            f.write("20-04-2023\t1003\t0070\t350.00\n")  # will be unmatched

        # File 2 in sub2: US dates
        f2_path = sub2 / "may~report'2023.txt"
        with open(f2_path, "w", encoding="utf-8") as f:
            f.write("PSTNG DATE\tdoc no\taccount\tamount\n")  # case variations in header
            f.write("05/12/2023\t2001\t0080\t450.00\n")
            f.write("05/20/2023\t2002\t0090\t550.00\n")

        # Consolidated Index File (Input 2)
        # Tab separated, has additional column and Index column
        with open(self.index_file, "w", encoding="utf-8") as f:
            f.write("PSTNG DATE\tDOC NO\tACCOUNT\tAMOUNT\tEXTRA_COL\tIndex\n")
            # matches File 1 row 1
            f.write("10-04-2023\t1001\t0050\t150.00\tExtra1\tIDX-001\n")
            # matches File 1 row 2 (with case differences in data e.g. lower/upper)
            f.write("15-04-2023\t1002\t0060\t150.00\tExtra2\tIDX-002\n")  # amount differs, won't match if amount is common col
            # let's match exact:
            f.write("15-04-2023\t1002\t0060\t250.00\tExtra2\tIDX-002\n")
            # matches File 2 row 1
            f.write("05/12/2023\t2001\t0080\t450.00\tExtra3\tIDX-003\n")
            # matches File 2 row 2
            f.write("05/20/2023\t2002\t0090\t550.00\tExtra4\tIDX-004\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_pipeline(self):
        engine = IndexerEngine()
        res = engine.analyze(str(self.input_folder), str(self.index_file))

        self.assertEqual(res.total_input1_files, 2)
        self.assertEqual(res.total_input1_rows, 5)
        # 1001, 1002, 2001, 2002 matched. 1003 unmatched.
        self.assertEqual(res.total_matched_rows, 4)
        self.assertEqual(res.total_unmatched_rows, 1)
        self.assertEqual(res.match_percentage, 80.0)

        # Check month summary
        df_summary = res.month_summary_df
        self.assertEqual(len(df_summary), 2)  # Apr 2023 and May 2023

        apr_row = df_summary[df_summary["_sort_key"] == "2023-04"].iloc[0]
        self.assertEqual(apr_row["Total Records"], 3)
        self.assertEqual(apr_row["Matched Records"], 2)
        self.assertEqual(apr_row["Unmatched Records"], 1)

        may_row = df_summary[df_summary["_sort_key"] == "2023-05"].iloc[0]
        self.assertEqual(may_row["Total Records"], 2)
        self.assertEqual(may_row["Matched Records"], 2)
        self.assertEqual(may_row["Unmatched Records"], 0)

        # Now test Phase 2 file generation
        files_written = engine.generate_indexed_files(res, str(self.output_folder))
        self.assertEqual(files_written, 2)

        # Check that output files exist with exact filenames and nested folders
        out_f1 = self.output_folder / "Region A" / "Subfolder 1" / "data~2023'apr.txt"
        out_f2 = self.output_folder / "Region B" / "may~report'2023.txt"
        self.assertTrue(out_f1.exists())
        self.assertTrue(out_f2.exists())

        # Inspect contents of out_f1
        df_out1 = pd.read_csv(out_f1, sep="\t", dtype=str)
        self.assertIn("Index", df_out1.columns)
        self.assertEqual(df_out1.loc[0, "Index"], "IDX-001")
        self.assertEqual(df_out1.loc[1, "Index"], "IDX-002")
        # Unmatched row should be empty string or NaN
        self.assertTrue(pd.isna(df_out1.loc[2, "Index"]) or df_out1.loc[2, "Index"] == "")

        # Inspect contents of out_f2
        df_out2 = pd.read_csv(out_f2, sep="\t", dtype=str)
        self.assertIn("Index", df_out2.columns)
        self.assertEqual(df_out2.loc[0, "Index"], "IDX-003")
        self.assertEqual(df_out2.loc[1, "Index"], "IDX-004")

    def test_blank_null_zero_date_filtering(self):
        from core.indexer_engine import filter_valid_pstng_dates
        df_test = pd.DataFrame({
            "Pstng Date": ["10-04-2023", "", "   ", "0", "0.0", "00", "00-00-0000", "00/00/0000", "nan", "NULL", "15-04-2023"],
            "Doc No": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
            "Amount": ["100", "200", "300", "400", "500", "600", "700", "800", "900", "1000", "1100"]
        })
        filtered_df, num_dropped = filter_valid_pstng_dates(df_test, "Pstng Date")
        self.assertEqual(num_dropped, 9)
        self.assertEqual(len(filtered_df), 2)
        self.assertListEqual(list(filtered_df["Doc No"]), ["1", "11"])

    def test_duplicate_line_items_index_repeats(self):
        # When Input 1 has multiple identical line items matching the index file,
        # all of them should receive the matching Index
        sub = self.input_folder / "DupTest"
        sub.mkdir(parents=True, exist_ok=True)
        dup_file = sub / "dup_items.txt"
        with open(dup_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDoc No\tAccount\tAmount\n")
            f.write("10-04-2023\t1001\t0050\t150.00\n")
            f.write("10-04-2023\t1001\t0050\t150.00\n")  # exact duplicate
            f.write("10-04-2023\t1001\t0050\t150.00\n")  # exact duplicate #2
            f.write("0\t9999\t0000\t0.00\n")             # blank/0 date row, must be filtered!

        # Consolidated index with single matching entry
        index_dup_file = Path(self.test_dir) / "index_dup.txt"
        with open(index_dup_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDoc No\tAccount\tAmount\tIndex\n")
            f.write("10-04-2023\t1001\t0050\t150.00\tIDX-REPEAT-999\n")

        engine = IndexerEngine()
        res = engine.analyze(str(sub), str(index_dup_file))

        # Check that 0 date was dropped
        self.assertEqual(res.total_removed_blank_date_rows, 1)
        self.assertEqual(res.total_input1_rows, 3)
        self.assertEqual(res.total_matched_rows, 3)

        out_dup = Path(self.test_dir) / "out_dup"
        engine.generate_indexed_files(res, str(out_dup))

        out_file = out_dup / "dup_items.txt"
        self.assertTrue(out_file.exists())
        df_res = pd.read_csv(out_file, sep="\t", dtype=str)
        self.assertEqual(len(df_res), 3)  # filtered row excluded
        self.assertEqual(list(df_res["Index"]), ["IDX-REPEAT-999", "IDX-REPEAT-999", "IDX-REPEAT-999"])

    def test_option1_abs_value_matching_quantities_and_net_values(self):
        # Credit Note where SAP dump has positive Qty and Net value, but Consolidated Index has negative Qty and Net value
        sub = self.input_folder / "CreditNoteTest"
        sub.mkdir(parents=True, exist_ok=True)
        cn_file = sub / "credit_notes.txt"
        with open(cn_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tBilled Quantity\tNet value\tSubtotal 3\n")
            f.write("4/15/2026\t6009054047\t1.00\t14,243.25\t-749.65\n")

        idx_file = Path(self.test_dir) / "idx_credit_notes.txt"
        with open(idx_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tBilled Quantity\tNet value\tSubtotal 3\tIndex\n")
            f.write("4/15/2026\t6009054047\t-1\t-14243.25\t-749.65\tIDX-CN-3178983\n")

        engine = IndexerEngine()
        res = engine.analyze(str(sub), str(idx_file))

        self.assertEqual(res.total_input1_rows, 1)
        self.assertEqual(res.total_matched_rows, 1)
        self.assertEqual(res.total_unmatched_rows, 0)
        self.assertEqual(res.match_percentage, 100.0)

        out_cn = Path(self.test_dir) / "out_cn"
        engine.generate_indexed_files(res, str(out_cn))

        df_res = pd.read_csv(out_cn / "credit_notes.txt", sep="\t", dtype=str)
        self.assertEqual(df_res.loc[0, "Index"], "IDX-CN-3178983")

    def test_fallback_original_columns_zeroed_quantities_and_amounts(self):
        # Row where SAP dump has raw values (1.00 and 3827.69),
        # but Consolidated Index has zeroed Billed Quantity (0) and Net value (0)
        # while keeping original values in BilledQtyO (1) and NetvalueO (3827.69)
        sub = self.input_folder / "FallbackTest"
        sub.mkdir(parents=True, exist_ok=True)
        raw_file = sub / "raw_sales.txt"
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tBilled Quantity\tNet value\tDescription\n")
            f.write("4/23/2026\t6008000111\t1.00\t3,827.69\tRB AMP 1,59 SN SV B15 P PrAR\n")

        idx_file = Path(self.test_dir) / "idx_fallback.txt"
        with open(idx_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tBilled Quantity\tNet value\tDescription\tBilledQtyO\tNetvalueO\tIndex\n")
            f.write("4/23/2026\t6008000111\t0\t0\tRB AMP 1,59 SN SV B15 P PrAR\t1\t3827.69\t3215824\n")

        engine = IndexerEngine()
        res = engine.analyze(str(sub), str(idx_file))

        self.assertEqual(res.total_input1_rows, 1)
        self.assertEqual(res.total_matched_rows, 1)
        self.assertEqual(res.total_unmatched_rows, 0)
        self.assertEqual(res.match_percentage, 100.0)

        out_fb = Path(self.test_dir) / "out_fb"
        engine.generate_indexed_files(res, str(out_fb))

        df_res = pd.read_csv(out_fb / "raw_sales.txt", sep="\t", dtype=str)
        self.assertEqual(df_res.loc[0, "Index"], "3215824")

    def test_export_unmatched_indexes_csv(self):
        # Index file has 2 items: IDX-1 (matched) and IDX-2 (unmatched)
        sub = self.input_folder / "UnfoundIdxTest"
        sub.mkdir(parents=True, exist_ok=True)
        raw_file = sub / "raw_data.txt"
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\n")
            f.write("4/23/2026\tDOC-100\n")

        idx_file = Path(self.test_dir) / "idx_unfound.txt"
        with open(idx_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tIndex\tExtraInfo\n")
            f.write("4/23/2026\tDOC-100\tIDX-FOUND\tFoundRow\n")
            f.write("4/25/2026\tDOC-999\tIDX-UNFOUND\tUnfoundRow\n")

        engine = IndexerEngine()
        res = engine.analyze(str(sub), str(idx_file))

        self.assertEqual(res.total_matched_rows, 1)
        self.assertEqual(res.total_unmatched_index_rows, 1)

        out_csv = Path(self.test_dir) / "unfound_indexes.csv"
        written = engine.export_unmatched_indexes_csv(res, str(out_csv))
        self.assertEqual(written, 1)
        self.assertTrue(out_csv.exists())

        df_unfound = pd.read_csv(out_csv, header=None, dtype=str)
        self.assertEqual(len(df_unfound), 1)
        self.assertEqual(df_unfound.iloc[0, 0], "IDX-UNFOUND")

    def test_target_index_file_filter(self):
        sub = self.input_folder / "TargetFilterTest"
        sub.mkdir(parents=True, exist_ok=True)
        raw_file = sub / "raw_data.txt"
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\n")
            f.write("4/23/2026\tDOC-100\n")

        idx_file = Path(self.test_dir) / "idx_full.txt"
        with open(idx_file, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDocumentNo\tIndex\n")
            f.write("4/23/2026\tDOC-100\tIDX-FOUND\n")
            f.write("4/25/2026\tDOC-999\tIDX-UNFOUND-1\n")
            f.write("4/26/2026\tDOC-888\tIDX-UNFOUND-2\n")

        target_file = Path(self.test_dir) / "target_list.csv"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("Index\n")
            f.write("IDX-FOUND\n")
            f.write("IDX-UNFOUND-1\n")

        engine = IndexerEngine()
        res = engine.analyze(str(sub), str(idx_file), target_index_file=str(target_file))

        # Out of target_list (IDX-FOUND, IDX-UNFOUND-1), IDX-FOUND is matched, so only IDX-UNFOUND-1 remains.
        self.assertEqual(res.total_unmatched_index_rows, 1)

        out_csv = Path(self.test_dir) / "unfound_target.csv"
        written = engine.export_unmatched_indexes_csv(res, str(out_csv))
        self.assertEqual(written, 1)

        df_out = pd.read_csv(out_csv, header=None, dtype=str)
        self.assertEqual(df_out.iloc[0, 0], "IDX-UNFOUND-1")


if __name__ == "__main__":
    unittest.main()
