# SignPath 申请材料与状态

申请入口：https://signpath.org/apply

## 可用于填写的项目事实

| 项目 | 内容 |
| --- | --- |
| Project name | DiskInventory |
| Source repository | https://github.com/Shizao315/disk-inventory |
| Project/download page | https://github.com/Shizao315/disk-inventory |
| License | MIT；第三方运行库许可证另附 |
| Maintainer / approver | Shizao315 |
| Code signing policy | https://github.com/Shizao315/disk-inventory/blob/main/CODE_SIGNING_POLICY.md |
| Existing successful CI | https://github.com/Shizao315/disk-inventory/actions/runs/42459081210 |
| GitHub MFA | 维护者于 2026-11-08 确认已开启；属于用户确认，非工具读取证明 |
| Project age | 2026-11-08 新建；目前没有长期维护历史或既有社区信誉证明 |
| Application status | 维护者于 2026-11-08 提交，并提供服务方收件回执截图；等待审核，尚未获批 |

联系姓名与邮箱请由维护者在官方申请表中填写，不在公开文档中预填个人资料。若表单询问长期信誉、用户规模、第三方推荐等，本项目目前没有相应证据，应如实填写。

## English description

DiskInventory is a new MIT-licensed Windows desktop utility that inventories filesystem metadata and creates a self-contained offline HTML report. The report offers a global file-size ranking and an Explorer-style folder browser, with switchable or simultaneous views. It records file names, paths, logical sizes, extensions, creation times and last-modification times, with an option to include hidden items.

The application uses native C++/Win32 APIs. It does not index file contents, upload disk scan results or install a background service. NTFS full-volume indexing is implemented with MFT enumeration and separate metadata enrichment, with native directory enumeration as a fallback. Full-volume MFT performance and large real-world inventories are not yet validated.

The public GitHub-hosted Windows build has passed eight scanner/native-window integration checks and browser checks, including a synthetic 12,001-record report. The project was created on 8 November 2026 and does not yet have an established public reputation. We are requesting an eligibility review for free open-source code signing; we understand that approval is not automatic.

## Submission receipt

On 8 November 2026 the maintainer submitted the application and supplied a screenshot of the SignPath Foundation submission acknowledgement. The acknowledgement confirms receipt and says the team intends to respond within the next few business days. It is not an approval, a certificate issuance, or permission to sign. No application reference was supplied. Personal contact details and the email screenshot are not stored in this public repository.

## Application notes

- Confirm the official form's terms, contact identity and intended use yourself.
- Check that the code signing policy and download page are publicly accessible.
- Describe the project as new; do not imply that SignPath already supports or signs it.
- Keep the provider's response or application reference. After approval, configure the real organization ID, project slug, signing-policy slug and credential through the supported account settings.
- Never paste the API token, password, OTP, recovery codes or signing private key into this document or chat.
