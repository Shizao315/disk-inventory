"""Windows source-only scanner for local development and report testing.

Uses only Python's standard library and the repository HTML template. It does
not invoke the native executable, perform MFT/USN enumeration, install services,
create certificates or change system security settings.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import stat
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'src' / 'report-template.html'
VERSION = '0.1.0-dev-python'
NAME_SURROGATE = 0x20000000
HIDDEN = getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 2)


def normalized(path: str | Path) -> str:
    value = os.fspath(path)
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
        value = value[4:]
    return os.path.abspath(os.path.expanduser(value))


def native(path: str | Path) -> str:
    value = normalized(path)
    if value.startswith('\\\\'):
        return '\\\\?\\UNC\\' + value[2:]
    return '\\\\?\\' + value


def path_key(path: str | Path) -> str:
    return os.path.normcase(normalized(path)).rstrip('\\')


def iso(value: float | None = None) -> str | None:
    try:
        when = datetime.now(timezone.utc) if value is None else datetime.fromtimestamp(value, timezone.utc)
        return when.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError, OSError):
        return None


def attributes(info: os.stat_result) -> int:
    return getattr(info, 'st_file_attributes', 0)


def directory_link(info: os.stat_result) -> bool:
    return bool(getattr(info, 'st_reparse_tag', 0) & NAME_SURROGATE) or stat.S_ISLNK(info.st_mode)


def node(parent: int, name: str, is_dir: bool, info: os.stat_result | None = None) -> list:
    return [parent, name, is_dir,
            str(0 if is_dir else info.st_size) if info is not None else ("0" if is_dir else None),
            iso(getattr(info, 'st_birthtime', info.st_ctime)) if info is not None else None,
            iso(info.st_mtime) if info is not None else None,
            attributes(info) if info is not None else 0,
            'ok' if info is not None else 'metadata_unavailable', 0, info is not None]


def validated_roots(roots: list[str]) -> list[tuple[str, os.stat_result]]:
    if os.name != 'nt':
        raise RuntimeError('This development scanner supports Windows only')
    selected: list[tuple[str, os.stat_result]] = []
    for raw in roots:
        path = normalized(raw)
        info = os.stat(native(path), follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'不是文件夹：{path}')
        key = path_key(path)
        if any(key == path_key(p) or key.startswith(path_key(p) + '\\') for p, _ in selected):
            continue
        selected = [(p, st) for p, st in selected
                    if not path_key(p).startswith(key + '\\')]
        selected.append((path, info))
    if not selected:
        raise ValueError('请至少选择一个文件夹或磁盘')
    return selected


def scan(roots: list[str], *, include_hidden: bool = False,
         exclude: tuple[str, ...] = (), cancel: threading.Event | None = None,
         progress=None) -> dict:
    selected = validated_roots(roots)
    stop = cancel if cancel is not None else threading.Event()
    started = iso()
    begin = time.perf_counter()
    excluded = {path_key(p) for p in exclude}
    nodes: list[list] = []
    pending: deque[tuple[int, str]] = deque()
    notes = ['Python 源码调试版：普通目录扫描；未执行 MFT/USN 索引，不用于原生 EXE 性能验收。']
    counters = {'files': 0, 'folders': 0, 'errors': 0, 'skipped': 0, 'hiddenSkipped': 0}

    def emit(current=''):
        if progress is not None:
            progress(dict(counters, current=current))

    def add(parent, name, is_dir, info=None):
        index = len(nodes)
        nodes.append(node(parent, name, is_dir, info))
        counters['folders' if is_dir else 'files'] += 1
        return index

    for path, info in selected:
        index = add(-1, path, True, info)
        if directory_link(info):
            nodes[index][7] = 'link_not_followed'
            nodes[index][9] = False
            counters['skipped'] += 1
        else:
            nodes[index][7] = 'enumeration_incomplete'
            nodes[index][9] = False
            pending.append((index, path))
    emit()

    while pending and not stop.is_set():
        directory_id, directory = pending.popleft()
        nodes[directory_id][7] = 'ok'
        nodes[directory_id][9] = True
        try:
            with os.scandir(native(directory)) as entries:
                for entry in entries:
                    if stop.is_set():
                        nodes[directory_id][7] = 'enumeration_incomplete'
                        nodes[directory_id][9] = False
                        break
                    full = os.path.join(directory, entry.name)
                    if path_key(full) in excluded:
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if not include_hidden and attributes(info) & HIDDEN:
                            counters['hiddenSkipped'] += 1
                            continue
                        is_dir = stat.S_ISDIR(info.st_mode)
                        # A directory symlink can expose a symlink mode even
                        # when the cached Windows attributes identify a folder.
                        is_dir = is_dir or bool(attributes(info) & stat.FILE_ATTRIBUTE_DIRECTORY)
                        index = add(directory_id, entry.name, is_dir, info)
                        if is_dir:
                            if directory_link(info):
                                nodes[index][7] = 'link_not_followed'
                                nodes[index][9] = False
                                counters['skipped'] += 1
                            else:
                                nodes[index][7] = 'enumeration_incomplete'
                                nodes[index][9] = False
                                pending.append((index, full))
                    except OSError as error:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            is_dir = False
                        index = add(directory_id, entry.name, is_dir)
                        nodes[index][8] = getattr(error, 'winerror', None) or error.errno or 1
                        nodes[index][9] = False
                        counters['errors'] += 1
        except OSError as error:
            nodes[directory_id][7] = 'unreadable'
            nodes[directory_id][8] = getattr(error, 'winerror', None) or error.errno or 1
            nodes[directory_id][9] = False
            counters['errors'] += 1
        emit(directory)

    # Parents precede children. Preserve all known subtotals even if some
    # children are unknown or intentionally not followed.
    totals = [int(n[3]) if n[3] is not None else 0 for n in nodes]
    for index in range(len(nodes) - 1, -1, -1):
        n = nodes[index]
        if n[2]:
            n[3] = str(totals[index])
            if stop.is_set():
                n[9] = False
        if n[0] >= 0:
            totals[n[0]] += totals[index]
            if not n[9] or n[7] != 'ok':
                nodes[n[0]][9] = False
    emit()
    return dict(version=VERSION, started=started, finished=iso(),
                seconds=time.perf_counter() - begin, hidden=include_hidden,
                cancelled=stop.is_set(), errors=counters['errors'],
                skipped=counters['skipped'], hiddenSkipped=counters['hiddenSkipped'],
                engines=[p + ': Python os.scandir (development)' for p, _ in selected],
                notes=notes, nodes=nodes)


def write_json(handle, data):
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'))
    for part in encoder.iterencode(data):
        handle.write(part.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))


def generate(roots: list[str], output: str | Path, *, include_hidden=False,
             overwrite=False, cancel=None, progress=None) -> dict:
    destination = normalized(output)
    if Path(destination).suffix.lower() not in {'.html', '.htm'}:
        raise ValueError('报告文件名必须以 .html 或 .htm 结尾')
    if os.path.lexists(native(destination)) and not overwrite:
        raise FileExistsError('报告已存在，请换一个文件名或确认覆盖')
    validated_roots(roots)
    template = TEMPLATE.read_text(encoding='utf-8')
    if template.count('<!--DISK_DATA-->') != 1:
        raise ValueError('HTML 模板缺失或数据标记不唯一')
    head, tail = template.split('<!--DISK_DATA-->')
    temporary = destination + '.tmp'
    os.makedirs(native(os.path.dirname(destination)), exist_ok=True)
    try:
        # Exclusive creation preserves a stale/failed temporary file rather
        # than truncating it. The new temporary report is also scan-excluded.
        with open(native(temporary), 'x', encoding='utf-8', errors='backslashreplace', newline='') as handle:
            data = scan(roots, include_hidden=include_hidden,
                        exclude=(destination, temporary), cancel=cancel, progress=progress)
            handle.write(head)
            write_json(handle, data)
            handle.write(tail)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise FileExistsError(f'临时报告已存在，已保留原文件；请换一个输出名：{temporary}') from error
    if overwrite:
        os.replace(native(temporary), native(destination))
    else:
        # Windows rename does not replace an existing destination, including
        # one that appeared after the initial existence check.
        os.rename(native(temporary), native(destination))
    return data


def local_drives() -> list[str]:
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint32
    bits = kernel.GetLogicalDrives()
    return [f'{chr(65 + i)}:\\' for i in range(26)
            if bits & (1 << i) and kernel.GetDriveTypeW(f'{chr(65 + i)}:\\') == 3]


def default_output() -> str:
    return str(ROOT / 'reports' / ('DiskInventory-dev-' + time.strftime('%Y%m%d-%H%M%S') + '.html'))


class ScannerWindow:
    def __init__(self, window, roots=(), output=None, hidden=False):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.window = window
        self.window.title('DiskInventory · Python 源码调试版')
        self.window.geometry('850x530')
        self.window.minsize(760, 500)
        self.busy = False
        self.closing = False
        self.cancel = threading.Event()
        self.events = queue.SimpleQueue()
        self.latest = {}
        self.last_report = None
        self.output = tk.StringVar(value=output or default_output())
        self.hidden = tk.BooleanVar(value=hidden)
        self.status = tk.StringVar(value='请选择扫描目录。此版使用普通目录扫描，完成后生成离线 HTML。')
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='磁盘文件清单 · 源码调试版', font=('Microsoft YaHei UI', 16, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))
        ttk.Label(frame, text='选择目录后，生成大小排行与资源管理器式目录浏览两种视图。').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 14))
        ttk.Label(frame, text='扫描路径（每行一个）').grid(row=2, column=0, sticky='w')
        self.roots = tk.Text(frame, height=4, wrap='none', font=('Microsoft YaHei UI', 10))
        self.roots.grid(row=3, column=0, columnspan=3, sticky='nsew', pady=(4, 8))
        self.roots.insert('1.0', '\n'.join(roots))
        self.choose_button = ttk.Button(frame, text='选择文件夹…', command=self.choose)
        self.choose_button.grid(row=4, column=0, sticky='w')
        self.drives_button = ttk.Button(frame, text='全部本地磁盘', command=self.all_drives)
        self.drives_button.grid(row=4, column=1, padx=8)
        self.hidden_check = ttk.Checkbutton(frame, text='包含隐藏文件和文件夹', variable=self.hidden)
        self.hidden_check.grid(row=4, column=2, sticky='w')
        ttk.Label(frame, text='离线 HTML 输出位置').grid(row=5, column=0, sticky='w', pady=(18, 4))
        self.output_entry = ttk.Entry(frame, textvariable=self.output)
        self.output_entry.grid(row=6, column=0, columnspan=2, sticky='ew')
        self.output_button = ttk.Button(frame, text='另存为…', command=self.choose_output)
        self.output_button.grid(row=6, column=2, padx=(8, 0), sticky='ew')
        controls = ttk.Frame(frame)
        controls.grid(row=7, column=0, columnspan=3, sticky='w', pady=(20, 10))
        self.start_button = ttk.Button(controls, text='开始扫描并生成报告', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='取消扫描', command=self.cancel.set, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        self.open_button = ttk.Button(controls, text='打开报告', command=self.open_report, state='disabled')
        self.open_button.pack(side='left')
        self.desktop_button = ttk.Button(controls, text='软件内查看', command=self.open_embedded, state='disabled')
        self.desktop_button.pack(side='left', padx=10)
        ttk.Label(frame, textvariable=self.status, wraplength=790).grid(row=8, column=0, columnspan=3, sticky='w', pady=6)
        self.edit_controls = [self.choose_button, self.drives_button, self.hidden_check, self.output_entry, self.output_button]
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(150, self.poll)

    def choose(self):
        from tkinter import filedialog
        selected = filedialog.askdirectory(parent=self.window, title='选择扫描文件夹或磁盘')
        if selected:
            self.roots.delete('1.0', 'end')
            self.roots.insert('1.0', normalized(selected))

    def all_drives(self):
        self.roots.delete('1.0', 'end')
        self.roots.insert('1.0', '\n'.join(local_drives()))

    def choose_output(self):
        from tkinter import filedialog
        selected = filedialog.asksaveasfilename(parent=self.window, title='保存离线 HTML 报告', defaultextension='.html', filetypes=[('离线 HTML', '*.html')], initialfile=Path(self.output.get()).name)
        if selected:
            self.output.set(normalized(selected))

    def set_busy(self, busy):
        self.busy = busy
        self.roots.configure(state='disabled' if busy else 'normal')
        for control in self.edit_controls:
            control.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        self.open_button.configure(state='normal' if not busy and self.last_report else 'disabled')
        self.desktop_button.configure(state='normal' if not busy and self.last_report else 'disabled')

    def start(self):
        from tkinter import messagebox
        if self.busy:
            return
        roots = [line.strip() for line in self.roots.get('1.0', 'end').splitlines() if line.strip()]
        try:
            validated_roots(roots)
            output = normalized(self.output.get())
            overwrite = os.path.lexists(native(output))
            if overwrite and not messagebox.askyesno('覆盖报告', '该报告已经存在，是否覆盖？', parent=self.window):
                return
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror('无法开始', str(error), parent=self.window)
            return
        self.cancel.clear()
        self.latest = {}
        self.set_busy(True)
        self.status.set('正在扫描…')
        include_hidden = self.hidden.get()

        def worker():
            try:
                result = generate(roots, output, include_hidden=include_hidden,
                                  overwrite=overwrite, cancel=self.cancel,
                                  progress=lambda stats: setattr(self, 'latest', stats))
                self.events.put(('done', output, result))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        from tkinter import messagebox
        if self.busy and self.latest:
            p = self.latest
            self.status.set(('正在取消并保存部分结果… ' if self.cancel.is_set() else '扫描中… ') + f"文件 {p['files']:,}，文件夹 {p['folders']:,}，读取错误 {p['errors']:,}")
        try:
            event = self.events.get_nowait()
        except queue.Empty:
            event = None
        if event:
            if event[0] == 'done':
                self.last_report = Path(event[1])
                data = event[2]
                count = sum(not n[2] for n in data['nodes'])
                label = '已取消，部分报告已保存' if data['cancelled'] else '报告已生成'
                self.status.set(f"{label}：{count:,} 个文件；{data['errors']:,} 项读取错误。\n{event[1]}")
            else:
                self.status.set('扫描或导出失败：' + event[1])
                if not self.closing:
                    messagebox.showerror('生成失败', event[1], parent=self.window)
            self.set_busy(False)
            if self.closing:
                self.window.destroy()
                return
        self.window.after(150, self.poll)

    def open_report(self):
        if self.last_report:
            webbrowser.open(self.last_report.as_uri())

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel.set()
            self.status.set('正在停止扫描并保存部分报告，完成后关闭…')
        else:
            self.window.destroy()

    def open_embedded(self):
        if not self.last_report:
            return
        executable = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(executable if executable.exists() else sys.executable), '-B', str(ROOT / 'tools' / 'desktop_viewer.py'), str(self.last_report)])


def main(argv=None):
    parser = argparse.ArgumentParser(description='DiskInventory Windows source development scanner')
    parser.add_argument('--root', action='append', default=[])
    parser.add_argument('--output')
    parser.add_argument('--include-hidden', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args(argv)
    if args.gui or not args.root:
        import tkinter as tk
        window = tk.Tk()
        ScannerWindow(window, args.root, args.output, args.include_hidden)
        window.mainloop()
        return 0
    try:
        output = args.output or default_output()
        result = generate(args.root, output, include_hidden=args.include_hidden, overwrite=args.overwrite)
        summary = dict(report=normalized(output), files=sum(not n[2] for n in result['nodes']),
                       folders=sum(n[2] for n in result['nodes']), seconds=result['seconds'],
                       errors=result['errors'], cancelled=result['cancelled'], engine='Python os.scandir')
        print(json.dumps(summary, ensure_ascii=False))
        return 3 if result['cancelled'] else 2 if result['errors'] else 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    raise SystemExit(main())
