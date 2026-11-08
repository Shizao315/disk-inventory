"""Exercise the independent Python scanner without starting the native EXE."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-output' / 'dev'
spec = importlib.util.spec_from_file_location('dev_scan', ROOT / 'tools' / 'dev_scan.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def read_report(path):
    text = path.read_text(encoding='utf-8')
    match = re.search(r'<script id="scan-data" type="application/json">(.*?)</script>', text, re.S)
    return json.loads(match.group(1))


def records(data):
    paths, result = [], {}
    for n in data['nodes']:
        path = n[1] if n[0] < 0 else paths[n[0]].rstrip('\\') + '\\' + n[1]
        paths.append(path)
        result[path] = n
    return result


class SourceScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.root = OUT / ('fixture-' + str(time.time_ns()))
        for name in ['', '资料', 'empty', 'hidden-dir']:
            (cls.root / name).mkdir(exist_ok=True)
        for name, content in [('visible.txt', b'abc'), ('zero', b''), ("资料/中文&'记录.bin", b'x' * 1024), ('hidden.txt', b'hidden!'), ('hidden-dir/child.txt', b'child')]:
            (cls.root / name).write_bytes(content)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.CreateHardLinkW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
        for p in [cls.root / 'hidden.txt', cls.root / 'hidden-dir']:
            if not kernel.SetFileAttributesW(str(p), 2):
                raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.CreateHardLinkW(str(cls.root / 'hard-link.txt'), str(cls.root / 'visible.txt'), None):
            raise ctypes.WinError(ctypes.get_last_error())
        cls.big = cls.root / 'large-sparse.bin'
        import msvcrt
        kernel.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        with cls.big.open('wb') as handle:
            returned = ctypes.c_uint32()
            if not kernel.DeviceIoControl(msvcrt.get_osfhandle(handle.fileno()), 0x900C4, None, 0, None, 0, ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
            handle.truncate(5 * 1024**3 + 17)
        cls.long = cls.root
        # Exceed MAX_PATH for scanner coverage while staying below OneDrive's
        # 400-character decoded path limit in this synchronized workspace.
        for i in range(3):
            cls.long = cls.long / ('long-segment-' + str(i) + '-' + 'x' * 40)
            os.mkdir(dev.native(cls.long))
        with open(dev.native(cls.long / 'long-file.txt'), 'wb') as handle:
            handle.write(b'long')
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(cls.root / 'loop'), str(cls.root)], capture_output=True)
        if made.returncode:
            raise RuntimeError('Cannot create junction fixture')
        cls.visible_report = OUT / 'scan-visible.html'
        cls.hidden_report = OUT / 'scan-hidden.html'
        cls.visible = dev.generate([str(cls.root)], cls.visible_report, overwrite=True)
        cls.hidden = dev.generate([str(cls.root)], cls.hidden_report, include_hidden=True, overwrite=True)
        (OUT / 'fixture-info.json').write_text(json.dumps({'root': str(cls.root), 'report': str(cls.visible_report)}, ensure_ascii=False), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        # Keep bounded fixtures/reports for review, but do not leave a 5-GiB
        # logical file in a potentially synchronized workspace.
        if cls.big.parent == cls.root and cls.big.name == 'large-sparse.bin':
            cls.big.unlink(missing_ok=True)

    def test_hidden_filter_and_parent_relationships(self):
        visible, hidden = records(self.visible), records(self.hidden)
        self.assertNotIn(str(self.root / 'hidden.txt'), visible)
        self.assertNotIn(str(self.root / 'hidden-dir'), visible)
        self.assertNotIn(str(self.root / 'hidden-dir' / 'child.txt'), visible)
        self.assertIn(str(self.root / 'hidden-dir' / 'child.txt'), hidden)
        self.assertEqual(sum(not n[2] for n in self.visible['nodes']), 6)
        self.assertEqual(read_report(self.visible_report), self.visible)

    def test_sizes_dates_links_and_unicode_long_path(self):
        from datetime import datetime
        items = records(self.visible)
        self.assertEqual(items[str(self.big)][3], str(5 * 1024**3 + 17))
        self.assertEqual(items[str(self.root / 'hard-link.txt')][3], '3')
        self.assertEqual(items[str(self.root)][3], str(5 * 1024**3 + 17 + 3 + 3 + 1024 + 4))
        self.assertEqual(items[str(self.root / 'zero')][3], '0')
        self.assertIn(str(self.long / 'long-file.txt'), items)
        self.assertEqual(items[str(self.root / 'loop')][7], 'link_not_followed')
        self.assertFalse(items[str(self.root)][9])
        self.assertFalse(any(p.startswith(str(self.root / 'loop') + '\\') for p in items))
        n = items[str(self.root / 'visible.txt')]
        st = (self.root / 'visible.txt').stat()
        self.assertAlmostEqual(datetime.fromisoformat(n[4].replace('Z', '+00:00')).timestamp(), st.st_birthtime, delta=.01)
        self.assertAlmostEqual(datetime.fromisoformat(n[5].replace('Z', '+00:00')).timestamp(), st.st_mtime, delta=.01)

    def test_output_exclusion_and_duplicate_roots(self):
        output = self.root / 'self.html'
        result = dev.generate([str(self.root / '资料'), str(self.root), str(self.root)], output)
        self.assertEqual(sum(n[0] < 0 for n in result['nodes']), 1)
        self.assertNotIn(str(output), records(result))
        self.assertNotIn(str(output) + '.tmp', records(result))

    def test_cancellation_preserves_known_partial_data(self):
        event = threading.Event()
        def stop_after_root(stats):
            if stats['files']:
                event.set()
        output = OUT / 'cancelled.html'
        result = dev.generate([str(self.root)], output, overwrite=True, cancel=event, progress=stop_after_root)
        self.assertTrue(result['cancelled'])
        self.assertGreater(sum(not n[2] for n in result['nodes']), 0)
        self.assertFalse(result['nodes'][0][9])
        self.assertEqual(read_report(output)['cancelled'], True)

    def test_unreadable_directory_is_not_a_complete_empty_folder(self):
        with mock.patch.object(dev.os, 'scandir', side_effect=PermissionError(13, 'synthetic permission error')):
            result = dev.scan([str(self.root / 'empty')])
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['nodes'][0][7], 'unreadable')
        self.assertFalse(result['nodes'][0][9])

    def test_output_conflicts_and_json_html_boundary(self):
        output = OUT / ('conflict-' + self.root.name + '.html')
        output.write_text('preserve', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            dev.generate([str(self.root / 'empty')], output)
        self.assertEqual(output.read_text(), 'preserve')
        temporary = OUT / ('stale-' + self.root.name + '.html.tmp')
        temporary.write_text('preserve temporary', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            dev.generate([str(self.root / 'empty')], str(temporary)[:-4])
        self.assertEqual(temporary.read_text(), 'preserve temporary')
        import io
        buffer = io.StringIO()
        text = '</script><script>bad()</script>&'
        dev.write_json(buffer, {'name': text})
        self.assertNotIn('<', buffer.getvalue())
        self.assertEqual(json.loads(buffer.getvalue())['name'], text)

    def test_real_command_line(self):
        output = OUT / ('cli-' + self.root.name + '.html')
        proc = subprocess.run([sys.executable, '-B', str(ROOT / 'tools' / 'dev_scan.py'), '--root', str(self.root / 'empty'), '--output', str(output)], capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(proc.stdout)['files'], 0)
        self.assertEqual(len(read_report(output)['nodes']), 1)

    def test_gui_start_button_produces_report(self):
        import tkinter as tk
        window = tk.Tk()
        window.withdraw()
        output = OUT / ('gui-' + self.root.name + '.html')
        app = dev.ScannerWindow(window, [str(self.root / 'empty')], str(output))
        try:
            app.start_button.invoke()
            deadline = time.monotonic() + 15
            while app.busy and time.monotonic() < deadline:
                window.update()
                time.sleep(.03)
            self.assertFalse(app.busy)
            self.assertTrue(output.exists())
            self.assertEqual(str(app.open_button.cget('state')), 'normal')
            self.assertEqual(len(read_report(output)['nodes']), 1)
        finally:
            window.destroy()


if __name__ == '__main__':
    suite = unittest.main(verbosity=2, exit=False)
    OUT.mkdir(parents=True, exist_ok=True)
    import hashlib
    (OUT / 'dev-integration-results.json').write_text(json.dumps({
        'status': 'PASS' if suite.result.wasSuccessful() else 'FAIL',
        'tests_run': suite.result.testsRun,
        'errors': len(suite.result.errors), 'failures': len(suite.result.failures),
        'source_sha256': hashlib.sha256((ROOT / 'tools' / 'dev_scan.py').read_bytes()).hexdigest(),
    }, indent=2), encoding='utf-8')
    sys.exit(0 if suite.result.wasSuccessful() else 1)
