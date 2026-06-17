import io
import re
import pandas as pd
from azure.ai.documentintelligence import DocumentIntelligenceClient
from src.utils.helpers import parse_indian_currency, validate_row_math

def run_azure_ocr(
    image_bytes: bytes,
    azure_client: DocumentIntelligenceClient,
    page_num: int = 1,
) -> tuple[str, list[pd.DataFrame]]:
    poller = azure_client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=io.BytesIO(image_bytes),
        content_type="image/png",
    )
    result = poller.result()

    text_parts = []
    if result.paragraphs:
        for para in result.paragraphs:
            if para.content:
                text_parts.append(para.content)
    elif result.pages:
        for page in result.pages:
            for line in page.lines or []:
                text_parts.append(line.content)
    text = "\n".join(text_parts).strip()

    dataframes = []
    if result.tables:
        for table in result.tables:
            row_count = table.row_count
            col_count = table.column_count

            grid = [[""] * col_count for _ in range(row_count)]
            y_coords = [0.0] * row_count

            for cell in table.cells:
                r = cell.row_index
                c = cell.column_index
                if r < row_count and c < col_count:
                    content = cell.content or ""
                    
                    conf = getattr(cell, 'confidence', 1.0)
                    if conf is not None and conf < 0.85:
                        content = f"<low_conf>{content}</low_conf>"
                        
                    grid[r][c] = content
                    
                    if y_coords[r] == 0.0 and hasattr(cell, 'bounding_regions') and cell.bounding_regions:
                        polygon = cell.bounding_regions[0].polygon
                        if polygon and len(polygon) >= 2:
                            y_coords[r] = round(polygon[1], 2)

            header_indices = {
                cell.column_index
                for cell in table.cells
                if getattr(cell, "kind", None) == "columnHeader" and cell.row_index == 0
            }
            has_headers = len(header_indices) == col_count and col_count > 0
            
            merged_headers = False
            if has_headers and row_count >= 2:
                row0_pure_str = all(not re.search(r'\d', str(cell)) for cell in grid[0])
                row1_pure_str = all(not re.search(r'\d', str(cell)) for cell in grid[1])
                if row0_pure_str and row1_pure_str:
                    for c in range(col_count):
                        grid[0][c] = (str(grid[0][c]) + " " + str(grid[1][c])).strip()
                    merged_headers = True

            if has_headers:
                headers = grid[0]
                if merged_headers:
                    df = pd.DataFrame(grid[2:], columns=headers)
                    y_coords_data = y_coords[2:]
                    expected_data_rows = row_count - 2
                else:
                    df = pd.DataFrame(grid[1:], columns=headers)
                    y_coords_data = y_coords[1:]
                    expected_data_rows = row_count - 1
            else:
                df = pd.DataFrame(grid)
                y_coords_data = y_coords
                expected_data_rows = row_count

            df.replace(r"^\s*$", pd.NA, regex=True, inplace=True)
            valid_rows = df.dropna(how='all').index
            df = df.loc[valid_rows].copy()
            df.fillna("", inplace=True)
            
            y_coords_filtered = [y_coords_data[i] for i in valid_rows]

            if df.shape[0] < 2 or df.shape[1] < 2:
                continue

            total_cells = df.size
            empty_cells = (
                df.astype(str).replace(r"^\s*$", "", regex=True).eq("").sum().sum()
            )
            empty_ratio = empty_cells / total_cells if total_cells > 0 else 0

            if has_headers and empty_ratio > 0.90:
                continue
            if not has_headers and empty_ratio > 0.65:
                continue

            if df.shape[1] == 2 and not has_headers:
                text_content = " ".join(df.astype(str).values.flatten())
                digit_count = sum(c.isdigit() for c in text_content)
                if digit_count < 5:
                    continue

            final_rows = df.shape[0]
            missing_rows = expected_data_rows - final_rows
            tolerance = max(2, int(expected_data_rows * 0.10))
            
            if missing_rows >= tolerance:
                status = "FAIL (Rows Dropped)"
            else:
                status = "PASS"
                
            df["Completeness_Status"] = status
            df.insert(0, "Y_Coord", y_coords_filtered)
            df.insert(0, "Page_Num", page_num)

            for col in df.columns:
                if col in ("Page_Num", "Y_Coord"):
                    continue

                def try_parse(val):
                    # Handle pandas objects (Series/DataFrame) and missing values safely
                    try:
                        # pd.isna may return a boolean or an array/Series
                        is_na = pd.isna(val)
                    except Exception:
                        is_na = False

                    if isinstance(is_na, (pd.Series, pd.DataFrame)):
                        if getattr(is_na, "all", lambda: False)():
                            return val
                    else:
                        if is_na:
                            return val

                    # Convert to string safely
                    try:
                        sval = str(val)
                    except Exception:
                        return val

                    if any(c.isdigit() for c in sval):
                        parsed = parse_indian_currency(sval)
                        if isinstance(parsed, float):
                            return parsed
                    return val

                df[col] = df[col].apply(try_parse)

            df = validate_row_math(df)
            dataframes.append(df)

    return text, dataframes
