from __future__ import annotations

import csv
import html
import io
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "reviewreply.db"

POSITIVE_PHRASES = [
    "Thank you for taking the time to share this.",
    "We truly appreciate your support.",
    "Your feedback means a lot to our team.",
]
NEGATIVE_PHRASES = [
    "Thank you for sharing this honest feedback.",
    "We are sorry your experience did not meet expectations.",
    "We take your comments seriously and appreciate you speaking up.",
]
ACTION_PHRASES = [
    "Please reach out directly so we can make this right.",
    "We would love a chance to improve your next experience.",
    "Our team is already reviewing this internally.",
]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                business_name TEXT NOT NULL,
                tone TEXT NOT NULL,
                rating INTEGER NOT NULL,
                review_text TEXT NOT NULL,
                reply_1 TEXT NOT NULL,
                reply_2 TEXT NOT NULL,
                reply_3 TEXT NOT NULL
            )"""
        )
        conn.commit()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def keyword_hint(review: str) -> str:
    review_lower = review.lower()
    hints = {
        "wait": "speed of service",
        "late": "timeliness",
        "rude": "staff friendliness",
        "price": "value for money",
        "clean": "cleanliness",
        "quality": "product quality",
        "friendly": "customer care",
        "helpful": "support experience",
    }
    for token, hint in hints.items():
        if token in review_lower:
            return hint
    return "overall experience"


def tone_prefix(tone: str) -> str:
    return {
        "professional": "Hello",
        "warm": "Hi there",
        "playful": "Hey",
        "premium": "Greetings",
    }.get(tone, "Hello")


def generate_reply_variants(business_name: str, review_text: str, rating: int, tone: str) -> list[str]:
    prefix = tone_prefix(tone)
    focus = keyword_hint(review_text)
    if rating >= 4:
        acks = POSITIVE_PHRASES
        enders = [
            "We look forward to serving you again soon.",
            "Thanks again for supporting our team.",
            "We cannot wait to welcome you back.",
        ]
    else:
        acks = NEGATIVE_PHRASES
        enders = ACTION_PHRASES

    return [
        clean_text(f"{prefix}, thank you for your review of {business_name}. {acks[0]} We are glad you noticed our {focus}. {enders[0]}"),
        clean_text(f"{prefix}, we appreciate your feedback about {business_name}. {acks[1]} Your note about {focus} helps us keep improving. {enders[1]}"),
        clean_text(f"{prefix}, thank you for choosing {business_name}. {acks[2]} We value every comment we receive, especially around {focus}. {enders[2]}"),
    ]


def html_page(body: str) -> bytes:
    shell = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>ReviewReply Engine</title><style>
body{{font-family:Arial,sans-serif;max-width:920px;margin:1.5rem auto;padding:0 1rem;background:#f4f7fb;}}
nav a{{margin-right:1rem;}} .card{{background:#fff;padding:1rem;border-radius:10px;margin:1rem 0;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
input,select,textarea{{width:100%;padding:.5rem;margin:.3rem 0 .8rem;border:1px solid #ccd5e3;border-radius:6px;}} button{{padding:.6rem 1rem;background:#2457d6;color:#fff;border:0;border-radius:8px;}}
</style></head><body>
<h1>ReviewReply Engine</h1><nav><a href='/'>Generator</a><a href='/dashboard'>Dashboard</a><a href='/export.csv'>Export CSV</a></nav>{body}</body></html>"""
    return shell.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, content: str, code: int = 200) -> None:
        payload = html_page(content)
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(self.render_form())
            return
        if path == "/dashboard":
            with closing(get_db()) as conn:
                rows = conn.execute("SELECT * FROM replies ORDER BY datetime(created_at) DESC LIMIT 50").fetchall()
            rendered_rows = "".join(
                f"<tr><td>{html.escape(r['created_at'])}</td><td>{html.escape(r['business_name'])}</td><td>{r['rating']}</td><td>{html.escape(r['review_text'][:120])}</td></tr>"
                for r in rows
            )
            self._send_html(f"<div class='card'><h2>Recent generated replies</h2><table><tr><th>When</th><th>Business</th><th>Rating</th><th>Review</th></tr>{rendered_rows}</table></div>")
            return
        if path == "/export.csv":
            with closing(get_db()) as conn:
                rows = conn.execute("SELECT * FROM replies ORDER BY id DESC").fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "created_at", "business_name", "tone", "rating", "review_text", "reply_1", "reply_2", "reply_3"])
            for row in rows:
                writer.writerow([row[k] for k in row.keys()])
            data = output.getvalue().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=reviewreply-export.csv")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_html("<div class='card'><h2>Not found</h2></div>", 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/":
            self._send_html("<div class='card'><h2>Not found</h2></div>", 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        business_name = clean_text(form.get("business_name", [""])[0])
        review_text = clean_text(form.get("review_text", [""])[0])
        tone = form.get("tone", ["professional"])[0]
        rating = int(form.get("rating", ["5"])[0])

        if not business_name or not review_text:
            self._send_html(self.render_form("Business name and review text are required."), 400)
            return

        replies = generate_reply_variants(business_name, review_text, rating, tone)

        with closing(get_db()) as conn:
            conn.execute(
                """INSERT INTO replies (created_at,business_name,tone,rating,review_text,reply_1,reply_2,reply_3)
                VALUES (?,?,?,?,?,?,?,?)""",
                (datetime.utcnow().isoformat(timespec="seconds"), business_name, tone, rating, review_text, replies[0], replies[1], replies[2]),
            )
            conn.commit()

        items = "".join(f"<li>{html.escape(r)}</li>" for r in replies)
        self._send_html(self.render_form() + f"<div class='card'><h3>Ready-to-use responses</h3><ol>{items}</ol></div>")

    def render_form(self, error: str = "") -> str:
        error_html = f"<p style='color:#900'>{html.escape(error)}</p>" if error else ""
        return f"""
        <div class='card'>
        <h2>Generate review responses in seconds</h2>
        <p>Sell this as a done-for-you review response service at $49/month. 21 clients = $1,029/month.</p>
        {error_html}
        <form method='post' action='/'>
          <label>Business name</label><input name='business_name' required>
          <label>Review rating</label><select name='rating'><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select>
          <label>Tone</label><select name='tone'><option value='professional'>Professional</option><option value='warm'>Warm</option><option value='premium'>Premium</option><option value='playful'>Playful</option></select>
          <label>Customer review text</label><textarea name='review_text' rows='6' required></textarea>
          <button type='submit'>Generate 3 reply options</button>
        </form></div>
        """


def run() -> None:
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("ReviewReply Engine running at http://localhost:8000")
    server.serve_forever()


if __name__ == "__main__":
    run()
