"""Combine the docs/*.md files into docs/Project_Documentation.pdf (make docs-pdf).

The Markdown is put in one HTML page (rendered with marked.js and mermaid.js)
and printed to PDF with headless Chrome. Needs Chrome and internet access.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT_PDF = DOCS / "Project_Documentation.pdf"
OUT_HTML = DOCS / "Project_Documentation.html"

# (file, title in the table of contents)
SECTIONS = [
    ("architecture.md", "1. Architecture diagram and blocks"),
    ("HLD.md", "2. High-level design"),
    ("LLD.md", "3. Low-level design (API endpoints and I/O)"),
    ("test_plan.md", "4. Test plan and test cases"),
    ("test_report.md", "4b. Test report (latest run)"),
    ("user_manual.md", "5. User manual"),
]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Financial Complaint Router - Documentation</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #222; }
  h1 { font-size: 20pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; color: #1f4e79; }
  h2 { font-size: 14pt; color: #1f4e79; margin-top: 18px; }
  h3 { font-size: 12pt; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; page-break-inside: auto; }
  tr { page-break-inside: avoid; }
  th, td { border: 1px solid #bbb; padding: 4px 6px; vertical-align: top; text-align: left; }
  th { background: #e8eef5; }
  code { background: #f2f2f2; padding: 0 3px; border-radius: 3px; font-size: 9pt; }
  pre { background: #f6f6f6; padding: 8px; border-radius: 4px; white-space: pre-wrap; font-size: 8.5pt; }
  pre code { background: none; padding: 0; }
  .doc { page-break-before: always; }
  .cover { text-align: center; padding-top: 220px; }
  .cover h1 { border: none; font-size: 28pt; }
  .toc { page-break-before: always; }
  .toc li { font-size: 12pt; margin: 6px 0; }
  .mermaid { text-align: center; margin: 10px 0; }
</style></head>
<body>
<div class="cover">
  <h1>Financial Complaint Router</h1>
  <p style="font-size:14pt">AI system that routes customer complaints, flags urgent ones<br>
  and shows similar past cases - built with AIOps practices</p>
  <p style="margin-top:60px">Project documentation<br>__DATE__</p>
</div>
<div class="toc"><h1>Contents</h1><ol style="list-style:none;padding:0">__TOC__</ol></div>
__DOCS__
<script>
  document.querySelectorAll("script[type='text/markdown']").forEach(function (src) {
    var div = document.createElement("div");
    div.className = "doc";
    div.innerHTML = marked.parse(src.textContent);
    // ```mermaid code blocks become diagrams
    div.querySelectorAll("code.language-mermaid").forEach(function (code) {
      var box = document.createElement("div");
      box.className = "mermaid";
      box.textContent = code.textContent;
      code.parentElement.replaceWith(box);
    });
    src.replaceWith(div);
  });
  mermaid.initialize({ startOnLoad: false, theme: "default", flowchart: { useMaxWidth: true } });
  mermaid.run().then(function () { document.title = "READY"; });
</script>
</body></html>
"""


def find_chrome() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("Chrome/Chromium not found - install one of them to print the PDF.")


def main() -> None:
    toc, docs = [], []
    for filename, title in SECTIONS:
        text = (DOCS / filename).read_text(encoding="utf-8")
        toc.append(f"<li>{html.escape(title)}</li>")
        # Markdown goes inside a <script> tag, so escape "</script".
        docs.append('<script type="text/markdown">\n' + text.replace("</script", "<\\/script") + "\n</script>")

    page = (PAGE.replace("__DATE__", date.today().strftime("%d %B %Y"))
                .replace("__TOC__", "\n".join(toc))
                .replace("__DOCS__", "\n".join(docs)))
    OUT_HTML.write_text(page, encoding="utf-8")

    subprocess.run([
        find_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", "--virtual-time-budget=20000",
        f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri(),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    OUT_HTML.unlink()
    print(f"Wrote {OUT_PDF.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
