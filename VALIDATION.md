# 0.1.0-test 本地交付验证

日期：2026-11-08，Asia/Shanghai。

**最终交付 EXE 启动被本机 Smart App Control 阻止，尚未通过最终二进制端到端复验。** 以下成功的扫描与原生窗口测试来自前一构建，不能直接记为最终文件运行通过。

前一已测构建 SHA-256：`d68fdc9dc70309ccbc7fc94a24c5f1b3fb86a3d4b903ff53361d64a5db98b5e2`，8 项检查通过于 13:32。随后仅修改 HTML 视图切换选择器的作用范围并重编译；最终 EXE 的本机运行被 Code Integrity 拒绝。

## 已执行

- 原生 C++ x64 EXE 编译成功，227,328 字节（222 KiB）；PE 子系统为 Windows GUI。
- `tests/integration.py`：8 项检查通过。使用实际 EXE 扫描人工目录，核对隐藏项与隐藏目录后代、逻辑大小和目录小计、空目录/空文件、中文长路径、创建和最后写入时间、5 GiB 以上稀疏文件、硬链接、循环 junction、重复/重叠根路径、排除输出文件、无效输入及 MFT 请求的兼容回退。
- 同一检查覆盖原生窗口：在后台隐藏启动、验证路径预填、触发“开始扫描”、检查实际报告和“打开报告”按钮可用、正常退出。
- `tests/report-browser.cjs`：使用 Edge 157 的无界面模式打开真实 EXE 生成的 HTML，检查数值大小升降序、三种布局、文件定位、目录进入/返回/前进/上级、筛选、文件信息及本地链接。
- 另使用 12,001 条人工记录检查分页末页和虚拟列表，确认全部记录仍可访问、当前只绘制少量可见行。
- 浏览器检查未发现页面脚本错误，也未发出 HTTP/HTTPS 请求。
- 已查看真实报告的页面截图，修复过模式切换样式作用范围问题。最终模板另使用前一构建的真实扫描数据回放验证；该回放不代替最终 EXE 运行。

EXE 哈希、源文件哈希、官方工具链校验值、系统 DLL 导入和测试结果见发布包中的 `manifest.json` 与 `SHA256SUMS.txt`。测试输出保存在开发目录 `test-output`，不进入开源源码或交付包。

## 尚未验证的范围

- 提权后的真实 NTFS 全盘 MFT 分支和端到端性能。该分支已实现，但本次实际扫描测试以有边界的人工文件夹为主，不能将兼容回退测试视为 MFT 运行通过。
- 百万级真实文件报告的载入时间、内存与浏览性能。
- 其他 Windows 机器、其他浏览器和各云盘占位文件实现。
- UAC 拒绝/重启的人工操作，以及取消大扫描后保存部分报告的完整操作链。

此版本用于用户首次本地试用，不是已完成全部平台和性能验收的正式发行版。当前主要交付为 EXE 与交互 HTML，Markdown/CSV 导出留作后续。

## 当前系统拦截

- 最终 EXE：未签名。运行返回 WinError 4551。
- Code Integrity 事件 3033/3077 指向本 EXE，策略 ID 为 `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`；本机 `VerifiedAndReputablePolicyState=1`。
- 普通执行与请求沙箱外直接执行均被拒绝；没有改动安全策略、证书信任或注册表。
- 本机用户证书库未发现可用的代码签名证书。
- 需在允许此类开发构建的测试环境验证，或取得公开受信任的代码签名资格后签名，再重新验证最终哈希。
- [微软 Smart App Control 说明](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)与[签名要求](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)。
