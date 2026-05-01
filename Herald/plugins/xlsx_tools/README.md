# XLSX Tools Plugin

Adds workbook tools for Herald:

- `xlsx_tools_list_sheets(path)`
- `xlsx_tools_preview_csv(path, sheet=null, max_rows=30, max_cols=20, data_only=false, include_formulas=true)`
- `xlsx_tools_export_csv(path, sheet=null, output_dir=null, data_only=false, include_formulas=true)`
- `xlsx_tools_set_cell(path, sheet, cell, value, output_path=null)`
- `xlsx_tools_update_from_csv(path, csv_path, sheet=null, output_path=null, clear_sheet=true, infer_types=true)`
- `xlsx_tools_create_from_csv(csv_path, output_path, sheet="Sheet1", infer_types=true)`

Typical workflow:

1. Call `xlsx_tools_list_sheets` to inspect workbook structure.
2. Call `xlsx_tools_preview_csv` to feed a small sheet preview to the model.
3. Call `xlsx_tools_export_csv` when the model should inspect or edit the sheet as CSV.
4. Use `fs_read`/`fs_write` on the CSV when text editing is easier.
5. Call `xlsx_tools_update_from_csv` to write CSV rows back into a workbook.

Formula cells are included by default in CSV previews and exports. Format:

```text
<calculated value> | <formula without leading equals sign>
```

Example:

```csv
name,total
alpha,12 | A2+B2
```

`openpyxl` does not calculate formulas itself. It reads cached calculated values
stored in the workbook by Excel/LibreOffice. If no cached value exists, the CSV
cell keeps the formula and leaves the left side empty:

```csv
alpha, | A2+B2
```

By default CSV exports go to:

```text
.Herald/plugin-data/xlsx_tools/exports/<workbook-name>/
```

Edits write to `<original-name>.edited.xlsx` unless `output_path` is provided.

The plugin requires `openpyxl`.
