"""
dashboard_daily.py — daily snapshot of AetherMind RAG activity.

Run by a Hermes cron job (e.g. every day at 23:55). Reads today's
visitors / questions / waitlist from the local Postgres (rag_site) and
writes a dated Markdown + JSON snapshot into the project's dashboard_log/.

If Postgres (your laptop) is OFF, it simply writes a "no data" snapshot
and exits 0 — nothing crashes.
"""
import json
import os
from datetime import datetime

import psycopg2

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_DIR, "dashboard_log")
os.makedirs(LOG_DIR, exist_ok=True)

DSN = (
    "dbname=rag_site user=postgres password=Valtare@123 "
    "host=127.0.0.1 port=5432"
)


def collect():
    try:
        conn = psycopg2.connect(DSN)
    except Exception as e:
        return {"enabled": False, "error": str(e),
                "visits": 0, "questions": 0, "waitlist": 0,
                "recent": [], "waitlist_rows": []}
    cur = conn.cursor()
    try:
        def one(sql):
            cur.execute(sql)
            return cur.fetchone()[0]

        visits = one("SELECT COUNT(*) FROM visitor_logs "
                     "WHERE ts >= CURRENT_DATE")
        questions = one("SELECT COUNT(*) FROM visitor_logs "
                        "WHERE ts >= CURRENT_DATE AND event='question'")
        waitlist = one("SELECT COUNT(*) FROM waitlist")

        cur.execute(
            "SELECT ts, project, event, detail FROM visitor_logs "
            "WHERE ts >= CURRENT_DATE ORDER BY ts DESC")
        recent = [
            {"ts": str(r[0]), "project": r[1], "event": r[2],
             "detail": (r[3] or "")[:200]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "SELECT name, email, note, ts FROM waitlist ORDER BY ts DESC")
        wl = [
            {"name": r[0], "email": r[1], "note": (r[2] or "")[:200],
             "ts": str(r[3])}
            for r in cur.fetchall()
        ]
        return {"enabled": True, "visits": visits, "questions": questions,
                "waitlist": waitlist, "recent": recent, "waitlist_rows": wl}
    finally:
        cur.close()
        conn.close()


def render_md(s, day):
    lines = [f"# AetherMind Daily Dashboard — {day}", ""]
    status = "Postgres ON" if s.get("enabled") else "Postgres OFF (laptop off?)"
    lines.append(f"Status: {status}")
    lines.append(f"Events today: {s.get('visits',0)}")
    lines.append(f"Questions asked: {s.get('questions',0)}")
    lines.append(f"Waitlist total: {s.get('waitlist',0)}")
    lines.append("")
    lines.append("## Today's Activity")
    if s.get("recent"):
        for r in s["recent"]:
            lines.append(f"- `{r['ts'][:19]}` [{r['project']}/{r['event']}] {r['detail']}")
    else:
        lines.append("- no activity")
    lines.append("")
    lines.append("## Waitlist Signups")
    if s.get("waitlist_rows"):
        for w in s["waitlist_rows"]:
            lines.append(f"- {w['name'] or '—'} <{w['email']}> — {w['note']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main():
    day = datetime.now().strftime("%Y-%m-%d")
    s = collect()
    md = render_md(s, day)
    md_path = os.path.join(LOG_DIR, f"dashboard_{day}.md")
    json_path = os.path.join(LOG_DIR, f"dashboard_{day}.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    # stdout is delivered to the user by the cron job
    print(f"✅ Daily dashboard snapshot saved: {md_path}")
    print(f"   events={s.get('visits',0)} questions={s.get('questions',0)} "
          f"waitlist={s.get('waitlist',0)}")
    if not s.get("enabled"):
        print(f"   ⚠️ Postgres unavailable: {s.get('error')}")


if __name__ == "__main__":
    main()
