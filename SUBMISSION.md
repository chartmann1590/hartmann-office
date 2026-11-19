# Submitting Hartmann Office to Depot

Everything in this repository is ready for review. A person submits, not an agent, so these are the steps
for the publisher (Hartmann Studios).

## What is already done

| Check | Result |
| --- | --- |
| `luma lint` | passed |
| `luma test` (360, 500, 1024, 1280 px × pointer, touch, keyboard) | passed |
| `appstreamcli validate --no-net --pedantic` (AppStream 1.1.3) | passed (one pedantic note: capital letters in the reverse-DNS ID, which is normal) |
| `desktop-file-validate` | passed |
| `flatpak-builder-lint manifest` (real manifest, GitHub URL, pinned commit) | passed |
| Build with `org.flatpak.Builder` 1.4.12 on `org.projectluma.Platform//44`, installed and run in its sandbox | passed |
| Unit tests (formula engine, OpenDocument round trips) and UI tests in the Luma runtime | 13 + 5 passed |
| `luma release-check` | **fails until real conformance evidence exists**: it wants evidence from Luma's SDK test-image lanes on `x86_64` *and* `aarch64`, desktop and mobile. The tests above ran on both architectures, but not in those lanes, so the evidence file is left honest (all false); never fill it in by hand. |

Permissions the app asks for: none beyond showing a window (`--share=ipc`, `--socket=wayland`,
`--socket=fallback-x11`, `--device=dri`). Files come and go through the file chooser and print portals.
No network, no filesystem access.

## Packages

Depot takes a package per architecture. Both are attached to the GitHub release
[v1.0.0](https://github.com/chartmann1590/hartmann-office/releases/tag/v1.0.0), built with the official Flatpak builder from the
commit the manifest pins, installed and tested on each architecture:

- `com.charleshartmann.Office-1.0.0-x86_64.flatpak`: computers
- `com.charleshartmann.Office-1.0.0-aarch64.flatpak`: phones, tablets and ARM computers

`SHA256SUMS` sits beside them. Upload both in Connect.

## Steps

1. **Publish the source.** Create the public repository `github.com/chartmann1590/hartmann-office` and push
   `main` (the metainfo's links and screenshot URLs point there).
2. **Pin the commit.** In `flatpak/com.charleshartmann.Office.json`, replace `COMMIT_PLACEHOLDER` with the full
   40-character commit you want Luma to build (`git rev-parse HEAD`), commit that, and push. Luma rejects a git
   source without a full commit.
3. **Join the developer program** at https://hub.simplyluma.com/connect/developer.
4. **Prove the namespace.** The app ID is `com.charleshartmann.Office`, so you prove you control
   `charleshartmann.com` (Connect shows how). If you'd rather prove a GitHub account instead, the ID would
   become `io.github.chartmann1590.HartmannOffice` in every file; choose before the first submission,
   because an app ID is permanent.
5. **Submit the release** in Connect with the name `Hartmann Office` and the ID `com.charleshartmann.Office`.
   The listing (summary, description, screenshots, categories, licence, links, release notes, OARS rating) is
   read from `data/com.charleshartmann.Office.metainfo.xml`. For the privacy policy, give the link to
   `PRIVACY.md` in the repository.
6. **Review.** Luma builds the manifest, validates the metainfo and desktop file, runs
   `flatpak-builder-lint`, computes permissions, then a person reviews the first release.

## Listing text (also in the metainfo)

- **Name:** Hartmann Office
- **Summary:** Documents, spreadsheets and presentations
- **Developer:** Hartmann Studios
- **Category:** Work (Office)
- **Licence:** GPL-3.0-or-later
- **Content rating:** OARS 1.1, no objectionable content
- **Screenshots:** `screenshots/document.png`, `spreadsheet.png`, `presentation.png` (computer), `tablet.png`, `phone.png`, `tv.png`
