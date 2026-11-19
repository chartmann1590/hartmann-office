# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for checking the layout (APP_SHOT=/path.png APP_WIDTH=360 ./run-app). Not used in normal runs."""
import os

from gi.repository import GLib, Graphene, Gtk


def _settle_text(widget):
    """Headless X has no frame clock driving GtkTextView's lazy line layout; finish it before capturing."""
    if isinstance(widget, Gtk.TextView):
        buf = widget.get_buffer()
        widget.get_iter_location(buf.get_end_iter())
        widget.get_line_yrange(buf.get_end_iter())
        widget.queue_draw()
    child = widget.get_first_child()
    while child is not None:
        _settle_text(child)
        child = child.get_next_sibling()


def screenshot(window, path):
    _settle_text(window)
    ctx = GLib.MainContext.default()
    for _ in range(200):
        if not ctx.iteration(False):
            break
    width, height = window.get_width(), window.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(window).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    app = window.get_application()
    print("shot", path, width, height, node is not None, window.get_mapped(), window.get_realized(),
          [(type(w).__name__, w.get_width(), w.get_mapped()) for w in (app.get_windows() if app else [])], flush=True)
    if node is None:
        return
    texture = window.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, width, height))
    texture.save_to_png(path)


def schedule(window, path):
    window.set_default_size(int(os.environ.get("APP_WIDTH", "1024")), int(os.environ.get("APP_HEIGHT", "720")))
    if os.environ.get("XSHOT"):
        window.maximize()
    script = os.environ.get("APP_SCRIPT")
    if script:
        GLib.timeout_add(900, lambda: (exec(compile(open(script).read(), script, "exec"), {"win": window, "GLib": GLib, "Gtk": Gtk, "os": os}), False)[1])
    GLib.timeout_add(int(os.environ.get("APP_DELAY", "2500")),
                     lambda: (screenshot(window, path), window.get_application().quit()) and False)
