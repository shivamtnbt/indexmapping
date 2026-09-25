"""
Unit and integration tests for Turbo Indexing Engine (DuckDB Powered)
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from turbo.engine import TurboIndexerEngine


class TestTurboEngineEndToEnd(unittest.TestCase):
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
        f1_path = sub1 / "data~2023'apr.txt"
        with open(f1_path, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDoc No\tAccount\tAmount\n")
            f.write("10-04-2023\t1001\t0050\t150.00\n")
            f.write("15-04-2023\t1002\t0060\t250.00\n")
            f.write("15-04-2023\t1002\t0060\t250.00\n")  # duplicate line item matching row 2!
            f.write("20-04-2023\t1003\t0070\t350.00\n")  # unmatched
            f.write("0\t9999\t0000\t0.00\n")             # blank/0 date row, MUST BE REMOVED!

        # File 2 in sub2: US dates
        f2_path = sub2 / "may~report'2023.txt"
        with open(f2_path, "w", encoding="utf-8") as f:
            f.write("PSTNG DATE\tdoc no\taccount\tamount\n")
            f.write("05/12/2023\t2001\t0080\t450.00\n")
            f.write("05/20/2023\t2002\t0090\t550.00\n")

        # Consolidated Index File (Input 2)
        with open(self.index_file, "w", encoding="utf-8") as f:
            f.write("PSTNG DATE\tDOC NO\tACCOUNT\tAMOUNT\tEXTRA_COL\tIndex\n")
            f.write("10-04-2023\t1001\t0050\t150.00\tExtra1\tIDX-001\n")
            f.write("15-04-2023\t1002\t0060\t250.00\tExtra2\tIDX-002\n")
            f.write("05/12/2023\t2001\t0080\t450.00\tExtra3\tIDX-003\n")
            f.write("05/20/2023\t2002\t0090\t550.00\tExtra4\tIDX-004\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_turbo_full_pipeline(self):
        engine = TurboIndexerEngine()
        res = engine.analyze(str(self.input_folder), str(self.index_file))

        self.assertEqual(res.total_input1_files, 2)
        # File 1 has 5 valid rows (1 dropped for 0 date). File 2 has 2 valid rows. Total = 6 rows.
        self.assertEqual(res.total_removed_blank_date_rows, 1)
        self.assertEqual(res.total_input1_rows, 6)

        # Matched rows: 1001 (1), 1002 (2 duplicate rows), 2001 (1), 2002 (1) = 5 matched
        self.assertEqual(res.total_matched_rows, 5)
        # Unmatched rows: 1003 (1) = 1 unmatched
        self.assertEqual(res.total_unmatched_rows, 1)

        # Check month summary breakdown
        df_summary = res.month_summary_df
        self.assertIsNotNone(df_summary)
        self.assertEqual(len(df_summary), 2)  # Apr 2023 and May 2023

        apr_row = df_summary[df_summary["_sort_key"] == "2023-04"].iloc[0]
        self.assertEqual(apr_row["Total Records"], 4)
        self.assertEqual(apr_row["Matched Records"], 3)  # 1001 + 2 of 1002
        self.assertEqual(apr_row["Unmatched Records"], 1)

        # Test Phase 2 file generation
        files_written = engine.generate_indexed_files(res, str(self.output_folder))
        self.assertEqual(files_written, 2)

        out_f1 = self.output_folder / "Region A" / "Subfolder 1" / "data~2023'apr.txt"
        self.assertTrue(out_f1.exists())
        df_out1 = pd.read_csv(out_f1, sep="\t", dtype=str)

        # 0 date row must be excluded
        self.assertEqual(len(df_out1), 4)
        self.assertIn("Index", df_out1.columns)
        self.assertEqual(df_out1.loc[0, "Index"], "IDX-001")
        # Check duplicate line items repeat the index!
        self.assertEqual(df_out1.loc[1, "Index"], "IDX-002")
        self.assertEqual(df_out1.loc[2, "Index"], "IDX-002")
        # Unmatched row
        self.assertTrue(pd.isna(df_out1.loc[3, "Index"]) or df_out1.loc[3, "Index"] == "")

        # Test single month unmatched export
        unm_csv = Path(self.test_dir) / "unm_apr.csv"
        exported_count = engine.export_unmatched_for_month(res, "2023-04 (Apr 2023)", str(unm_csv))
        self.assertEqual(exported_count, 1)
        self.assertTrue(unm_csv.exists())
        df_unm = pd.read_csv(unm_csv)
        self.assertEqual(len(df_unm), 1)
        self.assertEqual(str(df_unm.loc[0, "Doc No"]), "1003")

    def test_normalizations_and_duplicates(self):
        # Test quantities with .00 vs integer, commas in amounts, quotes, nan vs empty, and duplicate keys in index file
        sub = self.input_folder / "NormTest"
        sub.mkdir(parents=True, exist_ok=True)
        f_path = sub / "norm_file.txt"
        with open(f_path, "w", encoding="utf-8") as f:
            f.write("Pstng Date\tDoc No\tQty\tAmount\tNote\n")
            f.write("10-04-2023\t101\t1.00\t3,628.57\tnan\n")           # .00, comma, nan
            f.write("10-04-2023\t102\t2.50\t1,000.00\t\"Special\"\n")      # .50, comma, quotes
            f.write("  \t103\t0.00\t0.00\tblank_date\n")                  # blank date -> must be removed!

        idx_path = Path(self.test_dir) / "idx_norm.txt"
        with open(idx_path, "w", encoding="utf-8") as f:
            f.write("PSTNG DATE\tDOC NO\tQTY\tAMOUNT\tNOTE\tIndex\n")
            f.write("10-04-2023\t101\t1\t3628.57\t\tIDX-NORM-01\n")        # matches row 1 with clean numbers
            # Add duplicate composite key in index file (different index)
            f.write("10-04-2023\t101\t1\t3628.57\t\tIDX-NORM-01-DUP\n")    # duplicate key, first occurrence must be kept!
            f.write("10-04-2023\t102\t2.5\t1000\tSpecial\tIDX-NORM-02\n")   # matches row 2

        engine = TurboIndexerEngine()
        res = engine.analyze(str(sub), str(idx_path))

        self.assertEqual(res.total_removed_blank_date_rows, 1)
        self.assertEqual(res.total_input1_rows, 2)
        self.assertEqual(res.total_matched_rows, 2)
        self.assertEqual(res.duplicate_keys_in_input2, 1)

        out_dir = Path(self.test_dir) / "out_norm"
        engine.generate_indexed_files(res, str(out_dir))

        df_res = pd.read_csv(out_dir / "norm_file.txt", sep="\t", dtype=str)
        self.assertEqual(len(df_res), 2)
        self.assertEqual(df_res.loc[0, "Index"], "IDX-NORM-01")
        self.assertEqual(df_res.loc[1, "Index"], "IDX-NORM-02")

    def test_option1_credit_notes_signed_values(self):
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

        engine = TurboIndexerEngine()
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

        engine = TurboIndexerEngine()
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

        engine = TurboIndexerEngine()
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

        engine = TurboIndexerEngine()
        res = engine.analyze(str(sub), str(idx_file), target_index_file=str(target_file))

        self.assertEqual(res.total_unmatched_index_rows, 1)

        out_csv = Path(self.test_dir) / "unfound_target.csv"
        written = engine.export_unmatched_indexes_csv(res, str(out_csv))
        self.assertEqual(written, 1)

        df_out = pd.read_csv(out_csv, header=None, dtype=str)
        self.assertEqual(df_out.iloc[0, 0], "IDX-UNFOUND-1")


if __name__ == "__main__":
    unittest.main()
