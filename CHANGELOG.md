# Changelog

## 1.2.1 (2026-11-19)

- Combine the GitHub release checker with scoped lifetime promotion entry and exact purchased-plan labels.

## 1.2.0 (2026-11-19)

- Update alerts: Hartmann Office watches its GitHub releases and tells you when a new version is out, with the release
  notes. Copies from Depot update through Depot (Luma's own updater); copies downloaded from GitHub download
  the bundle for this device, check it against the release's checksums, and open it in the system installer,
  which asks you to confirm. Turn automatic checks off in the update panel.

## 1.1.1 (2026-11-19)

- Ready for promotion codes on Office Pro Lifetime: when the store turns them on, the upgrade panel says so and
  codes are entered on Stripe's checkout page. Codes are checked by Stripe; a completed order unlocks exactly like a paid one.

## 1.1.0 (2026-11-19)

- Office Pro, an optional purchase through Stripe: templates, premium slide themes, version history, and
  headers, footers and page numbers. Nothing that was free before costs money now.
- Computer, tablet, phone and TV screenshots; on Luma's TV home.

## 1.0.0 (2026-11-18)

The first release.

- Documents: title, headings, lists, quotes, inline formatting, alignment, word count, find and replace, Letter or A4.
- Spreadsheets: formula engine with more than 50 functions, several sheets, number formats, sorting, fill down,
  insert and delete rows and columns, copy and paste.
- Presentations: three slide layouts, five themes, speaker notes, full screen Present.
- OpenDocument files (.odt, .ods, .odp), CSV and Markdown; PDF export and printing.
- Autosave, and Deleted keeps files for 30 days.
