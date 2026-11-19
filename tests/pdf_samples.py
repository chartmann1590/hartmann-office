"""Write sample PDFs of the three seeded files to /root/ho/pdf/ (dev check)."""
import os, sys, tempfile
sys.path.insert(0, "src")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
from hoffice.library import Library
from hoffice import render
class W: pass
win = W(); win.library = Library(); win.open_entry = lambda e: None; win.refresh = lambda: None
exec(compile(open("tests/seed_dev.py").read(), "seed", "exec"), {"win": win, "os": os})
os.makedirs("pdf", exist_ok=True)
for e in win.library.list():
    n = render.write_pdf(f"pdf/{e.kind}.pdf", win.library.read(e), e.title)
    print(e.kind, n, "pages")
