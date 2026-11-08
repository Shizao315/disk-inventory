# Code signing policy

## Current status

DiskInventory is an MIT-licensed project maintained at [Shizao315/disk-inventory](https://github.com/Shizao315/disk-inventory). The project is preparing an application for SignPath Foundation's free open-source signing service. **It has not been accepted, no signing certificate is currently available, and all published executables remain unsigned.**

The statement “Free code signing provided by SignPath.io, certificate by SignPath Foundation” will apply only after the service has approved the project and a release has actually been signed. It is not a claim about current downloads.

## Responsibilities

- Maintainer, committer and reviewer: [Shizao315](https://github.com/Shizao315).
- Release and signing approver: Shizao315.
- Automated coding and build assistance does not independently authorize a signing request or release.
- The maintainer confirms that GitHub two-factor authentication has been enabled. SignPath account MFA must also be enabled before use.

The maintainer reviews source/build changes, chooses the release source, and approves production signing. No unrelated third-party binaries may be submitted under this project's signing identity.

## Build and signing process

1. Build from this public repository on a GitHub-hosted Windows runner.
2. Run the synthetic scanner/native-window integration checks and offline HTML browser checks.
3. Preserve the unsigned executable as an artifact of that run.
4. After project approval and credential configuration, the owner may manually start the signing workflow from `main`. The configured signing policy must require owner approval.
5. Sign only the `DiskInventory.exe` built in that workflow, with product name `DiskInventory` and matching product/file version metadata.
6. Validate the returned Authenticode signature and timestamp, keep the unsigned and signed hashes, and rerun scanner/browser checks on the returned executable before making the signed build available.

Signing credentials belong in the provider's protected key storage and GitHub Actions secrets, not in source files, issues, chat messages or downloadable reports.

## Privacy policy

The scanner reads filesystem metadata selected by the user and writes the chosen local report. It does not read file contents for indexing, upload scan results, perform telemetry, install a background service, or change operating-system security policy.

The exported HTML contains its data, JavaScript and styles and does not make HTTP/HTTPS requests. A user-selected network share, or a local-file link pointing to such a share, can cause normal operating-system/browser access to that location.

The development workflow downloads the declared compiler and test dependencies. A future, explicitly started signing workflow will transmit the unsigned software artifact and public build-origin metadata to SignPath; it will not transmit the user's disk scan reports. These development services have their own policies: [GitHub](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement), [SignPath](https://about.signpath.io/privacy-policy).

The repository includes only synthetic examples; users decide whether to share reports containing their own filenames and paths.
