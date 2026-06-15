import pandas as pd
from pathlib import Path
from src.utils.helpers import extract_grand_total, _extract_value_by_keyword, _validate_running_totals

def reconcile_document(
    src: Path, combined_text: str, all_dfs: list[pd.DataFrame], extra_exceptions: list[dict] = None, balance_sheet: bool = False
) -> tuple[str, dict]:
    calculated_total = 0.0
    row_exceptions = []
    if extra_exceptions:
        row_exceptions.extend(extra_exceptions)
        
    running_total_exc = _validate_running_totals(all_dfs)
    if running_total_exc:
        row_exceptions.extend(running_total_exc)

    for t_idx, df in enumerate(all_dfs, start=1):
        skip_cols = {"Page_Num", "Y_Coord", "Validation_Status", "Validation_Notes", "Completeness_Status"}
        data_cols = [c for c in df.columns if c not in skip_cols]
        data_df = df[data_cols]

        for r_idx, row in data_df.iterrows():
            numeric_vals = [v for v in row if isinstance(v, float) and not pd.isna(v)]
            if numeric_vals:
                calculated_total += numeric_vals[-1]

        if "Validation_Status" in df.columns:
            fail_rows = df[df["Validation_Status"] == "FAIL"]
            for r_idx, fail_row in fail_rows.iterrows():
                row_exceptions.append({
                    "table": t_idx,
                    "row": int(r_idx),
                    "data": {str(k): str(v) for k, v in fail_row.items()},
                    "note": str(fail_row.get("Validation_Notes", "Row validation failed")),
                })

        if "Completeness_Status" in df.columns:
            comp_fails = df[df["Completeness_Status"] == "FAIL (Rows Dropped)"]
            if not comp_fails.empty:
                row_exceptions.append({
                    "table": t_idx,
                    "row": "ALL",
                    "data": {},
                    "note": "Table completeness validation failed (too many rows dropped during filtering)."
                })

    calculated_total = round(calculated_total, 2)

    if balance_sheet:
        assets = _extract_value_by_keyword(combined_text, ["Total Assets", "Assets"])
        liabs = _extract_value_by_keyword(combined_text, ["Total Liabilities", "Total Equity and Liabilities", "Liabilities"])
        
        printed_grand_total = 0.0
        delta = None
        
        if assets is not None and liabs is not None:
            delta = round(abs(assets - liabs), 2)
            if delta <= 2.0:
                status = "RECONCILED"
            else:
                status = "UNRECONCILED"
                row_exceptions.append({
                    "table": "BALANCE_SHEET",
                    "row": "ALL",
                    "data": {},
                    "note": f"Balance Sheet Mismatch: Assets={assets}, Liabilities={liabs}"
                })
        else:
            status = "UNRECONCILED"
            row_exceptions.append({
                "table": "BALANCE_SHEET",
                "row": "ALL",
                "data": {},
                "note": f"Could not find both Assets and Liabilities in text. Assets={assets}, Liabs={liabs}"
            })
            
        if len(row_exceptions) > 0:
            status = "UNRECONCILED"
    else:
        printed_grand_total = extract_grand_total(combined_text)

        if printed_grand_total is not None and calculated_total > 0:
            delta = round(abs(calculated_total - printed_grand_total), 2)
            tolerance_ok = delta <= 2.0
        else:
            delta = None
            tolerance_ok = False

        math_ok = len(row_exceptions) == 0

        if not all_dfs:
            status = "RECONCILED"
        elif tolerance_ok and math_ok:
            status = "RECONCILED"
        else:
            status = "UNRECONCILED"

    filename_lower = src.name.lower()
    first_page_text = combined_text[:1000].lower() if combined_text else ""
    
    is_legal_financial = any(kw in filename_lower for kw in ["panchnama", "balance sheet", "enclosure", "statement"]) or \
                         any(kw in first_page_text for kw in ["panchnama", "balance sheet", "enclosure", "statement"])
                         
    if is_legal_financial and len(row_exceptions) > 0:
        status = "UNRECONCILED"
        row_exceptions.append({
            "table": "GLOBAL",
            "row": "ALL",
            "data": {},
            "note": "Requires Human Sign-Off"
        })

    exc_entry = {
        "filename": src.name,
        "status": status,
        "Calculated_Total": calculated_total,
        "Printed_Grand_Total": printed_grand_total,
        "delta": delta,
        "row_exceptions": row_exceptions,
    }

    return status, exc_entry
