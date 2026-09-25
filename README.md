# PBI Indexer & Consolidation Tool

An offline Python desktop application that consolidates tab-delimited (`.txt`) files across nested subfolders, parses Posting Dates according to Power Query logic, matches rows against a consolidated index file on all common columns, displays a month-wise review summary, and generates indexed files replicating the exact directory hierarchy.

---

## Key Features

1. **Multi-Folder Recursive Scanning**:
   - Recursively traverses nested subfolders to locate all tab-separated `.txt` files.
   - Robustly handles special characters in filenames (e.g., `~`, `'`, spaces, brackets).
   - Auto-detects text encodings (`utf-8`, `utf-8-sig`, `cp1252`, `latin-1`).

2. **Power Query Date Parsing**:
   - Accurately converts `Pstng Date` using your Power Query rule:
     * Separator `-`: EU format (`DD-MM-YYYY`)
     * Separator `/`: US format (`MM/DD/YYYY`)
     * Handles 2-digit years (`YY` $\rightarrow$ `20YY`)
   - Groups records chronologically by Month/Year (e.g., `2023-04 (Apr 2023)`).

3. **Intelligent Schema Matching**:
   - Matches column names case-insensitively.
   - Identifies all common columns between input files and the consolidated index file.
   - Preserves string formats (leading zeros in account numbers, doc numbers, cost centers).
   - Case-insensitive, whitespace-trimmed, and numeric-normalized matching.

4. **Two-Phase Review & Execution Workflow**:
   - **Step 1 (Analyze & Match)**:
     * Consolidates all files and matches records.
     * Displays an interactive **Month-wise Summary Table** (Total Records, Matched Records, Unmatched Records, Match %).
     * Provides an **Unmatched Preview** tab with an interactive **Month Filter dropdown** to view unmatched records month by month.
     * **Month-wise Unmatched Download Options**:
       - 📥 **Download Selected Month Unmatched (CSV)**: Click any month row in the table (or simply double-click the row) to immediately download that month's unmatched records.
       - 📁 **Export Each Month as Separate CSVs...**: Exports every month's unmatched records into its own dedicated file (e.g. `Unmatched_2024-01.csv`, `Unmatched_2024-02.csv`) inside a chosen folder, keeping them strictly separated.
       - 💾 **Export Summary Table (CSV)**: Downloads the month-wise summary breakdown table.
   - **Step 2 (Generate Indexed Files)**:
     * Unlocks only after reviewing the summary.
     * Generates updated `.txt` files with the `Index` column added.
     * Unmatched records have their `Index` left blank.
     * Replicates the exact nested subfolder structure and preserved filenames in the target directory.

5. **Modern Desktop Interface**:
   - Built with `customtkinter` with Dark/Light theme toggle.
   - Real-time progress bar, metrics cards, and activity logs.
   - Background multi-threading ensures the UI never hangs or freezes.

---

## How to Run

### Method 1: Double-Click Launcher
Double-click [`run.bat`](file:///c:/Users/shiva/OneDrive%20-%20TNBT%20Tech%20Pvt.%20Ltd/TNBT%20System%20Automation/PBI%20Indexing%202/run.bat).

### Method 2: Command Line
Open a terminal in this directory and execute:
```bash
python main.py
```

---

## Sample Data Included

A working sample dataset has been pre-generated in [`sample_data/`](file:///c:/Users/shiva/OneDrive%20-%20TNBT%20Tech%20Pvt.%20Ltd/TNBT%20System%20Automation/PBI%20Indexing%202/sample_data/):
- **Input Folder**: `sample_data/Source_Files` (contains subfolders and `.txt` files with `~` and `'` in filenames).
- **Consolidated Index File**: `sample_data/consolidated_with_index.txt`
You can test the tool immediately using these sample paths!
