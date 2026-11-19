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
`--device=dri`) and **the internet** (`--share=network`), used for the optional Office Pro purchase (prices, checkout
and license checks) and update checks against GitHub releases (see `PRIVACY.md`). Files come and go through the file chooser and print portals; no
filesystem access.

## Packages

Depot takes a package per architecture. Both are built with the official Flatpak builder from the
commit the manifest pins, installed and tested on each architecture:

- `com.charleshartmann.Office-1.1.0-x86_64.flatpak`: computers
- `com.charleshartmann.Office-1.1.0-aarch64.flatpak`: phones, tablets and ARM computers

They are attached, with `SHA256SUMS`, to the GitHub release
[v1.1.0](https://github.com/chartmann1590/hartmann-office/releases/tag/v1.1.0) and kept in `~/luma-apps/bundles/`. Upload both in Connect.

## Steps

Done: the public repository, the pinned manifest commit (`493b1045…`), both 1.1.0 packages on the GitHub
release, and the live Office Pro catalog. A private 1.0.0 draft already exists in Connect (x86_64, with TV
support and screenshots); keep it and update it rather than starting a new one:

1. **Package:** replace the 1.0.0 x86_64 bundle with `com.charleshartmann.Office-1.1.0-x86_64.flatpak` and add
   `com.charleshartmann.Office-1.1.0-aarch64.flatpak`, checking each against the SHA-256 above. Version `1.1.0`.
2. **TV:** keep TV support; the 1.1.0 packages still carry the tile and `X-Luma-TV` keys (`presentation = fullscreen`).
3. **What's new:** "Office Pro, an optional purchase: templates, premium slide themes, version history, and
   headers, footers and page numbers. Everything that was free stays free."
4. **Description:** the 1.1.0 metainfo adds the paragraph saying the app is free with an optional Office Pro
   purchase through Stripe (review 3.6).
5. **Permissions:** 1.1.0 adds `--share=network` (Depot shows it as "Uses the internet"), used only for Office Pro.
6. **Privacy policy:** same link, updated text (`PRIVACY.md`) covering the license server and Stripe.
7. **In-app purchases / pricing:** say yes if the form asks; prices come from the live catalog. **Sign-in:** `none`.
8. **Screenshots:** the draft's set can stay; the repo also has computer, tablet, phone and TV shots
   (`screenshots/`). Store screenshots must not show prices, so the upgrade panel isn't among them.
9. **Review.** Only Charles sends it for review.

## 1.1.0 release check (2026-11-19)

**Packages** (GitHub release [v1.1.0](https://github.com/chartmann1590/hartmann-office/releases/tag/v1.1.0); built with
`org.flatpak.Builder` from source commit `493b1045068067fe2a3a09fab1010e243a7bfa8d`, the commit the manifest pins; runtime
`org.projectluma.Platform//44`):

| Architecture | File | SHA-256 |
| --- | --- | --- |
| x86_64 (computers, TVs) | `com.charleshartmann.Office-1.1.0-x86_64.flatpak` | `b7b6d12bf5c31364fac137ee2719b4dbdc4fa4de3c7cfec189a3fb2eed9daf51` |
| aarch64 (phones, tablets, ARM computers) | `com.charleshartmann.Office-1.1.0-aarch64.flatpak` | `5a252f58f5329ec8277b62942a7d887965be3a146f1a5d2fdb0597c3f42d8111` |

One package per architecture serves computer, tablet, phone and TV (LumaUI adapts by width, input and posture).
Permissions: network (Office Pro only), display. The same paid-feature, network and privacy disclosure applies on every device: free app,
optional Office Pro through Stripe, email to the license server and Stripe only when buying or restoring.

**What was verified, and where.** None of this ran on a real Luma phone, tablet or TV.

| Check | Where it ran | Result |
| --- | --- | --- |
| UI tests (6), driving the real app | Luma SDK runtime, x86_64 (Proxmox build container) and aarch64 (Docker on Apple Silicon), virtual display | passed |
| Bundle builds, installs, reports version 1.1.0 | same two environments | passed |
| Packaged billing code reads the live catalog | both installed packages, both architectures, live server, read-only | exactly the three products: $2.99 a month; $19.99 a year, first 7 days free; $39.99 once |
| Upgrade panel shows live prices; Buy creates a live Stripe Checkout session (`cs_live_…`); app waits; Cancel returns to the plans; nothing unlocks | x86_64, virtual display, live server; reserved test address, no browser, no card, no payment | passed |
| Restore for an address that never bought | both packages, live server | "no purchase", nothing unlocked |
| Purchase, restore and expiry logic against a server speaking the same `/v2` API | unit tests with a local fake server | passed |
| Computer, tablet, phone and TV layouts | screenshots in the Luma runtime with Luma's device switches (TV posture forced, no Luma shell) | reviewed |
| Real Luma device (phone, tablet, TV), sound, lock-screen controls, portals | not run | **not verified** |
| Completed payment, trial enrollment, cancellation in Stripe's portal, restore of a real purchase | not run (no live charges; no test-mode server exists) | **not verified** |
| `luma release-check` conformance evidence | not run in Luma's SDK test-image lanes | fails as expected; evidence file left honest |

## Billing (Office Pro)

The app is free; **Office Pro** is an optional purchase through the shared Hartmann Studios license server (the
Cloudflare Worker `livecaptionn-premium`, `/v2` API) and Stripe Checkout, the same system as the studio's direct
Android builds. No Stripe key is in the app.

**For the listing (Luma review 3.6):** the description already says the app is free with an optional purchase,
and names the extras. In Connect, mark the app as offering in-app purchases if the form asks. Prices and trial
lengths are read live from the license server, never hard-coded.

**Sign-in declaration (2.4):** `none`. Buying asks for an email for the receipt and license; it does not create
an account, and nothing in the app needs one.

**Live since 2026-11-19:** the license server's catalog lists `hartmann-office` with the three approved Stripe prices
(registered by the studio's billing maintainer; nothing in this repo creates prices). Public readback of
`/v2/catalog?app=hartmann-office`:

| Product key | Label | Stripe mode | Price |
| --- | --- | --- | --- |
| `office_pro:monthly` | Office Pro (Monthly) | subscription | $2.99 / month |
| `office_pro:yearly` | Office Pro (Yearly) | subscription | $19.99 / year, 7-day free trial |
| `office_lifetime` | Office Pro (Lifetime) | payment | $39.99 once |

The public catalog it serves:

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
