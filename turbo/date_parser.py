"""
Power Query Date Logic implemented natively in DuckDB SQL expressions
for multi-threaded C++ execution.
"""

from typing import Tuple


def get_pq_date_macros_sql() -> str:
    """
    Returns SQL statements to create DuckDB macros that implement the exact
    Power Query posting date logic:
      - If contains '-' -> delimiter is '-', parts = [Day, Month, Year]
      - Else -> delimiter is '/', parts = [Month, Day, Year]
      - If Year < 100: Year = if Year < 50 then 2000 + Year else 1900 + Year
      - Generates sort key 'YYYY-MM' and label 'YYYY-MM (Mon YYYY)'
    """
    return """
    CREATE OR REPLACE MACRO pq_month_key(raw_d) AS (
        CASE 
            WHEN raw_d IS NULL OR TRIM(raw_d) IN ('', '0', '0.0', '0.00', '00', 'nan', 'null', 'none', 'nat', '#n/a') 
                 OR REGEXP_MATCHES(REPLACE(REPLACE(REPLACE(REPLACE(CAST(raw_d AS VARCHAR), '-', ''), '/', ''), '.', ''), ' ', ''), '^0+$')
            THEN '9999-99'
            ELSE (
                WITH p AS (
                    SELECT 
                        TRIM(CAST(raw_d AS VARCHAR)) AS s,
                        CASE WHEN contains(TRIM(CAST(raw_d AS VARCHAR)), '-') THEN '-' ELSE '/' END AS sep,
                        str_split(TRIM(CAST(raw_d AS VARCHAR)), CASE WHEN contains(TRIM(CAST(raw_d AS VARCHAR)), '-') THEN '-' ELSE '/' END) AS parts
                ),
                c AS (
                    SELECT 
                        TRY_CAST(CASE WHEN sep = '-' THEN parts[2] ELSE parts[1] END AS INTEGER) AS m,
                        TRY_CAST(CASE WHEN sep = '-' THEN parts[1] ELSE parts[2] END AS INTEGER) AS d,
                        TRY_CAST(parts[3] AS INTEGER) AS y_raw
                    FROM p
                ),
                f AS (
                    SELECT 
                        m,
                        d,
                        CASE 
                            WHEN y_raw < 50 THEN 2000 + y_raw
                            WHEN y_raw < 100 THEN 1900 + y_raw
                            ELSE y_raw
                        END AS y
                    FROM c
                )
                SELECT 
                    CASE 
                        WHEN y IS NULL OR m IS NULL OR m < 1 OR m > 12 THEN '9999-99'
                        ELSE printf('%04d-%02d', y, m)
                    END
                FROM f
            )
        END
    );

    CREATE OR REPLACE MACRO pq_month_label(raw_d) AS (
        CASE 
            WHEN raw_d IS NULL OR TRIM(raw_d) IN ('', '0', '0.0', '0.00', '00', 'nan', 'null', 'none', 'nat', '#n/a') 
                 OR REGEXP_MATCHES(REPLACE(REPLACE(REPLACE(REPLACE(CAST(raw_d AS VARCHAR), '-', ''), '/', ''), '.', ''), ' ', ''), '^0+$')
            THEN 'Unknown / Missing Date'
            ELSE (
                WITH p AS (
                    SELECT 
                        TRIM(CAST(raw_d AS VARCHAR)) AS s,
                        CASE WHEN contains(TRIM(CAST(raw_d AS VARCHAR)), '-') THEN '-' ELSE '/' END AS sep,
                        str_split(TRIM(CAST(raw_d AS VARCHAR)), CASE WHEN contains(TRIM(CAST(raw_d AS VARCHAR)), '-') THEN '-' ELSE '/' END) AS parts
                ),
                c AS (
                    SELECT 
                        TRY_CAST(CASE WHEN sep = '-' THEN parts[2] ELSE parts[1] END AS INTEGER) AS m,
                        TRY_CAST(CASE WHEN sep = '-' THEN parts[1] ELSE parts[2] END AS INTEGER) AS d,
                        TRY_CAST(parts[3] AS INTEGER) AS y_raw
                    FROM p
                ),
                f AS (
                    SELECT 
                        m,
                        d,
                        CASE 
                            WHEN y_raw < 50 THEN 2000 + y_raw
                            WHEN y_raw < 100 THEN 1900 + y_raw
                            ELSE y_raw
                        END AS y
                    FROM c
                )
                SELECT 
                    CASE 
                        WHEN y IS NULL OR m IS NULL OR m < 1 OR m > 12 THEN 'Unknown / Missing Date'
                        ELSE strftime(make_date(y, m, 1), '%Y-%m (%b %Y)')
                    END
                FROM f
            )
        END
    );
    """


