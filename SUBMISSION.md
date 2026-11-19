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

Permissions the app asks for: showing a window (`--share=ipc`, `--socket=wayland`, `--socket=fallback-x11`,
`--device=dri`) and **the internet** (`--share=network`), used only for the optional Office Pro purchase (prices,
checkout and license checks; see `PRIVACY.md`). Files come and go through the file chooser and print portals; no
filesystem access.

## Packages

Depot takes a package per architecture. Both are built with the official Flatpak builder from the
commit the manifest pins, installed and tested on each architecture:

- `com.charleshartmann.Office-1.1.0-x86_64.flatpak`: computers
- `com.charleshartmann.Office-1.1.0-aarch64.flatpak`: phones, tablets and ARM computers

They are attached, with `SHA256SUMS`, to the GitHub release
[v1.1.0](https://github.com/chartmann1590/hartmann-office/releases/tag/v1.1.0) and kept in `~/luma-apps/bundles/`. Upload both in Connect.

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

## Billing (Office Pro)

The app is free; **Office Pro** is an optional purchase through the shared Hartmann Studios license server (the
Cloudflare Worker `livecaptionn-premium`, `/v2` API) and Stripe Checkout, the same system as the studio's direct
Android builds. No Stripe key is in the app.

**For the listing (Luma review 3.6):** the description already says the app is free with an optional purchase,
and names the extras. In Connect, mark the app as offering in-app purchases if the form asks. Prices and trial
lengths are read live from the license server, never hard-coded.

**Sign-in declaration (2.4):** `none`. Buying asks for an email for the receipt and license; it does not create
an account, and nothing in the app needs one.

**What the license server needs before purchases work:** an app entry `hartmann-office` in its catalog with three Stripe
prices. Until then the panel says "Purchases aren't open for this app yet" and everything else works.

| Product key | Label | Stripe mode | Price |
| --- | --- | --- | --- |
| `office_pro:monthly` | Office Pro (Monthly) | subscription | $2.99 / month |
| `office_pro:yearly` | Office Pro (Yearly) | subscription | $19.99 / year, 7-day free trial |
| `office_lifetime` | Office Pro (Lifetime) | payment | $39.99 once |

The catalog entry, in the shape the server already serves for Nightsay (`GET /v2/catalog?app=nightsay`):

```json
{
  "app": "hartmann-office",
  "name": "Hartmann Office",
  "products": {
    "office_pro:monthly": {
      "mode": "subscription",
      "trial_days": 0,
      "implies": [],
      "display": {
        "label": "Office Pro (Monthly)",
        "amount": 299,
        "interval": "month",
        "consumable": false
      }
    },
    "office_pro:yearly": {
      "mode": "subscription",
      "trial_days": 7,
      "implies": [],
      "display": {
        "label": "Office Pro (Yearly)",
        "amount": 1999,
        "interval": "year",
        "consumable": false
      }
    },
    "office_lifetime": {
      "mode": "payment",
      "trial_days": 0,
      "implies": [],
      "display": {
        "label": "Office Pro (Lifetime)",
        "amount": 3999,
        "interval": null,
        "consumable": false
      }
    }
  }
}
```

Checkout returns to the server's own `/v2/return` page; the app doesn't need a redirect. It reads the Checkout
session id from the checkout address and asks `/v2/entitlement` until Stripe confirms the payment.

## Listing text (also in the metainfo)

- **Name:** Hartmann Office
- **Summary:** Documents, spreadsheets and presentations
- **Developer:** Hartmann Studios
- **Category:** Work (Office)
- **Licence:** GPL-3.0-or-later
- **Content rating:** OARS 1.1, no objectionable content
- **Screenshots:** `screenshots/document.png`, `spreadsheet.png`, `presentation.png` (computer), `tablet.png`, `phone.png`, `tv.png`
