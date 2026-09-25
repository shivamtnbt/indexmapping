"""
Date parsing module implementing the Power Query Pstng Date conversion logic:

Power Query logic:
let
    Cleaned    = Text.Trim(Text.From([Pstng Date])),
    Separator  = if Text.Contains(Cleaned, "-") then "-" else "/",
    Parts      = Text.SplitAny(Cleaned, "-/"),
    P1         = Number.FromText(Parts{0}),
    P2         = Number.FromText(Parts{1}),
    P3         = Number.FromText(Parts{2}),
    Year       = if P3 < 100 then P3 + 2000 else P3,

    // If separator is / assume mm/dd (US), else assume dd/mm (EU)
    Day        = if Separator = "/" then P2 else P1,
    Month      = if Separator = "/" then P1 else P2,

    Dt         = #date(Year, Month, Day),
    Result     = Date.ToText(Dt, [Format="dd-MM-yyyy", Culture="en-IN"])
in
    Dt
"""

import re
import datetime
from typing import Optional, Tuple


def parse_pstng_date(val) -> Optional[datetime.date]:
    """
    Parses a posting date value into a datetime.date object using the user's Power Query logic.
    Returns None if the value cannot be parsed.
    """
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("nan", "nat", "none", "null", ""):
        return None

    # Check separator as per Power Query logic
    separator = "-" if "-" in val_str else "/"
    # Split on - or / or .
    parts = re.split(r"[-/]", val_str)
    
    if len(parts) >= 3:
        try:
            # Strip extra spaces or trailing times if any (e.g. "2023-04-15 00:00:00")
            p1_str = parts[0].strip()
            p2_str = parts[1].strip()
            p3_str = parts[2].split()[0].strip()  # remove potential timestamp part

            p1 = int(float(p1_str))
            p2 = int(float(p2_str))
            p3 = int(float(p3_str))

            # Power query rule:
            # If P1 is 4 digits (e.g. 2023-04-15 or 2023/04/15), handle gracefully
            if p1 >= 1000:
                year = p1
                month = p2
                day = p3
            else:
                year = p3 + 2000 if p3 < 100 else p3
                # If separator is / assume mm/dd (US), else assume dd/mm (EU)
                day = p2 if separator == "/" else p1
                month = p1 if separator == "/" else p2

            if 1 <= month <= 12 and 1 <= day <= 31:
                return datetime.date(year, month, day)
        except Exception:
            pass

    # Secondary fallback for dot separator: DD.MM.YYYY (common in SAP exports)
    if "." in val_str:
        dot_parts = val_str.split(".")
        if len(dot_parts) >= 3:
            try:
                d = int(float(dot_parts[0].strip()))
                m = int(float(dot_parts[1].strip()))
                y_str = dot_parts[2].split()[0].strip()
                y = int(float(y_str))
                year = y + 2000 if y < 100 else y
                if 1 <= m <= 12 and 1 <= d <= 31:
                    return datetime.date(year, m, d)
            except Exception:
                pass

    return None


def get_month_key_and_label(dt: Optional[datetime.date]) -> Tuple[str, str]:
    """
    Returns a sortable key (e.g., '2023-04') and human-friendly display label (e.g., '2023-04 (Apr 2023)').
    If dt is None, returns ('9999-99', 'Unknown / Missing Date').
    """
    if dt is None:
        return "9999-99", "Unknown / Missing Date"
    sort_key = dt.strftime("%Y-%m")
    display_label = f"{sort_key} ({dt.strftime('%b %Y')})"
    return sort_key, display_label
