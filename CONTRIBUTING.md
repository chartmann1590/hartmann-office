# Contributing

Thanks for helping make Hartmann Office better.

## Reporting a problem

[Open an issue](https://github.com/chartmann1590/hartmann-office/issues/new/choose) and say which editor, which
device, and the steps that show it. A small file that shows the problem helps most. Leave out anything private.

## Sending a change

1. Fork the repository and make a branch.
2. Keep each pull request to one change.
3. Run the checks:
   ```sh
   python3 -m pytest tests/test_formula.py tests/test_odf.py
   xvfb-run flatpak run --command=python3 org.projectluma.Sdk//44 tests/test_ui.py
   luma lint && luma test
   ```
4. For anything you can see, try it at phone width (360 px) and on a computer, in light and dark.
5. Say in the pull request what you tested.

## Style

- Use LumaUI parts (`luma_appkit`) before writing your own widget, and Luma's colour tokens, never fixed colours.
- Words in the interface are short and plain, in sentence case.
- The app asks for no permissions beyond showing a window. Files come and go through the portals.
- `formula.py` and `odf.py` don't import GTK, so they can be tested anywhere. Keep it that way.

By contributing you agree your work is licensed under GPL-3.0-or-later.
