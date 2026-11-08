"""Source prototype: embedded HTML, native clipboard/location, current-folder updates.

Optional dependency: PySide6 6.9.2. No native scanner EXE is invoked. This is
an effect prototype, not a proposal to bundle Qt into the tiny native EXE.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

# Anaconda's Python can import Qt through add_dll_directory, but its Chromium
# child also needs the environment's Library/bin in its own DLL search path.
# Scope this to this process and children; do not alter the user's system PATH.
conda_libraries = Path(sys.executable).parent / 'Library' / 'bin'
if conda_libraries.is_dir():
    os.environ['PATH'] = str(conda_libraries) + os.pathsep + os.environ.get('PATH', '')

from PySide6.QtCore import QFile, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QLabel, QMainWindow, QMessageBox, QPushButton, QToolBar
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

import dev_scan as scanner
from refresh_report import refresh_report

ROOT = Path(__file__).resolve().parents[1]


def directory_snapshot(directory, hidden, excluded=()):
    """One directory only; a failed enumeration must never mean 'all deleted'."""
    result = {'directory': directory, 'hidden': hidden, 'entries': [], 'error': None}
    keys = {scanner.path_key(p) for p in excluded}
    try:
        if scanner.directory_link(os.stat(scanner.native(directory), follow_symlinks=False)):
            raise OSError('目录链接不自动跟随；请直接选择目标目录重新扫描')
        with os.scandir(scanner.native(directory)) as entries:
            for entry in entries:
                if scanner.path_key(os.path.join(directory, entry.name)) in keys:
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if not hidden and scanner.attributes(info) & scanner.HIDDEN:
                        continue
                    is_dir = stat.S_ISDIR(info.st_mode) or bool(scanner.attributes(info) & stat.FILE_ATTRIBUTE_DIRECTORY)
                    n = scanner.node(-1, entry.name, is_dir, info)
                    if is_dir:
                        n[7] = 'link_not_followed' if scanner.directory_link(info) else 'enumeration_incomplete'
                        n[9] = False
                except OSError as error:
                    # Preserve the entry with unknown metadata. The name was
                    # enumerated, so a stat failure is not a deletion signal.
                    n = scanner.node(-1, entry.name, False)
                    n[8] = getattr(error, 'winerror', None) or error.errno or 1
                result['entries'].append(n)
    except OSError as error:
        result['error'] = str(error)
        result['entries'] = []
    return result


class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() not in {'file', 'qrc', 'about', 'data'}:
            info.block(True)


class ReportPage(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.report = ''
        self.navigation_diagnostics = []

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # Keep the native bridge attached only to this generated report.
        accepted = not is_main_frame or url == QUrl(self.report) or url.toString() == 'about:blank'
        self.navigation_diagnostics.append({'url': url.toString(), 'accepted': accepted})
        return accepted


class Bridge(QObject):
    snapshotReady = Signal(str)
    message = Signal(str)
    completed = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.directory = ''
        self.hidden = False
        self.busy = False
        self.pending = False
        self.closed = False
        self.generation = 0
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='current-folder')
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(900)
        self.timer.timeout.connect(self.refresh)
        self.completed.connect(self.deliver)

    @Slot(str, result=bool)
    def copyText(self, value):
        if len(value) > 65536:
            return False
        QApplication.clipboard().setText(value)
        return True

    @Slot(str, result=bool)
    def revealPath(self, value):
        try:
            if not os.path.isabs(value) or '\0' in value:
                return False
            directory = value if os.path.dirname(value) == value else os.path.dirname(value)
            if not os.path.isdir(scanner.native(directory)):
                raise FileNotFoundError(directory)
            # Only a verified directory is passed to the shell; never a file,
            # command line, URL or JavaScript-provided executable.
            os.startfile(directory)
            return True
        except OSError as error:
            self.message.emit('无法打开所在位置：' + str(error))
            return False

    @Slot(str, bool)
    def directorySelected(self, directory, hidden):
        if directory == self.directory and hidden == self.hidden:
            return
        if not os.path.isabs(directory) or '\0' in directory:
            return
        self.directory, self.hidden = directory, hidden
        self.update_watch()
        self.window.folder_label.setText('当前目录：' + directory)

    @Slot()
    def pauseUpdates(self):
        self.window.live.setChecked(False)
        self.pending = False
        self.timer.stop()
        self.message.emit('本会话新增记录达到上限，已暂停监听；请重新扫描')

    def update_watch(self):
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        if self.window.live.isChecked() and self.directory:
            try:
                if scanner.directory_link(os.stat(scanner.native(self.directory), follow_symlinks=False)):
                    self.message.emit('目录链接不自动监听；请直接选择目标目录')
                    return
            except OSError:
                self.message.emit('无法监听该目录；可使用“刷新当前目录”')
                return
            if not self.watcher.addPath(self.directory):
                self.message.emit('无法监听该目录；可使用“刷新当前目录”')

    def changed(self, directory):
        # Debounce bursts, with one worker and at most one pending refresh.
        self.timer.start()

    def refresh(self):
        if self.closed or not self.directory:
            return
        if self.busy:
            self.pending = True
            return
        self.busy = True
        directory, hidden = self.directory, self.hidden
        self.window.statusBar().showMessage('正在刷新当前目录…')
        excluded = [self.window.original_report, self.window.loaded_report]
        excluded += [str(p) + '.tmp' for p in excluded if p]
        future = self.pool.submit(directory_snapshot, directory, hidden, [p for p in excluded if p])
        generation = self.generation
        future.add_done_callback(lambda completed: self.finished(completed, generation))

    def finished(self, future, generation):
        try:
            result = future.result()
        except Exception as error:
            result = {'directory': self.directory, 'error': str(error), 'entries': []}
        if not self.closed:
            result['_generation'] = generation
            self.completed.emit(result)

    @Slot(object)
    def deliver(self, result):
        self.busy = False
        if result['_generation'] == self.generation and result['directory'] == self.directory:
            self.snapshotReady.emit(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
            self.window.statusBar().showMessage('当前目录已刷新；其他目录保留扫描记录', 6000)
        if self.pending:
            self.pending = False
            self.timer.start()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        self.pool.shutdown(wait=False, cancel_futures=True)


class Viewer(QMainWindow):
    def __init__(self, report=None):
        super().__init__()
        self.setWindowTitle('DiskInventory · 内嵌界面试用版')
        self.resize(1500, 940)
        self.original_report = ''
        self.loaded_report = ''
        toolbar = QToolBar('报告操作', self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_button = QPushButton('打开扫描报告…')
        self.open_button.clicked.connect(self.choose)
        toolbar.addWidget(self.open_button)
        scan_button = QPushButton('扫描目录…')
        scan_button.clicked.connect(self.scan)
        toolbar.addWidget(scan_button)
        self.refresh_button = QPushButton('刷新当前目录')
        self.refresh_button.setEnabled(False)
        toolbar.addWidget(self.refresh_button)
        self.live = QCheckBox('实时更新当前目录（不含子目录）')
        toolbar.addWidget(self.live)
        browser_button = QPushButton('浏览器打开')
        browser_button.clicked.connect(lambda: self.loaded_report and QDesktopServices.openUrl(QUrl.fromLocalFile(self.loaded_report)))
        toolbar.addWidget(browser_button)
        toolbar.addSeparator()
        self.folder_label = QLabel('等待打开报告')
        self.folder_label.setMaximumWidth(550)
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        toolbar.addWidget(self.folder_label)
        self.view = QWebEngineView(self)
        # Off-the-record profile: no persistent browser cache/history. Block
        # outbound requests and prevent navigation away from the trusted UI.
        self.profile = QWebEngineProfile(self)
        self.interceptor = LocalOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = ReportPage(self.profile, self.view)
        self.view.setPage(self.page)
        self.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self.view.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        self.setCentralWidget(self.view)
        self.bridge = Bridge(self)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject('native', self.bridge)
        self.page.setWebChannel(self.channel)
        library = QFile(':/qtwebchannel/qwebchannel.js')
        if not library.open(QFile.ReadOnly):
            raise RuntimeError('Qt WebChannel script missing')
        bootstrap = bytes(library.readAll()).decode('utf-8') + '''
new QWebChannel(qt.webChannelTransport,function(channel){
 window.diskInventoryHost=channel.objects.native;
 window.diskInventoryHost.snapshotReady.connect(function(text){if(window.diskInventory)window.diskInventory.applyDirectorySnapshot(JSON.parse(text));});
 window.diskInventoryHost.message.connect(function(text){if(window.diskInventory)window.diskInventory.notify(text);});
 window.dispatchEvent(new Event('diskinventory-host-ready'));
});'''
        script = QWebEngineScript()
        script.setName('DiskInventory native bridge')
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(bootstrap)
        self.page.scripts().insert(script)
        self.refresh_button.clicked.connect(self.bridge.refresh)
        self.live.toggled.connect(self.toggle_live)
        self.view.loadFinished.connect(self.loaded)
        self.statusBar().showMessage('实时更新默认关闭；开启后只监听当前目录，不轮询整盘')
        if report:
            QTimer.singleShot(0, lambda: self.open_report(report))

    def open_report(self, source):
        try:
            self.live.setChecked(False)
            self.bridge.generation += 1
            self.bridge.directory = ''
            upgraded = refresh_report(source)
            self.original_report = str(Path(source).absolute())
            self.loaded_report = str(upgraded)
            self.page.report = QUrl.fromLocalFile(self.loaded_report).toString()
            self.refresh_button.setEnabled(False)
            self.view.load(QUrl.fromLocalFile(self.loaded_report))
            self.statusBar().showMessage('正在载入报告并建立索引，大报告需要更多时间与内存…')
        except Exception as error:
            QMessageBox.critical(self, '无法打开报告', str(error))

    def loaded(self, success):
        self.refresh_button.setEnabled(success)
        self.statusBar().showMessage('报告已载入；点击名称、路径、大小、日期即可复制' if success else '页面载入失败')

    def toggle_live(self, checked):
        self.bridge.update_watch()
        if checked:
            self.bridge.refresh()
        self.statusBar().showMessage('只监听当前目录；变化后合并更新，原始报告保留' if checked else '实时更新已关闭')

    def choose(self):
        chosen, _ = QFileDialog.getOpenFileName(self, '打开扫描报告', str(ROOT / 'reports'), 'HTML (*.html *.htm)')
        if chosen:
            self.open_report(chosen)

    def scan(self):
        executable = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(executable if executable.exists() else sys.executable), '-B', str(ROOT / 'tools' / 'dev_scan.py'), '--gui'])

    def closeEvent(self, event):
        self.bridge.shutdown()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', nargs='?')
    parser.add_argument('--latest', action='store_true')
    parser.add_argument('--diagnostics', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.latest and not args.report:
        candidates = [p for p in (ROOT / 'reports').glob('*.html') if '-ui-' not in p.stem]
        if candidates:
            args.report = str(max(candidates, key=lambda p: p.stat().st_mtime_ns))
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    window = Viewer(args.report)
    window.show()
    if args.diagnostics:
        began = time.perf_counter()
        diagnostics = QTimer(window)
        diagnostics.setInterval(750)
        def sampled(text):
            if not text:
                return
            info = json.loads(text)
            if info.get('ready'):
                info['startup_seconds'] = time.perf_counter() - began
                info['live_enabled'] = window.live.isChecked()
                Path(args.diagnostics).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
                diagnostics.stop()
        diagnostics.timeout.connect(lambda: window.page.runJavaScript('JSON.stringify({ready:Boolean(window.diskInventory&&window.diskInventory.ready&&window.diskInventoryHost),files:document.getElementById("file-count")?.textContent,folders:document.getElementById("folder-count")?.textContent})', sampled))
        diagnostics.start()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
