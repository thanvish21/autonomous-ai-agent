"""Generate placeholder screenshots so the README renders before real captures exist.

Run: python3 scripts/make_placeholders.py
Replace docs/screenshots/*.png with real captures when available.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

BG = (11, 16, 32)
PANEL = (19, 26, 49)
BORDER = (36, 48, 86)
ACCENT = (56, 189, 248)
ACCENT2 = (129, 140, 248)
TEXT = (230, 236, 255)
MUTED = (148, 163, 196)
OK = (52, 211, 153)


def _font(size: int):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def panel(d, box, fill=PANEL):
    d.rounded_rectangle(box, radius=14, fill=fill, outline=BORDER, width=2)


def header(d, w):
    d.rectangle([0, 0, w, 60], fill=(14, 20, 48))
    d.rounded_rectangle([24, 19, 46, 41], radius=6, fill=ACCENT)
    d.text((58, 22), "Autonomous Agent", font=_font(20), fill=TEXT)
    d.text((w - 280, 24), "Built with Claude tool use", font=_font(14), fill=MUTED)


def shot_trace(path):
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    header(d, w)

    # left history
    panel(d, [16, 76, 296, h - 16])
    d.text((32, 92), "HISTORY", font=_font(13), fill=MUTED)
    for i, (txt, st, col) in enumerate(
        [
            ("Compare Python web frameworks", "completed", OK),
            ("Find anomalies in sales.csv", "running", ACCENT),
            ("Fibonacci first 20 numbers", "completed", OK),
        ]
    ):
        y = 120 + i * 78
        panel(d, [32, y, 280, y + 66], fill=(26, 34, 64))
        d.text((44, y + 10), txt[:30], font=_font(13), fill=TEXT)
        d.text((44, y + 38), st, font=_font(12), fill=col)

    # center: input + trace
    panel(d, [312, 76, 836, 240])
    d.text((328, 92), "NEW TASK", font=_font(13), fill=MUTED)
    panel(d, [328, 118, 820, 196], fill=(26, 34, 64))
    d.text(
        (340, 130),
        "Research the top 5 Python web frameworks,\ncompare them in a table, write a report.",
        font=_font(14),
        fill=TEXT,
    )
    d.rounded_rectangle([720, 204, 820, 232], radius=8, fill=ACCENT)
    d.text((738, 210), "Run agent", font=_font(14), fill=BG)

    panel(d, [312, 256, 836, h - 16])
    d.text((328, 272), "EXECUTION TRACE", font=_font(13), fill=MUTED)
    rows = [
        ("THOUGHT", "Planning: 1) search frameworks 2) compare 3) write report", ACCENT2),
        ("TOOL_CALL", "web_search  {\"query\": \"top python web frameworks 2026\"}", ACCENT),
        ("TOOL_RESULT", "ok  ·  5 results (FastAPI, Django, Flask, …)", OK),
        ("THOUGHT", "Reflection: have data → drafting comparison table", ACCENT2),
        ("TOOL_CALL", "file_manager  {\"action\": \"write\", \"path\": \"report.md\"}", ACCENT),
        ("TOOL_RESULT", "ok  ·  bytes_written: 1843", OK),
        ("THOUGHT", "Goal met → submit_final_answer", ACCENT2),
    ]
    y = 300
    for kind, body, col in rows:
        panel(d, [328, y, 820, y + 56], fill=(26, 34, 64))
        d.rectangle([328, y, 332, y + 56], fill=col)
        d.text((344, y + 8), kind, font=_font(11), fill=MUTED)
        d.text((344, y + 28), body[:62], font=_font(13), fill=TEXT)
        y += 66

    # right: output
    panel(d, [852, 76, w - 16, h - 16])
    d.text((868, 92), "FINAL OUTPUT", font=_font(13), fill=MUTED)
    d.rounded_rectangle([1150, 88, 1248, 112], radius=10, outline=ACCENT, width=2)
    d.text((1166, 92), "running", font=_font(12), fill=ACCENT)
    panel(d, [868, 124, w - 32, h - 32], fill=(26, 34, 64))
    d.text((884, 140), "# Python Web Frameworks", font=_font(17), fill=TEXT)
    lines = [
        "",
        "| Framework | Type    | Best for      |",
        "|-----------|---------|---------------|",
        "| FastAPI   | ASGI    | APIs, async   |",
        "| Django    | Full    | Batteries-inc |",
        "| Flask     | Micro   | Simplicity    |",
        "| Litestar  | ASGI    | Performance   |",
        "| Tornado   | Async   | Long-poll/WS  |",
        "",
        "FastAPI leads for modern async APIs …",
    ]
    yy = 168
    for ln in lines:
        d.text((884, yy), ln, font=_font(13), fill=TEXT if not ln.startswith("|") else MUTED)
        yy += 22

    img.save(path)


def shot_output(path):
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    header(d, w)
    panel(d, [16, 76, w - 16, h - 16])
    d.text((36, 96), "FINAL OUTPUT", font=_font(14), fill=MUTED)
    d.rounded_rectangle([w - 160, 90, w - 36, 118], radius=12, outline=OK, width=2)
    d.text((w - 144, 95), "completed", font=_font(13), fill=OK)

    panel(d, [36, 132, w - 36, h - 120], fill=(26, 34, 64))
    d.text((56, 152), "Sales Anomaly Report", font=_font(24), fill=TEXT)
    body = [
        "",
        "Ran anomaly detection on sales.csv (10 rows) with a z-score test.",
        "",
        "Anomalies found: 2",
        "  • Row 7  — $48,200  (z = 3.1, > 3σ)",
        "  • Row 3  — $120     (z = -2.8, near-zero outlier)",
        "",
        "```python",
        "import pandas as pd, numpy as np",
        "df = pd.read_csv('sales.csv')",
        "z = (df.amount - df.amount.mean()) / df.amount.std()",
        "print(df[z.abs() > 2.5])",
        "```",
        "",
        "Recommendation: verify row 7 against the source system; row 3",
        "looks like a data-entry error (missing trailing digits).",
    ]
    yy = 196
    for ln in body:
        col = ACCENT if ln.strip().startswith("•") else TEXT
        if ln.startswith("```") or ln.startswith("import") or ln.startswith("df") or ln.startswith("z ") or ln.startswith("print"):
            col = OK
        d.text((56, yy), ln, font=_font(15), fill=col)
        yy += 26

    panel(d, [36, h - 108, w - 36, h - 36], fill=(26, 34, 64))
    d.text((56, h - 96), "ARTIFACTS", font=_font(12), fill=MUTED)
    d.text((56, h - 72), "report.md   ·   analysis.py   ·   sales.csv", font=_font(14), fill=ACCENT)

    img.save(path)


def shot_history(path):
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    header(d, w)
    panel(d, [16, 76, 460, h - 16])
    d.text((36, 96), "HISTORY", font=_font(14), fill=MUTED)
    items = [
        ("Email framework report to me", "awaiting_confirmation", (251, 191, 36), "12s ago"),
        ("Find anomalies in sales.csv", "completed", OK, "3m ago"),
        ("Monitor example.com hourly", "running", ACCENT, "8m ago"),
        ("Compare Python web frameworks", "completed", OK, "1h ago"),
        ("Summarise a web page", "completed", OK, "2h ago"),
        ("Fibonacci first 20 numbers", "failed", (248, 113, 113), "3h ago"),
    ]
    y = 128
    for txt, st, col, when in items:
        panel(d, [36, y, 440, y + 78], fill=(26, 34, 64))
        d.text((52, y + 12), txt[:40], font=_font(15), fill=TEXT)
        d.rounded_rectangle([52, y + 44, 52 + 12 + 9 * len(st), y + 66], radius=10, outline=col, width=2)
        d.text((60, y + 48), st, font=_font(12), fill=col)
        d.text((360, y + 48), when, font=_font(12), fill=MUTED)
        y += 90

    # right: HITL confirm card
    panel(d, [476, 76, w - 16, 360])
    d.text((496, 96), "HUMAN INPUT REQUIRED", font=_font(14), fill=(251, 191, 36))
    panel(d, [496, 124, w - 36, 320], fill=(26, 34, 64))
    d.text((516, 144), "Confirm send_email:", font=_font(16), fill=TEXT)
    d.text((516, 178), 'to:      thanvish@example.com', font=_font(14), fill=MUTED)
    d.text((516, 204), 'subject: Python Web Frameworks Report', font=_font(14), fill=MUTED)
    d.text((516, 230), 'preview: Here is the comparison you asked for…', font=_font(14), fill=MUTED)
    d.rounded_rectangle([516, 268, 626, 300], radius=8, fill=ACCENT)
    d.text((540, 276), "Approve", font=_font(14), fill=BG)
    d.rounded_rectangle([642, 268, 740, 300], radius=8, outline=BORDER, width=2)
    d.text((664, 276), "Reject", font=_font(14), fill=TEXT)

    panel(d, [476, 376, w - 16, h - 16])
    d.text((496, 396), "FINAL OUTPUT", font=_font(14), fill=MUTED)
    d.text((496, 430), "Waiting for confirmation before sending…", font=_font(15), fill=MUTED)

    img.save(path)


if __name__ == "__main__":
    shot_trace(OUT / "01-trace.png")
    shot_output(OUT / "02-output.png")
    shot_history(OUT / "03-history.png")
    print("wrote placeholders to", OUT)
