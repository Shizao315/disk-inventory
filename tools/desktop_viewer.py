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
import sys
import threading
import time

# Anaconda's Python can import Qt through add_dll_directory, but its Chromium
# child also needs the environment's Library/bin in its own DLL search path.
# Scope this to this process and children; do not alter the user's system PATH.
conda_libraries = Path(sys.executable).parent / 'Library' / 'bin'
if conda_libraries.is_dir():
    os.environ['PATH'] = str(conda_libraries) + os.pathsep + os.environ.get('PATH', '')

from PySide6.QtCore import QFile, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QToolBar, QVBoxLayout, QWidget
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

import dev_scan as scanner
from refresh_report import refresh_report

ROOT = Path(__file__).resolve().parents[1]


def verify_entries(entries):
    """Only confirmed missing paths are removed; access errors remain unknown."""
    missing, unknown = [], []
    for entry in entries:
        try:
            os.stat(scanner.native(entry['path']), follow_symlinks=False)
        except FileNotFoundError:
            missing.append(entry['id'])
        except OSError as error:
            unknown.append({'id': entry['id'], 'error': getattr(error, 'winerror', None) or error.errno or 1})
    return {'missing': missing, 'unknown': unknown, 'checked': len(entries)}


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
    verificationReady = Signal(str)
    verificationCompleted = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.directory = ''
        self.hidden = False
        self.busy = False
        self.pending = False
        self.closed = False
        self.generation = 0
        self.verifying = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='current-folder')
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(900)
        self.timer.timeout.connect(self.refresh)
        self.completed.connect(self.deliver)
        self.verificationCompleted.connect(self.deliver_verification)

    @Slot(result=str)
    def reportContext(self):
        return self.window.report_context

    @Slot(str)
    def reportInfo(self, value):
        try:
            info = json.loads(value)
            roots = info['roots']
            if roots and all(isinstance(p, str) and os.path.isabs(p) for p in roots):
                self.window.report_roots = roots
                self.window.report_hidden = bool(info['hidden'])
        except (ValueError, KeyError, TypeError):
            pass

    @Slot(str)
    def verifyEntries(self, value):
        if self.closed or self.verifying or self.window.scan_busy:
            return
        try:
            entries = json.loads(value)
            if not isinstance(entries, list) or len(entries) > 5000:
                raise ValueError('最多校验本页 5,000 条记录')
            for entry in entries:
                if not isinstance(entry['id'], int) or not isinstance(entry['path'], str) or not os.path.isabs(entry['path']) or '\0' in entry['path']:
                    raise ValueError('路径或条目无效')
        except (ValueError, KeyError, TypeError) as error:
            self.message.emit('无法校验：' + str(error))
            return
        self.verifying = True
        self.window.verify_button.setEnabled(False)
        self.window.statusBar().showMessage('正在校验本页路径；不会删除磁盘文件…')
        generation = self.generation
        future = self.pool.submit(verify_entries, entries)
        def finished(done):
            try:
                result = done.result()
            except Exception as error:
                result = {'error': str(error)}
            result['_generation'] = generation
            if not self.closed:
                self.verificationCompleted.emit(result)
        future.add_done_callback(finished)

    @Slot(object)
    def deliver_verification(self, result):
        self.verifying = False
        self.window.verify_button.setEnabled(bool(self.window.loaded_report) and not self.window.scan_busy)
        if result['_generation'] != self.generation:
            return
        if result.get('error'):
            self.message.emit('校验失败：' + result['error'] + '；保留已有记录')
            return
        self.verificationReady.emit(json.dumps(result, ensure_ascii=True))
        self.window.statusBar().showMessage(f"本页校验完成：确认不存在 {len(result['missing'])} 项，无法确认 {len(result['unknown'])} 项", 10000)

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
    scanProgress = Signal(object)
    scanDone = Signal(object)
    scanFailed = Signal(str)

    def __init__(self, report=None):
        super().__init__()
        self.setWindowTitle('DiskInventory · 内嵌界面试用版')
        self.resize(1500, 940)
        self.original_report = ''
        self.loaded_report = ''
        self.report_context = ''
        self.report_roots = []
        self.report_hidden = False
        self.scan_busy = False
        self.closing = False
        self.scan_cancel = threading.Event()
        self.scan_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='embedded-scan')
        toolbar = QToolBar('报告操作', self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_button = QPushButton('打开历史报告…')
        self.open_button.clicked.connect(self.choose)
        toolbar.addWidget(self.open_button)
        self.scan_button = QPushButton('重新扫描…')
        self.scan_button.clicked.connect(self.scan)
        toolbar.addWidget(self.scan_button)
        self.report_button = QPushButton('查看报告')
        self.report_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.view))
        self.report_button.setEnabled(False)
        toolbar.addWidget(self.report_button)
        self.refresh_button = QPushButton('刷新当前目录')
        self.refresh_button.setEnabled(False)
        toolbar.addWidget(self.refresh_button)
        self.verify_button = QPushButton('校验本页是否存在')
        self.verify_button.setEnabled(False)
        self.verify_button.clicked.connect(lambda: self.page.runJavaScript('window.diskInventory?.verifyCurrentPage()'))
        toolbar.addWidget(self.verify_button)
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
        self.stack = QStackedWidget(self)
        self.scan_panel = self.build_scan_panel()
        self.stack.addWidget(self.scan_panel)
        self.stack.addWidget(self.view)
        self.setCentralWidget(self.stack)
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
 window.diskInventoryHost.verificationReady.connect(function(text){if(window.diskInventory)window.diskInventory.applyVerification(JSON.parse(text));});
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
        self.scanProgress.connect(self.scan_progress)
        self.scanDone.connect(self.scan_done)
        self.scanFailed.connect(self.scan_failed)
        self.statusBar().showMessage('实时更新默认关闭；开启后只监听当前目录，不轮询整盘')
        if report:
            QTimer.singleShot(0, lambda: self.open_report(report))

    def open_report(self, source, fresh=False):
        try:
            self.live.setChecked(False)
            self.bridge.generation += 1
            self.bridge.directory = ''
            upgraded = Path(source).absolute() if fresh else refresh_report(source)
            self.original_report = str(Path(source).absolute())
            self.loaded_report = str(upgraded)
            self.report_context = '本次重新扫描结果：扫描结束后的变化需刷新、校验或重新扫描。' if fresh else '历史扫描快照：打开或更换界面不会重新扫描磁盘；已删除的文件可能仍在历史记录中。'
            self.page.report = QUrl.fromLocalFile(self.loaded_report).toString()
            self.refresh_button.setEnabled(False)
            self.verify_button.setEnabled(False)
            self.report_button.setEnabled(True)
            self.stack.setCurrentWidget(self.view)
            self.view.load(QUrl.fromLocalFile(self.loaded_report))
            self.statusBar().showMessage('正在载入报告并建立索引，大报告需要更多时间与内存…')
        except Exception as error:
            QMessageBox.critical(self, '无法打开报告', str(error))

    def loaded(self, success):
        if self.view.url().toString() == 'about:blank':
            return
        self.refresh_button.setEnabled(success and not self.scan_busy)
        self.verify_button.setEnabled(success and not self.scan_busy)
        self.statusBar().showMessage('报告已载入；点击名称、路径、大小、日期即可复制' if success else '页面载入失败')

    def toggle_live(self, checked):
        self.bridge.update_watch()
        if checked:
            self.bridge.refresh()
        else:
            self.bridge.timer.stop()
            self.bridge.pending = False
        self.statusBar().showMessage('只监听当前目录；变化后合并更新，原始报告保留' if checked else '实时更新已关闭')

    def choose(self):
        chosen, _ = QFileDialog.getOpenFileName(self, '打开扫描报告', str(ROOT / 'reports'), 'HTML (*.html *.htm)')
        if chosen:
            self.open_report(chosen)

    def build_scan_panel(self):
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(30, 24, 30, 24)
        title = QLabel('重新扫描磁盘 / 文件夹', panel)
        title.setStyleSheet('font-size:24px;font-weight:bold')
        layout.addWidget(title)
        note = QLabel('这会实际读取当前磁盘并生成新报告。扫描表单与结果均在此窗口内切换；打开历史报告不会重新扫描。', panel)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel('扫描路径（每行一个）'))
        self.scan_roots = QPlainTextEdit(panel)
        self.scan_roots.setPlainText('\n'.join(scanner.local_drives()[:1]))
        self.scan_roots.setMaximumHeight(150)
        layout.addWidget(self.scan_roots)
        choices = QHBoxLayout()
        self.choose_root = QPushButton('选择文件夹…')
        self.choose_root.clicked.connect(self.choose_scan_root)
        choices.addWidget(self.choose_root)
        self.all_roots = QPushButton('全部本地磁盘')
        self.all_roots.clicked.connect(lambda: self.scan_roots.setPlainText('\n'.join(scanner.local_drives())))
        choices.addWidget(self.all_roots)
        self.scan_hidden = QCheckBox('包含隐藏文件和文件夹')
        choices.addWidget(self.scan_hidden)
        choices.addStretch()
        layout.addLayout(choices)
        layout.addWidget(QLabel('新报告保存位置'))
        output = QHBoxLayout()
        self.scan_output = QLineEdit(self.new_output())
        output.addWidget(self.scan_output)
        self.choose_scan_output = QPushButton('另存为…')
        self.choose_scan_output.clicked.connect(self.choose_scan_destination)
        output.addWidget(self.choose_scan_output)
        layout.addLayout(output)
        actions = QHBoxLayout()
        self.scan_start = QPushButton('开始重新扫描并显示新报告')
        self.scan_start.clicked.connect(self.start_scan)
        actions.addWidget(self.scan_start)
        self.scan_stop = QPushButton('取消扫描')
        self.scan_stop.setEnabled(False)
        self.scan_stop.clicked.connect(self.scan_cancel.set)
        actions.addWidget(self.scan_stop)
        actions.addStretch()
        layout.addLayout(actions)
        self.scan_progress_bar = QProgressBar(panel)
        self.scan_progress_bar.setRange(0, 1)
        self.scan_progress_bar.setValue(0)
        layout.addWidget(self.scan_progress_bar)
        self.scan_status = QLabel('尚未开始扫描。旧报告中的记录不会自动等同于当前磁盘状态。', panel)
        self.scan_status.setWordWrap(True)
        layout.addWidget(self.scan_status)
        layout.addStretch()
        self.scan_controls = [self.scan_roots, self.choose_root, self.all_roots, self.scan_hidden, self.scan_output, self.choose_scan_output]
        return panel

    def new_output(self):
        return str(ROOT / 'reports' / ('DiskInventory-scan-' + time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns()%1000000:06d}.html'))

    def scan(self):
        if not self.scan_busy:
            if self.report_roots:
                self.scan_roots.setPlainText('\n'.join(self.report_roots))
                self.scan_hidden.setChecked(self.report_hidden)
            self.scan_output.setText(self.new_output())
            self.scan_status.setText('准备重新扫描，尚未开始。点击“开始重新扫描并显示新报告”后才会读取当前磁盘。')
            self.scan_progress_bar.setValue(0)
        self.stack.setCurrentWidget(self.scan_panel)
        self.statusBar().showMessage('扫描设置；历史报告保留在磁盘，完成扫描后自动显示新结果')

    def choose_scan_root(self):
        chosen = QFileDialog.getExistingDirectory(self, '选择扫描目录')
        if chosen:
            self.scan_roots.setPlainText(scanner.normalized(chosen))

    def choose_scan_destination(self):
        chosen, _ = QFileDialog.getSaveFileName(self, '保存新扫描报告', self.scan_output.text(), 'HTML (*.html)')
        if chosen:
            self.scan_output.setText(scanner.normalized(chosen))

    def set_scanning(self, busy):
        self.scan_busy = busy
        for control in self.scan_controls:
            control.setEnabled(not busy)
        self.scan_start.setEnabled(not busy)
        self.scan_stop.setEnabled(busy)
        self.open_button.setEnabled(not busy)
        self.live.setEnabled(not busy)
        self.report_button.setEnabled(not busy and bool(self.loaded_report))
        self.refresh_button.setEnabled(not busy and bool(self.loaded_report))
        self.verify_button.setEnabled(not busy and bool(self.loaded_report))
        self.scan_progress_bar.setRange(0, 0 if busy else 1)
        self.scan_progress_bar.setValue(0)

    def start_scan(self):
        if self.scan_busy:
            return
        roots = [line.strip() for line in self.scan_roots.toPlainText().splitlines() if line.strip()]
        try:
            selected = scanner.validated_roots(roots)
            roots = [p for p, _ in selected]
            output = scanner.normalized(self.scan_output.text())
            if Path(output).suffix.lower() not in {'.html', '.htm'}:
                raise ValueError('报告文件名必须以 .html 或 .htm 结尾')
            overwrite = os.path.lexists(scanner.native(output))
            if overwrite and QMessageBox.question(self, '覆盖报告', '目标报告已存在，是否覆盖？') != QMessageBox.Yes:
                return
        except (OSError, ValueError, RuntimeError) as error:
            self.scan_status.setText('无法开始：' + str(error))
            return
        hidden = self.scan_hidden.isChecked()
        self.live.setChecked(False)
        self.bridge.timer.stop()
        self.bridge.pending = False
        self.bridge.generation += 1
        self.bridge.directory = ''
        # Keep the snapshot on disk, release its large DOM before collecting a
        # new full scan, so two million-record datasets need not coexist.
        self.view.load(QUrl('about:blank'))
        self.loaded_report = ''
        self.scan_cancel.clear()
        self.set_scanning(True)
        self.stack.setCurrentWidget(self.scan_panel)
        self.scan_status.setText('正在实际扫描磁盘；完成后在当前窗口显示新报告…')
        def worker():
            last = [0.0]
            def progress(stats):
                now = time.monotonic()
                if now - last[0] >= .15:
                    last[0] = now
                    self.scanProgress.emit(stats)
            try:
                data = scanner.generate(roots, output, include_hidden=hidden, overwrite=overwrite, cancel=self.scan_cancel, progress=progress)
                summary = {'report': output, 'roots': roots, 'hidden': hidden, 'files': sum(not n[2] for n in data['nodes']), 'errors': data['errors'], 'cancelled': data['cancelled'], 'started': data['started'], 'finished': data['finished']}
                del data
                self.scanDone.emit(summary)
            except Exception as error:
                self.scanFailed.emit(str(error))
        self.scan_pool.submit(worker)

    @Slot(object)
    def scan_progress(self, stats):
        self.scan_status.setText(('正在取消并保存部分结果… ' if self.scan_cancel.is_set() else '扫描中… ') + f"文件 {stats['files']:,}，文件夹 {stats['folders']:,}，读取错误 {stats['errors']:,}")

    @Slot(object)
    def scan_done(self, summary):
        self.set_scanning(False)
        self.scan_progress_bar.setValue(1)
        self.report_roots = summary['roots']
        self.report_hidden = summary['hidden']
        self.scan_status.setText(f"{'已取消并保存部分结果' if summary['cancelled'] else '本次重新扫描完成'}：{summary['files']:,} 个文件，{summary['errors']:,} 项读取错误。\n{summary['report']}")
        if self.closing:
            self.close()
        else:
            self.open_report(summary['report'], fresh=True)

    @Slot(str)
    def scan_failed(self, error):
        self.set_scanning(False)
        self.scan_status.setText('扫描失败：' + error)
        if self.closing:
            self.close()

    def closeEvent(self, event):
        if self.scan_busy:
            self.closing = True
            self.scan_cancel.set()
            self.scan_status.setText('正在取消并保存部分报告，完成后关闭…')
            event.ignore()
            return
        self.bridge.shutdown()
        self.scan_pool.shutdown(wait=False, cancel_futures=True)
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
