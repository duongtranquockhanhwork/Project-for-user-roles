"""Convert contribution/member-*.md to PDF (contribution/member-*.pdf).

Usage:  python docs/build_contributions.py
"""
import pathlib

from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = """body{font:11pt/1.45 'Times New Roman',serif;margin:0}h1{font-size:16pt}h2{font-size:12.5pt;
border-bottom:1px solid #999}table{border-collapse:collapse;width:100%}th,td{border:1px solid #777;
padding:3px 5px;text-align:left}blockquote{border-left:3px solid #b54708;margin:6px 0;padding:2px 8px;
background:#fff6e8}code{font:9.5pt Consolas,monospace}"""


def main():
    md = MarkdownIt("commonmark").enable("table")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for src in sorted((ROOT / "contribution").glob("member-*.md")):
            page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
                             f"<body>{md.render(src.read_text(encoding='utf-8'))}</body></html>")
            page.pdf(path=str(src.with_suffix(".pdf")), format="A4",
                     margin={"top": "18mm", "bottom": "18mm", "left": "18mm", "right": "18mm"})
            print("written", src.with_suffix(".pdf").name)
        browser.close()


if __name__ == "__main__":
    main()