def get_normalization_macro_sql() -> str:
    """
    Returns SQL statements to create DuckDB value normalization macro `norm_v(v)`.
    Handles:
      - Whitespace trimming
      - Quote stripping ('\"' and ''')
      - Thousands separator removal (',')
      - Lowercase conversion
      - Numeric trailing zero trimming (e.g. '1.00' -> '1', '1.50' -> '1.5')
      - NaN / NULL / None / Empty handling -> ''
      - "Noise punctuation" folding: the Unicode replacement character (from an
        upstream export that misread CP1252 bytes as UTF-8 and lost the original
        character -- common in older consolidated exports) and lookalike
        punctuation (non-breaking space, curly quotes, en/em dashes -- common
        when SAP text fields get pasted through Excel) are folded to a plain
        space/quote/hyphen so two otherwise-identical descriptions don't fail to
        match purely over which mangled character ended up on which side.
    """
    # Built as real Unicode characters (not regex escapes) so DuckDB's RE2 engine
    # matches them literally regardless of locale.
    replacement_char = "�"
    nbsp = " "
    curly_single = "‘’"
    curly_double = "“”"
    dashes = "–—"
    space_class = f"[{replacement_char}{nbsp}]+"
    quote_class = f"[{curly_single}]"
    dquote_class = f"[{curly_double}]"
    dash_class = f"[{dashes}]"

    return f"""
    CREATE OR REPLACE MACRO norm_v(v) AS (
        CASE
            WHEN v IS NULL THEN ''
            WHEN LOWER(TRIM(REPLACE(REPLACE(CAST(v AS VARCHAR), chr(34), ''), chr(39), ''))) IN ('nan', 'null', 'none', '<na>', '#n/a') THEN ''
            ELSE
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        LOWER(TRIM(REPLACE(REPLACE(REPLACE(
                            TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                                CAST(v AS VARCHAR),
                                '{space_class}', ' ', 'g'),
                                '{quote_class}', chr(39), 'g'),
                                '{dquote_class}', chr(34), 'g'),
                                '{dash_class}', '-', 'g')),
                            chr(34), ''), chr(39), ''), ',', ''))),
                        '\\.0+$', ''
                    ),
                    '(\\.[0-9]*[1-9])0+$', '\\1'
                )
        END
    );

    CREATE OR REPLACE MACRO norm_abs_v(v) AS (
        CASE
            WHEN v IS NULL THEN ''
            WHEN LOWER(TRIM(REPLACE(REPLACE(CAST(v AS VARCHAR), chr(34), ''), chr(39), ''))) IN ('nan', 'null', 'none', '<na>', '#n/a') THEN ''
            ELSE
                LTRIM(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            LOWER(TRIM(REPLACE(REPLACE(REPLACE(
                                TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(
                                    CAST(v AS VARCHAR),
                                    '{space_class}', ' ', 'g'),
                                    '{quote_class}', chr(39), 'g'),
                                    '{dquote_class}', chr(34), 'g'),
                                    '{dash_class}', '-', 'g')),
                                chr(34), ''), chr(39), ''), ',', ''))),
                            '\\.0+$', ''
                        ),
                        '(\\.[0-9]*[1-9])0+$', '\\1'
                    ),
                    '-+'
                )
        END
    );
    """


def get_valid_date_filter_sql(col_name: str) -> str:
    """
    Returns SQL boolean condition to filter out blank, null, '0', '0.0', '00-00-0000', etc.
    """
    c = f'"{col_name}"'
    return f"""(
        {c} IS NOT NULL 
        AND TRIM(REPLACE(REPLACE(CAST({c} AS VARCHAR), chr(34), ''), chr(39), '')) NOT IN (
            '', '0', '0.0', '0.00', '00', 'nan', 'null', 'none', 'nat', '#n/a', 
            '00-00-0000', '00/00/0000', '00.00.0000', '0000-00-00', '0000/00/00', '00000000'
        )
        AND NOT REGEXP_MATCHES(REPLACE(REPLACE(REPLACE(REPLACE(CAST({c} AS VARCHAR), '-', ''), '/', ''), '.', ''), ' ', ''), '^0+$')
    )"""
