import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'reconcile.py'
spec = importlib.util.spec_from_file_location('reconcile', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_case(self, start='A,each,0.1\n', moves='m1,A,each,0.2\n', end='A,each,0.3\n', tolerance='0'):
        files = []
        for name, header, body in [('opening.csv', 'entity_id,unit,amount\n', start), ('moves.csv', 'movement_id,entity_id,unit,amount,description\n', moves), ('closing.csv', 'entity_id,unit,amount\n', end)]:
            path = self.root / name
            body = ''.join(line + ',synthetic\n' for line in body.splitlines()) if name == 'moves.csv' else body
            path.write_text(header + body, encoding='utf-8')
            files.append(path)
        return module.reconcile(*files, tolerance=tolerance)

    def test_exact_decimal_and_row_evidence(self):
        report = self.run_case()
        self.assertEqual(report['status'], 'matched')
        row = report['results'][0]
        self.assertEqual(row['expected_closing'], '0.3')
        self.assertEqual(row['difference'], '0')
        self.assertEqual(row['evidence'][1], {'file': 'moves.csv', 'line': 2, 'line_end': 2, 'role': 'movement', 'amount': '0.2', 'movement_id': 'm1', 'description': 'synthetic'})

    def test_discrepancy_sign_and_signed_movements(self):
        row = self.run_case('A,each,10\n', 'm1,A,each,5\nm2,A,each,-3\n', 'A,each,11\n')['results'][0]
        self.assertEqual((row['status'], row['expected_closing'], row['difference']), ('discrepancy', '12', '-1'))

    def test_currency_units_never_combined(self):
        report = self.run_case('invoice-1,USD,10\ninvoice-1,EUR,20\n', 'payment,invoice-1,USD,-4\n', 'invoice-1,USD,6\ninvoice-1,EUR,20\n')
        self.assertEqual(report['keys_checked'], 2)
        self.assertEqual(report['status'], 'matched')

    def test_unit_mismatch_requires_explicit_snapshots(self):
        report = self.run_case('A,each,1\n', 'm1,A,box,1\n', 'A,each,1\n')
        self.assertEqual(report['status'], 'discrepancies')
        self.assertEqual(report['results'][0]['missing'], ['opening', 'closing'])

    def test_missing_snapshot_not_assumed_zero(self):
        row = self.run_case('', 'm1,A,each,1\n', 'A,each,1\n')['results'][0]
        self.assertEqual(row['status'], 'missing_snapshot')
        self.assertIsNone(row['difference'])

    def test_duplicate_movement_id_rejected(self):
        with self.assertRaisesRegex(module.InputError, 'duplicate movement id'):
            self.run_case(moves='x,A,each,0.1\nx,B,each,0.1\n')

    def test_duplicate_snapshot_rejected(self):
        with self.assertRaisesRegex(module.InputError, 'duplicate snapshot'):
            self.run_case(start='A,each,0.1\nA,each,0.1\n')

    def test_nonfinite_exponents_and_malformed_decimals_rejected(self):
        for value in ['NaN', 'Infinity', '-Infinity', '1e2', '1,000', '0.1234567890123', '1' * 41, ' 1', '--2']:
            with self.subTest(value=value), self.assertRaises(module.InputError):
                self.run_case(start=f'A,each,{value}\n')

    def test_tolerance_is_explicit_and_inclusive(self):
        self.assertEqual(self.run_case(end='A,each,0.31\n', tolerance='0.01')['status'], 'matched')
        self.assertEqual(self.run_case(end='A,each,0.31\n')['status'], 'discrepancies')
        with self.assertRaises(module.InputError):
            self.run_case(tolerance='-1')

    def test_large_decimal_addition_is_exact(self):
        opening = '9999999999999999999999999999999999999999'
        row = self.run_case(f'A,each,{opening}\n', 'm,A,each,0.000000000001\n', f'A,each,{opening}.000000000001\n')['results'][0]
        self.assertEqual(row['status'], 'matched')
        self.assertEqual(row['expected_closing'], opening + '.000000000001')

    def test_empty_is_not_success(self):
        self.assertEqual(self.run_case('', '', '')['status'], 'empty')

    def test_cli_exit_codes_and_no_input_mutation(self):
        examples = ROOT / 'examples'
        before = {p.name: p.read_bytes() for p in examples.glob('*.csv')}
        for closing, expected_code, expected_status in [('closing-matched.csv', 0, 'matched'), ('closing-broken.csv', 1, 'discrepancies'), ('missing.csv', 2, 'invalid_input')]:
            completed = subprocess.run([sys.executable, str(SCRIPT), '--opening', str(examples / 'opening.csv'), '--movements', str(examples / 'movements.csv'), '--closing', str(examples / closing), '--format', 'json'], text=True, capture_output=True)
            self.assertEqual(completed.returncode, expected_code)
            self.assertEqual(json.loads(completed.stdout or completed.stderr)['status'], expected_status)
        self.assertEqual(before, {p.name: p.read_bytes() for p in examples.glob('*.csv')})

    def test_bad_header_and_extra_columns_rejected(self):
        self.run_case()
        for content in ['key,key,amount\nA,each,1\n', 'entity_id,unit,amount\nA,each,1,extra\n']:
            (self.root / 'opening.csv').write_text(content, encoding='utf-8')
            with self.assertRaises(module.InputError):
                module.reconcile(self.root / 'opening.csv', self.root / 'moves.csv', self.root / 'closing.csv')

    def test_bom_quoted_csv_and_blank_line_evidence(self):
        self.run_case()
        (self.root / 'moves.csv').write_text('\ufeffmovement_id,entity_id,unit,amount,description\n\nm1,A,each,0.2,"receipt, first"\n', encoding='utf-8')
        report = module.reconcile(self.root / 'opening.csv', self.root / 'moves.csv', self.root / 'closing.csv')
        evidence = report['results'][0]['evidence'][1]
        self.assertEqual(report['status'], 'matched')
        self.assertEqual(evidence['line'], 3)
        self.assertEqual(evidence['description'], 'receipt, first')

    def test_markdown_escapes_data_and_output_no_overwrite(self):
        report = self.run_case()
        report['results'][0]['entity_id'] = '<script>|[x](url)'
        rendered = module.markdown(report)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;&#124;&#91;x&#93;(url)', rendered)
        self.assertIn('moves.csv:2', rendered)
        output = self.root / 'report.md'
        command = [sys.executable, str(SCRIPT), '--opening', str(self.root / 'opening.csv'), '--movements', str(self.root / 'moves.csv'), '--closing', str(self.root / 'closing.csv'), '--format', 'markdown', '--output', str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = output.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(output.read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
