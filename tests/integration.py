"""Run the real Windows executable against a bounded, synthetic fixture."""
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'test-output'
EXE = BASE / 'dist' / 'DiskInventory.exe'
KERNEL = ctypes.WinDLL('kernel32', use_last_error=True)
KERNEL.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
KERNEL.CreateHardLinkW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
KERNEL.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]


def read_report(path):
    html = path.read_text(encoding='utf-8')
    payload = re.search(r'<script id="scan-data" type="application/json">(.*?)</script>', html, re.S)
    if not payload:
        raise AssertionError('Embedded scan data missing')
    return json.loads(payload.group(1))


def paths(data):
    result = {}
    names = []
    for n in data['nodes']:
        full = n[1] if n[0] < 0 else names[n[0]].rstrip('\\') + '\\' + n[1]
        names.append(full)
        result[full] = n
    return result


class ScannerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(exist_ok=True)
        cls.root = OUT / ('fixture-' + str(time.time_ns()))
        cls.root.mkdir()
        (cls.root / '资料').mkdir()
        (cls.root / 'empty').mkdir()
        (cls.root / 'hidden-dir').mkdir()
        (cls.root / 'visible.txt').write_bytes(b'abc')
        (cls.root / 'zero').write_bytes(b'')
        (cls.root / '资料' / "中文&'记录.bin").write_bytes(b'x' * 1024)
        (cls.root / 'hidden.txt').write_bytes(b'hidden!')
        (cls.root / 'hidden-dir' / 'child.txt').write_bytes(b'child')
        for path in [cls.root / 'hidden.txt', cls.root / 'hidden-dir']:
            if not KERNEL.SetFileAttributesW(str(path), 2):
                raise ctypes.WinError(ctypes.get_last_error())
        cls.hardlink = cls.root / 'hard-link.txt'
        if not KERNEL.CreateHardLinkW(str(cls.hardlink), str(cls.root / 'visible.txt'), None):
            raise ctypes.WinError(ctypes.get_last_error())
        cls.big = cls.root / 'large-sparse.bin'
        import msvcrt
        with cls.big.open('wb') as f:
            handle = msvcrt.get_osfhandle(f.fileno())
            got = ctypes.c_uint32()
            if not KERNEL.DeviceIoControl(handle, 0x900C4, None, 0, None, 0, ctypes.byref(got), None):
                raise ctypes.WinError(ctypes.get_last_error())
            f.truncate(5 * 1024**3 + 17)
        cls.long = cls.root
        for i in range(5):
            cls.long = cls.long / ('long-segment-' + str(i) + '-' + 'x' * 40)
            os.mkdir('\\\\?\\' + str(cls.long))
        with open('\\\\?\\' + str(cls.long / 'long-file.txt'), 'wb') as f:
            f.write(b'long')
        cls.junction = cls.root / 'loop'
        proc = subprocess.run(['cmd', '/c', 'mklink', '/J', str(cls.junction), str(cls.root)], capture_output=True)
        if proc.returncode:
            raise AssertionError('Could not create bounded junction fixture')
        cls.expected_visible = 3 + 0 + 1024 + 3 + 5 * 1024**3 + 17 + 4
        cls.normal = OUT / 'scan-visible.html'
        cls.including = OUT / 'scan-hidden.html'
        for hidden, report in [(False, cls.normal), (True, cls.including)]:
            args = [str(EXE), '--root', str(cls.root), '--output', str(report), '--engine', 'directory']
            if hidden:
                args += ['--include-hidden']
            proc = subprocess.run(args, capture_output=True, timeout=60)
            if proc.returncode != 0:
                raise AssertionError(f'Scan failed: code={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}')
        cls.visible_data = read_report(cls.normal)
        cls.hidden_data = read_report(cls.including)
        (OUT / 'fixture-info.json').write_text(json.dumps({'root': str(cls.root), 'report': str(cls.normal)}, ensure_ascii=False), encoding='utf-8')

    def test_hidden_filter_and_descendants(self):
        visible = paths(self.visible_data)
        hidden = paths(self.hidden_data)
        self.assertNotIn(str(self.root / 'hidden.txt'), visible)
        self.assertNotIn(str(self.root / 'hidden-dir'), visible)
        self.assertNotIn(str(self.root / 'hidden-dir' / 'child.txt'), visible)
        self.assertIn(str(self.root / 'hidden.txt'), hidden)
        self.assertIn(str(self.root / 'hidden-dir' / 'child.txt'), hidden)
        self.assertEqual(len([n for n in self.visible_data['nodes'] if not n[2]]), 6)

    def test_lengths_totals_and_hardlinks(self):
        records = paths(self.visible_data)
        self.assertEqual(int(records[str(self.big)][3]), 5 * 1024**3 + 17)
        self.assertEqual(int(records[str(self.hardlink)][3]), 3)
        self.assertEqual(int(records[str(self.root)][3]), self.expected_visible)
        self.assertEqual(records[str(self.root / 'zero')][3], '0')
        self.assertTrue(records[str(self.root / 'empty')][2])

    def test_link_is_recorded_without_following(self):
        records = paths(self.visible_data)
        self.assertEqual(records[str(self.junction)][7], 'link_not_followed')
        self.assertFalse(any(p.startswith(str(self.junction) + '\\') for p in records))
        self.assertFalse(records[str(self.root)][9])

    def test_timestamps_unicode_and_long_paths(self):
        import datetime
        records = paths(self.visible_data)
        node = records[str(self.root / 'visible.txt')]
        modified = datetime.datetime.fromisoformat(node[5].replace('Z', '+00:00')).timestamp()
        self.assertAlmostEqual(modified, (self.root / 'visible.txt').stat().st_mtime, delta=0.01)
        created = datetime.datetime.fromisoformat(node[4].replace('Z', '+00:00')).timestamp()
        stat = (self.root / 'visible.txt').stat()
        self.assertAlmostEqual(created, getattr(stat, 'st_birthtime', stat.st_ctime), delta=0.01)
        self.assertIn(str(self.long / 'long-file.txt'), records)
        self.assertIn(str(self.root / '资料' / "中文&'记录.bin"), records)

    def test_duplicate_roots_and_self_output(self):
        report = self.root / 'self.html'
        proc = subprocess.run([str(EXE), '--root', str(self.root / '资料'), '--root', str(self.root), '--root', str(self.root), '--output', str(report)], capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        data = read_report(report)
        records = paths(data)
        self.assertEqual(len([n for n in data['nodes'] if n[0] < 0]), 1)
        self.assertNotIn(str(report), records)
        self.assertNotIn(str(report) + '.tmp', records)

    def test_invalid_input_fails_without_report(self):
        target = OUT / 'must-not-exist.html'
        proc = subprocess.run([str(EXE), '--root', str(self.root / 'missing'), '--output', str(target)], capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(target.exists())

    def test_mft_request_reports_fallback_for_folder(self):
        report = OUT / 'fallback.html'
        proc = subprocess.run([str(EXE), '--root', str(self.root / 'empty'), '--output', str(report), '--engine', 'mft'], capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0)
        data = read_report(report)
        self.assertTrue(any('native' in x.lower() or 'Win32' in x for x in data['engines']))
        self.assertTrue(any('MFT requires' in x for x in data['notes']))

    def test_native_gui_generates_report(self):
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.SetProcessDPIAware()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetDlgItem.restype = wintypes.HWND
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = wintypes.LPARAM
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.IsWindowEnabled.argtypes = [wintypes.HWND]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]

        def rect(hwnd):
            bounds = wintypes.RECT()
            self.assertTrue(user.GetWindowRect(hwnd, ctypes.byref(bounds)))
            return bounds

        report = OUT / ('gui-' + self.root.name + '.html')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # Start hidden; no desktop focus or modal success prompt.
        proc = subprocess.Popen([str(EXE), '--gui', '--root', str(self.root / 'empty'), '--output', str(report)], startupinfo=startup)
        window = None
        try:
            for _ in range(100):
                found = []
                @callback_type
                def visit(hwnd, _):
                    pid = wintypes.DWORD()
                    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == proc.pid and user.GetDlgItem(hwnd, 108):
                        found.append(hwnd)
                    return True
                user.EnumWindows(visit, 0)
                if found:
                    window = found[0]
                    break
                if proc.poll() is not None:
                    self.fail('Native GUI exited before creating controls')
                time.sleep(0.05)
            self.assertIsNotNone(window, 'Native GUI window did not initialize')
            root_control = user.GetDlgItem(window, 101)
            output_control = user.GetDlgItem(window, 106)
            browse_control = user.GetDlgItem(window, 102)
            status_control = user.GetDlgItem(window, 111)
            resize_styles = 0x00040000 | 0x00010000  # WS_THICKFRAME and WS_MAXIMIZEBOX
            self.assertEqual(user.GetWindowLongW(window, -16) & resize_styles, resize_styles)
            self.assertTrue(user.GetWindowLongW(window, -20) & 0x10)  # WS_EX_ACCEPTFILES
            frame = rect(window)
            width, height = frame.right - frame.left, frame.bottom - frame.top
            root, output = rect(root_control), rect(output_control)
            browse, status = rect(browse_control), rect(status_control)
            keep_position = 0x0002 | 0x0004 | 0x0010  # SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE
            self.assertTrue(user.SetWindowPos(window, None, 0, 0, width + 160, height + 80, keep_position))
            self.assertEqual(rect(root_control).right, root.right + 160)
            self.assertEqual(rect(root_control).bottom, root.bottom + 80)
            self.assertEqual(rect(output_control).right, output.right + 160)
            self.assertEqual(rect(browse_control).left, browse.left + 160)
            self.assertEqual(rect(status_control).top, status.top + 80)
            self.assertTrue(user.SetWindowPos(window, None, 0, 0, width, height, keep_position))
            self.assertEqual(rect(root_control).right, root.right)
            self.assertEqual(rect(root_control).bottom, root.bottom)
            buffer = ctypes.create_unicode_buffer(32768)
            for _ in range(100):
                user.SendMessageW(root_control, 0x0D, len(buffer), ctypes.cast(buffer, ctypes.c_void_p).value)
                if buffer.value == str(self.root / 'empty'):
                    break
                time.sleep(0.05)
            self.assertEqual(buffer.value, str(self.root / 'empty'))
            self.assertFalse(user.IsWindowEnabled(user.GetDlgItem(window, 115)))
            user.SendMessageW(window, 0x111, 116, 0)
            self.assertEqual(user.SendMessageW(root_control, 0x0E, 0, 0), 0)
            user.SendMessageW(root_control, 0x0C, 0, ctypes.cast(buffer, ctypes.c_void_p).value)
            user.SendMessageW(window, 0x111, 108, 0)
            for _ in range(200):
                if report.exists() and user.IsWindowEnabled(user.GetDlgItem(window, 110)):
                    break
                time.sleep(0.05)
            self.assertTrue(report.exists(), 'GUI start button did not generate report')
            self.assertTrue(user.IsWindowEnabled(user.GetDlgItem(window, 110)))
            self.assertTrue(user.IsWindowEnabled(user.GetDlgItem(window, 115)))
            self.assertEqual(len(read_report(report)['nodes']), 1)
            user.PostMessageW(window, 0x10, 0, 0)
            self.assertEqual(proc.wait(timeout=10), 0)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == '__main__':
    import hashlib
    program = unittest.main(verbosity=2, exit=False)
    result = program.result
    OUT.mkdir(exist_ok=True)
    (OUT / 'integration-results.json').write_text(json.dumps({
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'exe_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest(),
        'checks': sorted(name for name in dir(ScannerIntegration) if name.startswith('test_')),
    }, indent=2), encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
