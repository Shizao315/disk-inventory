"""Actual Qt WebEngine/WebChannel and current-directory watcher integration."""
from pathlib import Path
import hashlib
import json
import os
import sys
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import dev_scan
import desktop_viewer as desktop
from refresh_report import refresh_report
from PySide6.QtCore import QMimeData

OUT = ROOT / 'test-output' / 'desktop'
OUT.mkdir(parents=True, exist_ok=True)
fixture = OUT / ('fixture-' + str(time.time_ns()))
fixture.mkdir()
(fixture / 'delete-me.txt').write_text('abc', encoding='utf-8')
(fixture / "中文&'记录.txt").write_text('hello', encoding='utf-8')
report = OUT / ('scan-' + fixture.name + '.html')
dev_scan.generate([str(fixture)], report)
original_hash = hashlib.sha256(report.read_bytes()).hexdigest()
app = desktop.QApplication([])
window = desktop.Viewer(str(report))
loaded_states = []
window.view.loadFinished.connect(lambda ok: loaded_states.append(ok))
window.page.loadingChanged.connect(lambda info: print('Load:', info.status(), info.errorCode(), info.errorString(), flush=True))
window.page.renderProcessTerminated.connect(lambda status, code: print('Renderer terminated:',status,code,flush=True))
window.show()
clipboard = desktop.QApplication.clipboard()
saved = QMimeData()
if clipboard.mimeData():
    for fmt in clipboard.mimeData().formats():
        saved.setData(fmt, clipboard.mimeData().data(fmt))


def pump_until(check, timeout=35):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if check():
            return
        time.sleep(.025)
    raise AssertionError('Timed out waiting for real embedded UI')


def js(expression):
    result = []
    window.page.runJavaScript(expression, lambda value: result.append(value))
    pump_until(lambda: bool(result))
    return result[0]


def node_count():
    return js('document.getElementById("file-count").textContent')


checks = []
try:
    print('Waiting for real embedded page load', flush=True)
    pump_until(lambda: bool(loaded_states))
    assert loaded_states[-1], 'Embedded report failed to load: ' + repr(window.page.navigation_diagnostics)
    print('Embedded load finished; waiting for native bridge', flush=True)
    pump_until(lambda: js('Boolean(window.diskInventory && window.diskInventory.ready && window.diskInventoryHost)'))
    assert node_count() == '2'
    checks.append('actual Qt WebEngine loaded trusted report and WebChannel')
    js('document.querySelector("#size-vrows .filename").click()')
    pump_until(lambda: clipboard.text() == "中文&'记录.txt")
    checks.append('actual name click reached Windows clipboard')
    with mock.patch.object(desktop.os, 'startfile') as opened:
        js('document.querySelector("#size-vrows .reveal").click()')
        pump_until(lambda: opened.called)
        assert opened.call_args.args == (str(fixture),)
    checks.append('actual reveal button reached native directory shell adapter')
    window.live.setChecked(True)
    pump_until(lambda: bool(window.bridge.watcher.directories()))
    assert window.bridge.watcher.directories() == [str(fixture)]
    (fixture / 'delete-me.txt').unlink()
    pump_until(lambda: node_count() == '1')
    checks.append('Windows directory notification removed externally deleted file')
    (fixture / 'new.txt').write_bytes(b'123456789')
    pump_until(lambda: node_count() == '2')
    pump_until(lambda: js('document.querySelector("#size-vrows .filename").textContent') == 'new.txt')
    checks.append('Windows directory notification added file and updated numeric ranking')
    (fixture / 'new.txt').write_bytes(b'x')
    window.bridge.refresh()
    pump_until(lambda: js('document.querySelector("#size-vrows .filename").textContent') == "中文&'记录.txt")
    checks.append('manual metadata refresh reordered changed size')
    with mock.patch.object(desktop.os, 'scandir', side_effect=PermissionError('synthetic')):
        result = desktop.directory_snapshot(str(fixture), False)
    assert result['error'] and not result['entries']
    checks.append('failed directory read retains records rather than claiming deletion')
    assert not window.page.acceptNavigationRequest(desktop.QUrl('https://example.com/'), None, True)
    assert not window.page.acceptNavigationRequest(desktop.QUrl.fromLocalFile(str(fixture / 'new.txt')), None, True)
    checks.append('native bridge cannot navigate to remote or other local page')
    assert hashlib.sha256(report.read_bytes()).hexdigest() == original_hash
    checks.append('original report unchanged after session updates')
    # Only synthetic paths appear in this verification screenshot.
    window.grab().save(str(OUT / 'embedded-desktop.png'))
    (OUT / 'desktop-results.json').write_text(json.dumps({'status':'PASS','checks':checks,'source_report_sha256':original_hash,'watch_scope':'current directory only','original_unchanged':True}, indent=2), encoding='utf-8')
    print(json.dumps({'status':'PASS','checks':checks}))
finally:
    window.live.setChecked(False)
    window.close()
    app.processEvents()
    clipboard.setMimeData(saved)
    # Only this test's small, verified fixture is cleaned; no recursive delete.
    assert fixture.parent == OUT and fixture.name.startswith('fixture-')
    for child in fixture.iterdir():
        assert child.is_file()
        child.unlink()
    fixture.rmdir()
