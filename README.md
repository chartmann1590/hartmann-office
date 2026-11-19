# Hartmann Office

Documents, spreadsheets and presentations in one app made for [Luma](https://simplyluma.com).
It is built with LumaUI and fits a computer, a tablet and a phone.

- **Documents**: title, headings, lists, quotes, bold, italic, underline, strikethrough and alignment;
  word count; find and replace; Letter or A4 pages.
- **Spreadsheets**: formulas (SUM, AVERAGE, IF, VLOOKUP, SUMIF, COUNTIF, PMT, DATE, ROUND, CONCAT and more),
  several sheets, number formats, sorting, fill down, insert and delete rows and columns, copy and paste.
- **Presentations**: title, points and section slides; five themes; speaker notes; full screen Present mode.
- **Files**: OpenDocument (.odt, .ods, .odp) that other office apps read, plus CSV and Markdown.
  Export to PDF or print. Everything saves as you go; deleted files wait 30 days in Deleted.

No account, no network, no tracking. Files live in the app's own folder and move in and out through the
system file picker.

## Keyboard

| Keys | Does |
| --- | --- |
| Ctrl+N, Ctrl+Shift+N, Ctrl+Alt+N | New document, spreadsheet, presentation |
| Ctrl+O / Ctrl+Shift+S | Open / Save a copy |
| Ctrl+E / Ctrl+P | Export as PDF / Print |
| F5 | Present |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Ctrl+B, Ctrl+I, Ctrl+U | Bold, italic, underline |
| Ctrl+1, Ctrl+2, Ctrl+3, Ctrl+0 | Heading 1–3, body text |
| Ctrl+F | Find and replace |
| F2 or typing | Edit the selected cell (the bar is the formula bar) |
| Ctrl+D | Fill down |
| F9 | Show or hide the sidebar |

## Build

On Luma, or anywhere with the Luma SDK (`x86_64`):

```sh
flatpak remote-add --if-not-exists luma https://dl.simplyluma.com/luma.flatpakrepo
flatpak install luma org.projectluma.Platform//44 org.projectluma.Sdk//44
flatpak-builder --user --install --install-deps-from=luma build-dir flatpak/com.charleshartmann.Office.json
flatpak run com.charleshartmann.Office
```

Checks: `luma lint`, `luma test`, and the unit tests (`python3 -m pytest tests`).

## Licence

GPL-3.0-or-later. Copyright © 2026 Hartmann Studios.
