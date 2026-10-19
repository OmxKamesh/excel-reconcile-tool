# Sheet Reconcile

**Find the missing unit without losing the row that explains it.**

A small Claude Code skill and standalone Python CLI for reconciling opening stock or invoice balances, signed movements, and closing balances. It produces exact decimal calculations and inspectable CSV row evidence. No dependencies, API keys, uploads or account access.

## A 30-second example

From this repository directory, with Python 3.9+:

```sh
python scripts/reconcile.py --opening examples/opening.csv --movements examples/movements.csv --closing examples/closing-broken.csv
```

The synthetic widget ledger starts at 10, receives 5, ships 3, and closes at 11. The report identifies:

```text
WIDGET [each]: discrepancy; expected=12; actual=11; difference=-1
  opening opening.csv:2 amount=10
  movement movements.csv:2 amount=5 id=receipt-001
  movement movements.csv:3 amount=-3 id=shipment-001
  closing closing-broken.csv:2 amount=11
```

Exit code is **1**. The cable balance `0.1 + 0.2 = 0.3` matches exactly. Replay using `--closing examples/closing-matched.csv` for exit **0**. This second fixture is a separate synthetic scenario, not an assertion that changing a real closing balance is the correct repair.

Add `--format json` for structured evidence or `--format markdown` for a readable table with row citations. Add an explicitly chosen `--tolerance 0.01` for an absolute per-key tolerance; the default is zero. Reports go to stdout; inputs remain unchanged. Use `--output report.json` to save to a new file without overwriting an existing file. Choose the extension to match your format.

## Install in Claude Code

Copy this repository's `SKILL.md`, `scripts/` and `references/` into `~/.claude/skills/sheet-reconcile/` for personal use, or `.claude/skills/sheet-reconcile/` inside your project for project use. Copying the entire repository into that folder also works. On Windows, `~` refers to your user profile directory. Existing installations should be reviewed before replacement.

Invoke explicitly:

```text
/sheet-reconcile opening.csv movements.csv closing.csv
```

The skill is deliberately explicit-only (`disable-model-invocation: true`). It guides Claude to agree on signs and cutoffs, run the helper, and distinguish observed discrepancies from proposed corrections. The portable CLI also runs independently; no compatibility with other agents' skill discovery is claimed.

## Input contract

Snapshots: `entity_id,unit,amount`. Movements: `movement_id,entity_id,unit,amount,description`.

Each entity/unit needs an opening and closing row. Positive movements increase a balance; negative movements decrease it. Invoice example: `INV-001,USD,125.50` opening, payment movement `payment-1,INV-001,USD,-25.50,partial payment`, closing `INV-001,USD,100.00`. Confirm that convention matches your accounting export.

Strict validation rejects duplicate IDs, duplicate snapshot keys, malformed columns, missing fields, NaN/infinity and unsupported decimal formats. Different units/currencies are never added together. See [the full contract](references/csv-contract.md).

## Checks and limits

```sh
python -m unittest discover -s tests -v
```

Behavioral tests cover decimal precision, signed differences, mixed currencies, missing snapshots, duplicate records, malformed data, tolerance, exit statuses and unchanged inputs.

This is an arithmetic reconciliation tool, not an audit or accounting certification. It cannot prove an export is complete, identify duplicated transactions with different IDs, infer date boundaries, convert currencies/units or check the physical stock. It supports normalized CSVs, not live Sheets or XLSX. Data is loaded in memory; use modest exports. Arithmetic bounds are documented; unusually large precision requires adapting and testing the contract. A matching report can still reflect incomplete or incorrectly classified source data.

Reports contain supplied business identifiers and quantities. Keep real data and generated reports out of public repositories. All committed examples here are synthetic.

License decision pending: no open-source license is granted by this repository. Public visibility does not itself grant redistribution rights.
