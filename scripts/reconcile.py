#!/usr/bin/env python3
"""Strict, read-only CSV roll-forward reconciliation. Python standard library only."""
import argparse
import csv
import html
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re
import sys

NUMBER = re.compile(r"[+-]?\d{1,40}(?:\.\d{1,12})?\Z", re.ASCII)


class InputError(ValueError):
    pass


def number(value, where):
    if not NUMBER.fullmatch(value):
        raise InputError(f"{where}: expected plain decimal (max 40 integer/12 fractional digits)")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise InputError(f"{where}: invalid decimal") from exc
    if not result.is_finite():
        raise InputError(f"{where}: nonfinite decimal")
    return result


def decimal_text(value):
    return format(value, 'f') if value else '0'


def read_rows(path, movement=False):
    required = ['movement_id', 'entity_id', 'unit', 'amount', 'description'] if movement else ['entity_id', 'unit', 'amount']
    rows, seen = [], set()
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle, strict=True)
        if reader.fieldnames != required:
            raise InputError(f"{Path(path).name}: header must be {','.join(required)}")
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            start = reader.line_num
            where = f"{Path(path).name}:{start}"
            if None in row or any(v is None or not v.strip() for v in row.values()):
                raise InputError(f"{where}: missing/extra/empty field")
            if any(v != v.strip() or any(ord(c) < 32 for c in v) for v in row.values()):
                raise InputError(f"{where}: whitespace/control characters in field")
            identity = row['movement_id'] if movement else (row['entity_id'], row['unit'])
            if identity in seen:
                raise InputError(f"{where}: duplicate {'movement id' if movement else 'snapshot key/unit'}")
            seen.add(identity)
            row['value'] = number(row['amount'], where)
            row['source'] = {'file': Path(path).name, 'line': start, 'line_end': reader.line_num}
            rows.append(row)
    return rows


def reconcile(opening, movements, closing, tolerance='0'):
    tol = number(tolerance, 'tolerance')
    if tol < 0:
        raise InputError('tolerance must be nonnegative')
    starts = read_rows(opening)
    changes = read_rows(movements, movement=True)
    ends = read_rows(closing)
    initial = {(r['entity_id'], r['unit']): r for r in starts}
    final = {(r['entity_id'], r['unit']): r for r in ends}
    grouped = {}
    for row in changes:
        grouped.setdefault((row['entity_id'], row['unit']), []).append(row)
    keys = sorted(set(initial) | set(final) | set(grouped))
    results = []
    with localcontext() as context:
        context.prec = 100 + len(str(len(changes) + 1))
        for key in keys:
            first, last = initial.get(key), final.get(key)
            moves = grouped.get(key, [])
            net = sum((r['value'] for r in moves), Decimal(0))
            expected = first['value'] + net if first else None
            difference = last['value'] - expected if first and last else None
            status = 'missing_snapshot' if first is None or last is None else ('matched' if abs(difference) <= tol else 'discrepancy')
            evidence = []
            for role, rows in [('opening', [first] if first else []), ('movement', moves), ('closing', [last] if last else [])]:
                for row in rows:
                    entry = dict(row['source'], role=role, amount=row['amount'])
                    if 'movement_id' in row:
                        entry['movement_id'] = row['movement_id']
                        entry['description'] = row['description']
                    evidence.append(entry)
            results.append({'entity_id': key[0], 'unit': key[1], 'status': status,
                            'opening': decimal_text(first['value']) if first else None,
                            'net_movement': decimal_text(net),
                            'expected_closing': decimal_text(expected) if expected is not None else None,
                            'actual_closing': decimal_text(last['value']) if last else None,
                            'difference': decimal_text(difference) if difference is not None else None,
                            'missing': [name for name, row in [('opening', first), ('closing', last)] if row is None],
                            'evidence': evidence})
    issues = sum(r['status'] != 'matched' for r in results)
    return {'schema_version': 1, 'status': 'empty' if not results else ('discrepancies' if issues else 'matched'),
            'equation': 'opening + signed movements = closing', 'tolerance': decimal_text(tol),
            'keys_checked': len(results), 'issues': issues, 'results': results}


def human(report):
    lines = [f"Sheet Reconcile: {report['status']}", f"Keys: {report['keys_checked']}; issues: {report['issues']}; tolerance: {report['tolerance']}"]
    for row in report['results']:
        lines.append(f"{row['entity_id']} [{row['unit']}]: {row['status']}; expected={row['expected_closing']}; actual={row['actual_closing']}; difference={row['difference']}")
        if row['missing']:
            lines.append('  Missing snapshot: ' + ', '.join(row['missing']))
        for evidence in row['evidence']:
            lines.append(f"  {evidence['role']} {evidence['file']}:{evidence['line']} amount={evidence['amount']}" + (f" id={evidence['movement_id']}" if 'movement_id' in evidence else ''))
    return '\n'.join(lines)


def markdown(report):
    def cell(value):
        return html.escape(str(value)).replace('|', '&#124;').replace('`', '&#96;').replace('*', '&#42;').replace('_', '&#95;').replace('[', '&#91;').replace(']', '&#93;')
    lines = ['# Sheet Reconcile', '', f"Status: **{report['status']}**. Keys: {report['keys_checked']}; issues: {report['issues']}; tolerance: {report['tolerance']}.", '',
             '| Entity | Unit | Status | Expected | Actual | Difference |', '| --- | --- | --- | --- | --- | --- |']
    for row in report['results']:
        lines.append('| ' + ' | '.join(cell(row[k]) for k in ['entity_id', 'unit', 'status', 'expected_closing', 'actual_closing', 'difference']) + ' |')
    lines += ['', '## Row evidence', '', '| Entity | Unit | Role | File:line | Amount | Movement ID | Description |', '| --- | --- | --- | --- | --- | --- | --- |']
    for row in report['results']:
        for e in row['evidence']:
            lines.append('| ' + ' | '.join(cell(x) for x in [row['entity_id'], row['unit'], e['role'], f"{e['file']}:{e['line']}", e['amount'], e.get('movement_id', ''), e.get('description', '')]) + ' |')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opening', required=True)
    parser.add_argument('--movements', required=True)
    parser.add_argument('--closing', required=True)
    parser.add_argument('--tolerance', default='0', help='Absolute per-key tolerance; default exact')
    parser.add_argument('--format', choices=['text', 'json', 'markdown'], default='text')
    parser.add_argument('--output', help='Optional new output file; existing files are never overwritten')
    args = parser.parse_args(argv)
    try:
        report = reconcile(args.opening, args.movements, args.closing, args.tolerance)
    except (InputError, OSError, UnicodeError, csv.Error) as exc:
        print(json.dumps({'schema_version': 1, 'status': 'invalid_input', 'error': str(exc)}) if args.format == 'json' else f'Invalid input: {exc}', file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, ensure_ascii=True) if args.format == 'json' else (markdown(report) if args.format == 'markdown' else human(report))
    if args.output:
        try:
            with Path(args.output).open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(rendered + '\n')
        except OSError as exc:
            print(f'Output error: {exc}', file=sys.stderr)
            return 2
    else:
        print(rendered)
    return 0 if report['status'] == 'matched' else (2 if report['status'] == 'empty' else 1)


if __name__ == '__main__':
    sys.exit(main())
