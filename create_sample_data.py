"""
Utility script to generate sample test data matching the user's scenario:
- Input Folder with nested subfolders and tab-separated .txt files (including ~ and ' characters)
- Pstng Date in EU (DD-MM-YYYY) and US (MM/DD/YYYY) formats
- Consolidated index file with extra columns and Index column
"""

import os
from pathlib import Path

def generate_samples():
    base_dir = Path(__file__).parent / "sample_data"
    input_folder = base_dir / "Source_Files"
    index_file = base_dir / "consolidated_with_index.txt"

    # Create nested subfolders
    sub1 = input_folder / "North_Region" / "FY23-Q1"
    sub2 = input_folder / "South_Region" / "FY23-Q2"
    sub3 = input_folder / "West_Region"

    sub1.mkdir(parents=True, exist_ok=True)
    sub2.mkdir(parents=True, exist_ok=True)
    sub3.mkdir(parents=True, exist_ok=True)

    # File 1: EU dates with ~ and ' in name
    f1 = sub1 / "ledger~2023'apr.txt"
    with open(f1, "w", encoding="utf-8") as f:
        f.write("Pstng Date\tDoc No\tAccount\tAmount\tCost Center\n")
        f.write("10-04-2023\tDOC001\t00100\t1500.00\tCC101\n")
        f.write("15-04-2023\tDOC002\t00200\t2400.00\tCC102\n")
        f.write("28-04-2023\tDOC003\t00300\t3100.00\tCC103\n")

    # File 2: US dates with spaces and special characters
    f2 = sub2 / "ledger~2023'may [final].txt"
    with open(f2, "w", encoding="utf-8") as f:
        f.write("Pstng Date\tDoc No\tAccount\tAmount\tCost Center\n")
        f.write("05/10/2023\tDOC004\t00400\t4200.00\tCC201\n")
        f.write("05/22/2023\tDOC005\t00500\t5300.00\tCC202\n")

    # File 3: June data in West_Region
    f3 = sub3 / "june_records~'west'.txt"
    with open(f3, "w", encoding="utf-8") as f:
        f.write("Pstng Date\tDoc No\tAccount\tAmount\tCost Center\n")
        f.write("14-06-2023\tDOC006\t00600\t6100.00\tCC301\n")
        f.write("25-06-2023\tDOC007\t00700\t7200.00\tCC302\n")
        f.write("30-06-2023\tDOC008\t00800\t8900.00\tCC303\n")  # Unmatched row

    # Consolidated Index File (Tab Separated, has additional column and Index column)
    with open(index_file, "w", encoding="utf-8") as f:
        f.write("PSTNG DATE\tDOC NO\tACCOUNT\tAMOUNT\tCOST CENTER\tAudit_Status\tIndex\n")
        f.write("10-04-2023\tDOC001\t00100\t1500.00\tCC101\tApproved\tIDX-2023-0001\n")
        f.write("15-04-2023\tDOC002\t00200\t2400.00\tCC102\tApproved\tIDX-2023-0002\n")
        f.write("28-04-2023\tDOC003\t00300\t3100.00\tCC103\tPending\tIDX-2023-0003\n")
        f.write("05/10/2023\tDOC004\t00400\t4200.00\tCC201\tApproved\tIDX-2023-0004\n")
        f.write("05/22/2023\tDOC005\t00500\t5300.00\tCC202\tApproved\tIDX-2023-0005\n")
        f.write("14-06-2023\tDOC006\t00600\t6100.00\tCC301\tApproved\tIDX-2023-0006\n")
        f.write("25-06-2023\tDOC007\t00700\t7200.00\tCC302\tApproved\tIDX-2023-0007\n")
        # DOC008 is intentionally missing from index to demonstrate unmatched row handling

    print(f"Sample data generated successfully at:\n{base_dir}")

if __name__ == "__main__":
    generate_samples()
