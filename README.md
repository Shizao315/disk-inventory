# DiskInventory

小型 Windows 文件清单扫描器。读取文件系统元数据，输出一个自包含的离线 HTML 报告；同一报告支持全局文件大小排序、文件夹逐层浏览和双栏显示。

开源仓库：[Shizao315/disk-inventory](https://github.com/Shizao315/disk-inventory)。

[![Windows build and test](https://github.com/Shizao315/disk-inventory/actions/workflows/windows.yml/badge.svg)](https://github.com/Shizao315/disk-inventory/actions/workflows/windows.yml)

当前为 **0.1.0-test 测试版**。支持 Windows 10/11 x64。程序采用 C++ 与原生 Win32 界面；可执行文件不需要附带 HTML 模板，不要求安装 Python、Node.js、Everything 或 C++ 运行时。

**当前交付限制：此包未签名，本机 Smart App Control 已阻止最终 EXE 启动。** 前一构建的真实扫描和窗口检查已通过，但最终文件需要在允许开发构建的环境中复验，或完成受信任代码签名。详细证据见 `VALIDATION.md`；不能把前一构建测试或 HTML 回放视为最终文件已运行通过。

**云端验证更新：** 2026-11-08，GitHub Windows Server 2022 已从源码成功构建并运行 EXE，8 项扫描与原生窗口检查以及 Edge 报告检查全部通过。[成功运行记录](https://github.com/Shizao315/disk-inventory/actions/runs/42459081210)。该结果适用于此 CI 生成的程序，未改变本地未签名包的启动限制，也不包含全盘 MFT 性能验收。

- [下载 0.1.0-test 未签名测试包](downloads/DiskInventory-0.1.0-test-unsigned.zip)
- [测试包说明与 SHA-256](downloads/README.md)
- [人工数据交互样稿](report-demo.html)（下载后用浏览器打开；不是实际磁盘扫描结果）

## 快速使用

1. 双击 `DiskInventory.exe`。
2. 点击“选择文件夹”，或点击“全部本地磁盘”；也可在路径框逐行填入路径。
3. 按需勾选“包含隐藏文件和文件夹”，选择 HTML 报告保存位置。
4. 点击“开始扫描并生成报告”。完成后点击“打开报告”。

建议第一次选择一个较小目录，确认报告效果后再扫描整盘。生成的 HTML 可单独保存、复制，离线打开；不包含被扫描文件的正文。

报告顶部有“大小排序 / 目录浏览 / 双栏”。大小排行按原始字节数排序，点击大小表头切换方向；点击“定位目录”进入文件所在文件夹。目录视图支持双击进入、后退/前进、上一级、目录树及地址栏跳转。文件过多时分页，每页内部按需绘制可见行；分页不会截断报告数据。

报告中双击文件可查看信息，并尝试打开本地文件。浏览器可能阻止打开，或按格式选择预览/下载；可使用“复制路径”后在 Windows 资源管理器中打开。复制报告到其他电脑后，仍可浏览扫描时的目录清单，但原始文件路径可能不再有效。

## 扫描方式与权限

- 指定文件夹：使用 `FindFirstFileExW`、`FindExInfoBasic` 和 `FIND_FIRST_EX_LARGE_FETCH` 批量枚举，直接获取长度与创建/修改时间。
- 完整 NTFS 磁盘 + 管理员：使用 `FSCTL_ENUM_USN_DATA` 建立 MFT 名称与父子关系索引，再通过目录元数据补齐大小、日期及额外硬链接名称。
- 无法使用 MFT、非 NTFS，或未提权：回退到原生目录扫描；实际方式与原因写进报告诊断。
- 默认按普通用户启动。需要时点击“以管理员重启”；若取消 UAC，原窗口保留，可继续普通扫描。此测试版不安装服务、不创建或修改 USN 日志。

MFT 枚举和补齐元数据是两个步骤，此测试版不宣称达到 Everything 的性能。快速路径在读取大小与日期时仍受目录权限限制；未知项明确保留，不伪装成零字节。

## 数据口径

- 字段包含名称、类型/扩展名、完整路径、逻辑大小、创建时间和最后修改时间。
- 文件夹大小为纳入结果的后代文件逻辑长度之和。硬链接按每个路径计数；这不等同于实际占用磁盘空间。
- 隐藏项关闭时，隐藏目录及全部后代均排除；System 属性不等同于 Hidden。
- 目录 junction、符号链接等名称替身不跟随，避免循环；保留条目并标注。云占位目录按实际重解析标签处理，不一概丢弃；不打开文件正文。
- 空目录保留。无权限、元数据未知、未跟随链接与取消状态均写入报告。目录有缺失时只展示已知大小小计。
- 报告记录扫描时段，不是原子快照；扫描过程中变化可能导致部分条目未知。
- 日期原值保存为 UTC，界面按浏览器时区显示；创建日期不等同于内容原始创作日期。
- 报告及其 `.tmp` 文件从本次清单中排除。导出先写同目录 `.tmp`，成功后再替换目标报告；失败的临时文件保留供诊断，下次请换输出名或在核实后手动处理旧 `.tmp`。

## 命令行

```powershell
.\DiskInventory.exe --root 'D:\资料' --output 'D:\扫描报告.html'
.\DiskInventory.exe --root 'C:\' --root 'D:\' --output 'D:\全盘报告.html' --include-hidden
.\DiskInventory.exe --root 'D:\资料' --output 'D:\报告.html' --engine directory
```

`--engine auto|directory|mft`：默认 `auto`；`mft` 不适用时仍回退并记录原因。`--gui` 显示窗口并将其他参数填入界面，不会自动开始。重复及重叠根目录会合并。

退出码：`0` 已导出；`1` 参数、扫描异常或导出失败；`2` 已导出但存在读取错误/未知元数据；`3` 已取消并导出部分结果。未跟随目录链接单独记录，不单独使退出码变为错误。

## 构建

使用 Zig 0.13.0 附带的 Clang/MinGW 编译 C++：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-toolchain.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

准备脚本仅从 Zig 官方站点取得版本元数据和编译器，并核对官方 SHA-256；不会安装系统级软件。也可向 `build.ps1` 传入 `-ZigPath`。编译器与构建缓存放在 `.tools`、`.build`，不会打包进 EXE。

`src/report-template.html` 编译时嵌入 EXE；运行时不需要旁置模板。程序不依赖 CDN、联网请求或本地 Web 服务器。

## 验证

`tests/integration.py` 针对真实 EXE 建立有边界的人工目录并核对记录、隐藏项、日期、Unicode、长路径、硬链接、稀疏大文件和循环链接。测试结果放在 `test-output`，不进入开源样例。

`tests/report-browser.cjs` 使用 Playwright 与已安装的 Edge 验证离线报告交互，另用 12,001 条人工记录验证分页与可见行绘制。Node/Playwright 仅用于开发验证，不是最终程序依赖。

开发者可在项目目录运行：

```powershell
python -B tests/integration.py
npm install --no-save --ignore-scripts playwright@1.62.1 --registry=https://registry.npmjs.org
powershell -NoProfile -ExecutionPolicy Bypass -File tests/run-browser.ps1
```

GitHub Actions 的 Windows 工作流会从源码构建并执行这些检查。CI 构建仍然未签名；CI 通过不等于其他机器的 Smart App Control 会允许启动，也不等于全盘 MFT 性能已验证。

尚需分别验证真实大盘的 MFT 路径、百万级报告、其他 Windows 配置和各种云占位目录。具体已执行的测试与限制见交付验证记录。

许可证：MIT。实际磁盘报告可能包含私人文件名与路径，请自行决定分享范围；仓库示例使用人工数据。

## 隐私与代码签名

程序不主动向网络服务发送扫描数据；HTML 报告内嵌脚本、样式和记录，无外部请求。用户点击本地文件链接时，由浏览器和操作系统处理该路径；如扫描或打开网络共享路径，访问相应共享是该操作的一部分。

当前项目没有受信任代码签名资格，也未获准使用 SignPath Foundation。后续将评估开源签名申请；申请与配置说明见 [SIGNING.md](SIGNING.md)。将源码发布到 GitHub 本身不会给 EXE 添加 Windows 可信签名。

[Code signing policy](CODE_SIGNING_POLICY.md) 记录签名职责与隐私政策。[签名申请材料](signing/APPLICATION.md) 和手动工作流已准备；工作流在服务审批、参数和凭据尚未配置时会拒绝提交，当前未发送任何签名请求。
