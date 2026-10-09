# Debian releases

A release is built from a pushed `vX.Y.Z` tag. The workflow tests the exact tagged commit and publishes one amd64 `.deb` plus `SHA256SUMS` to GitHub Releases. The package version, Debian metadata, and tag must agree. A pre-existing Release is a hard failure; create a new version/tag for corrections.

## Maintainer procedure

1. Update `pyproject.toml` version and relevant package changelog text; run the documented tests and package checks.
2. Review and commit/push the source changes under the normal separate authorization. No version bump is performed by the workflow.
3. Only when separately authorized, create and push the matching `vX.Y.Z` tag. The push starts GitHub Actions; inspect the complete build/test and publish jobs.
4. Verify both Release assets and download them. In the download directory run `sha256sum -c SHA256SUMS`.

The workflow uses a read-only build/test job and a separate `contents: write` publish job with GitHub's built-in token. The publish job does not check out the repository or execute repository scripts; it validates only the downloaded package/checksum and performs GitHub CLI API operations. Actions are pinned to full commit SHAs. The first public release `v0.2.3` was published after explicit owner authorization. [GitHub Actions run 37937954360](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/37937954360) passed both jobs, including 133 tests. Both assets were downloaded from [the Release](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.3); SHA256SUMS and package metadata were independently verified. This confirms repository/token policy for that run, not future runs or desktop acceptance. The task branch was pushed; it has not been merged into `main`.

## Download and install

Download the `.deb` and `SHA256SUMS` from the Release, verify the checksum, then install as the user with `sudo apt install ./giga-pisar-dictation_VERSION_amd64.deb`. This is a manually downloaded package; no APT repository or automatic updates are provided. The target remains Linux Mint 22.x/Cinnamon/X11; CI on Ubuntu 24.04 is not desktop acceptance.

Owner-published binary downloads are permitted by the notice. No license is granted, and public availability does not grant redistribution or reuse permission. No open-source license is selected. GitHub Release distribution does not change package layout, runtime behavior, or the requirement for separate desktop/LAN acceptance.
