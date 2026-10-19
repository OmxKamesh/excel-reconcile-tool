# CSV contract and interpretation

UTF-8 (optional BOM), comma-delimited, standard CSV quoting. Headers must be exactly in this order:

| File | Header | Uniqueness |
| --- | --- | --- |
| Opening | `entity_id,unit,amount` | key + unit |
| Movements | `movement_id,entity_id,unit,amount,description` | id across the file |
| Closing | `entity_id,unit,amount` | key + unit |

Entity IDs and units are case-sensitive. Every field, including description, is required and cannot be empty or contain control characters or leading/trailing whitespace. Descriptions may contain quoted commas but not embedded newlines. A unit can be `each`, `kg`, `USD`, etc.; no conversion occurs. An entity/unit appearing anywhere requires both snapshots, even if the correct value is zero. Different units are reconciled separately. A missing unit counterpart produces a missing-snapshot issue rather than an assumed conversion.

Quantities are plain signed decimal strings with 1–40 integer digits and up to 12 fractional digits. Nonfinite values, scientific notation, thousands separators and whitespace are rejected. All arithmetic uses Decimal with sufficient precision for these limits. No float conversion or implicit rounding occurs. Tolerance is absolute, nonnegative and applied separately to every key/unit. For mixed units, default zero is safest; split files if different tolerances are needed.

Equation: `expected_closing = opening + sum(signed movements)`.
Difference: `actual_closing - expected_closing` (negative means below expected).

The tool validates syntax and arithmetic, not business semantics. It cannot tell whether a positive movement is truly a receipt or an incorrectly signed shipment. Confirm source conventions and time cutoffs before running. Repeated real movements with different IDs are not detectable as duplicates from this schema. There is no aggregation across currencies, FX conversion, tax logic, Excel/formula evaluation, date parsing, or remote spreadsheet access.

JSON schema version 1 stores decimals as strings to preserve exact values. Every result contains role-tagged evidence with file basename, physical CSV line start/end, raw numeric string, and movement ID where applicable. Keep a separate mapping when normalizing upstream exports; these lines refer to normalized input files, not the originals. Error messages identify invalid rows when parsing reaches them. Input errors stop reconciliation rather than producing partial success. Empty inputs yield status `empty` and exit 2.

Exit 0 = all supplied key/unit balances matched. Exit 1 = discrepancies or missing snapshots. Exit 2 = invalid/empty input, output errors, or command usage error. JSON reports are on stdout for completed checks; invalid-input JSON is on stderr. Argparse usage errors and output-file errors are ordinary text on stderr. Input files are never written. Use `--output` to create a new file with exclusive creation; it refuses every existing target, including inputs. Shell redirection is outside that protection and can overwrite files. Use `--format markdown` for a table with escaped data and all contributing row citations.
