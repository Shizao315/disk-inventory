# 本地 Python 源码调试版

用于等待受信任代码签名期间在本机试用扫描与报告。使用已安装的 Python 3.12+（含 Tkinter）独立扫描，不运行原生 EXE，不创建证书、不修改系统安全设置。

## 双击使用

1. 双击 `RUN_DEV_SCAN.cmd`。本机已验证可使用 `C:\ProgramData\anaconda3\pythonw.exe`。
2. 点击“选择文件夹”，首次建议选择一个较小的目录；也可点击“全部本地磁盘”。
3. 按需勾选“包含隐藏文件和文件夹”，选择报告保存位置。
4. 点击“开始扫描并生成报告”，完成后点击“打开报告”。

报告顶部可切换“大小排序 / 目录浏览 / 双栏”。文件夹可逐层打开；文件可查看大小、类型、日期和完整路径。报告保留扫描时的目录信息，离线打开，无需启动本地服务器。

默认报告位于项目 `reports` 文件夹。报告和临时输出不会被计入本次扫描。取消时保存已扫描的部分记录；无法读取的目录明确标注，不作为完整空目录。目录链接不跟随，避免循环。程序只读取文件元数据。

完成扫描后可点击“软件内查看”，或双击 `RUN_DESKTOP.cmd` 查看已有报告。该可选界面使用本机已有的 PySide6；具体功能与实时更新范围见 [内嵌界面说明](DESKTOP_PREVIEW.md)。

## 手动启动

如果双击入口无法启动，在项目目录运行：

```powershell
& 'C:\ProgramData\anaconda3\python.exe' -B tools\dev_scan.py --gui
```

也支持直接生成报告：

```powershell
python -B tools/dev_scan.py --root 'D:\资料' --output 'D:\扫描报告.html'
python -B tools/dev_scan.py --root 'C:\' --root 'D:\' --output 'D:\全盘报告.html' --include-hidden
```

已有报告默认不覆盖；命令行需明确加 `--overwrite`，窗口会询问。存在旧 `.tmp` 时保留原文件并报告错误，请改用新的报告名。

## 验证范围

这是普通 `os.scandir` 目录扫描版，复用原生程序的 HTML 模板。它用于试用扫描功能和两种报告视图，不代表原生 EXE 或 Everything 式 MFT 扫描的速度。原生 EXE 签名仍等待 SignPath 审核。

开发检查：`python -B tests/test_dev_scan.py`；随后运行 `tests/run-browser.ps1 -ReportDirectory test-output/dev`。检查只使用人工目录。长路径测试超过 Windows 传统 260 字符限制，但在本项目位置控制于 OneDrive 400 字符限制以内。

源码调试包需要保留 `tools/dev_scan.py` 与 `src/report-template.html` 的相对位置；不包含 Python 运行环境。
