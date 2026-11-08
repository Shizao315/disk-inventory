# 个人开发者如何给 EXE 签名

核对日期：2026-11-08。签名身份与费用尚未申请或购买，当前 EXE 未签名。

## 本项目当前进度

- 公开源码和 Windows 自动构建已就绪，现有云端扫描/报告测试通过。
- 维护者确认 GitHub 2FA 已开启；这是用户确认，不是工具读取证明。
- [Code signing policy](CODE_SIGNING_POLICY.md)、[英文申请材料](signing/APPLICATION.md)、产品版本资源与手动签名工作流已准备。
- 尚未提交或获得 SignPath 审批，未配置签名 API token，没有生成已签名 EXE。

下一步由维护者打开 https://signpath.org/apply ，用 `signing/APPLICATION.md` 中的项目事实与英文描述填写申请，并自行填写联系姓名/邮箱及确认条款。新项目缺少长期公开信誉，免费服务不保证获批。

获批后配置 `signing` 环境及下列 GitHub Actions 设置（不要写入源码）：

| 类型 | 名称 |
| --- | --- |
| Secret | SIGNPATH_API_TOKEN |
| Variable | SIGNPATH_ORGANIZATION_ID |
| Variable | SIGNPATH_PROJECT_SLUG |
| Variable | SIGNPATH_SIGNING_POLICY_SLUG |
| Variable | SIGNPATH_ARTIFACT_CONFIGURATION_SLUG |
| Variable | SIGNPATH_EXPECTED_SIGNER_SUBJECT |
| Variable | SIGNPATH_READY=true（仅在审批和参数核对完成后设置） |

具体 ID、slug 和证书 Subject 以获批账户为准。将 `signing/artifact-configuration.xml` 作为待服务方审核的配置；签名策略需保留维护者人工批准。运行 “Sign Windows release” 工作流时，勾选本次提交确认。流程会先构建/测试、上传精确产物、等待批准、验证返回的签名与时间戳，再测试已签名程序。任何环节失败都不会生成 `signed-verified` 交付物。

## 这次为什么不能运行

本机 Smart App Control 启用了强制检查，最终 EXE 启动返回 WinError 4551。该机制会拦截无法确认安全性的未签名程序。它不同于普通 SmartScreen 下载提醒，不能假设会出现“仍要运行”按钮。

代码签名证明发布者身份与文件签名后未被篡改，不代表对软件功能或安全性作全面保证。代码更新后需重新签名；签名后仍可能出现 SmartScreen 信誉提示。

- [微软 Smart App Control 机制](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- [可信代码签名要求](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)

## 可选路径

### 1. 免费开源项目签名：SignPath Foundation

为满足条件的开源项目提供免费签名服务，证书身份为 SignPath Foundation。它通过核验开源仓库、自动构建与项目控制权来提供签名，不要求申请者购买个人证书。

前提包括公开开源许可、已有发行与功能说明、项目持续维护、可核验的项目信誉、构建来源可验证及团队双因素认证。申请需要审核，新项目不能保证即时或最终获批。

建议顺序：

1. 将经过整理的源码发布到目标 GitHub 账号，配置自动构建。
2. 发布明确标注测试状态的发行物，准备签名与隐私说明。
3. 由仓库所有者开启 GitHub 双因素认证并提交 SignPath 申请。
4. 获批后配置 GitHub Actions 与 SignPath，构建完成后由授权者确认签名。
5. 对签名后的 EXE 再验证签名、时间戳与 SHA-256，重新运行扫描和报告检查。

技术脚本可由 Codex 配置；申请确认、账号登录、双因素认证与发布授权由用户本人完成。目前没有提交申请，也没有将这个新项目描述为已获准使用该服务。

- [官方介绍](https://signpath.org/)
- [官方申请条件](https://signpath.org/terms)
- [申请入口](https://signpath.org/apply)

### 2. 付费个人证书或云签名

例如 SSL.com 官方列有 IV Code Signing，面向个人开发者，不要求企业资料。申请人通常需要按官方流程完成身份核验，并选择云端签名或受保护的硬件密钥方式。中国大陆个人的具体受理、证件要求、税费及云签名附加费用尚未确认，应在付款前向供应商核实。

Certum 的 Open Source Code Signing in the Cloud 页面显示从 €49 起，但核对时页面同时标注缺货；不能据此保证可以立即购买。其是否接受申请人的地区与材料也需另行确认。

流程是：确认地区与个人资格 → 确认全部费用 → 本人注册并完成核验 → 取得签名账号或证书 → 安装相应签名工具 → 给最终 EXE 签名并加时间戳 → 验证签名和运行。无需用户学习 C++ 或自己写构建脚本。

证件只通过供应商官方核验页面提交；不需要发到聊天里。签名私钥、账号密码和一次性验证码也不写进仓库。

- [SSL.com 个人 IV 代码签名](https://www.ssl.com/products/software-integrity/code-signing/)
- [Certum 开源代码签名产品](https://shop.certum.eu/open-source-code-signing-on-simplysign.html)

### 3. 微软 Artifact Signing

微软官方最新快速入门列明：Public Trust 个人开发者目前必须位于美国或加拿大。按中国大陆个人申请，目前不适用，不能靠选择其他 Azure 数据中心解决申请资格问题。

- [地区与个人资格要求](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)

## 当前建议

先完成测试与开源准备，评估 SignPath 免费申请；只有确定需要立即公开分发且免费途径不适用时，再考虑经过地区与总价核实的个人付费签名。签名不能消除所有系统限制，仍需在目标机器实测。

当前没有改动 Windows 安全策略、证书信任或注册表，没有申请签名服务、付款、上传证件或向第三方发送文件。
