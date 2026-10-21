"""
Build submission.pdf from submission.md
=======================================
Markdown → HTML (python-markdown) → PDF (headless Google Chrome).
No pandoc/LaTeX needed.

Usage:
    pip install markdown
    python scripts/build_pdf.py
"""

import pathlib
import subprocess
import sys
import tempfile

import markdown

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

CSS = """
@page { size: Letter; margin: 0.6in 0.65in; }
body { font: 10.5pt/1.45 -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
h2, h3 { page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { background: #f2f2f2; }
code { font: 9pt Menlo, monospace; background: #f4f4f4; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f6f6f6; border: 1px solid #ddd; padding: 6pt 8pt; line-height: 1.3;
      white-space: pre-wrap; word-break: break-word; }
pre code { background: none; padding: 0; font-size: 8pt; }
img { max-width: 100%; border: 1px solid #ccc; }
a { color: #0b57d0; text-decoration: none; }
"""


def main():
    repo = pathlib.Path.cwd()
    body = markdown.markdown((repo / 'submission.md').read_text(),
                             extensions=['meta', 'tables', 'fenced_code'])
    # <base> lets relative paths like docs/rag-screenshot.png resolve from the repo.
    html = (f'<!doctype html><html><head><meta charset="utf-8"><base href="{repo.as_uri()}/">'
            f'<title>CS 452 Conference Talk RAG - Trevor Wattles</title><style>{CSS}</style></head>'
            f'<body>{body}</body></html>')

    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as f:
        f.write(html)
    result = subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                             '--allow-file-access-from-files', f'--print-to-pdf={repo / "submission.pdf"}',
                             pathlib.Path(f.name).as_uri()], capture_output=True, text=True)
    pathlib.Path(f.name).unlink()
    if result.returncode != 0:
        print(result.stderr[-1000:])
        sys.exit(1)
    print('✅ Wrote submission.pdf')


if __name__ == '__main__':
    main()
