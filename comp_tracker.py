#!/usr/bin/env python3
"""
comp_tracker.py — Click Click Close Automated Compensation Tracker
==================================================================
Every closed loan gets logged. Every dollar tracked.
No manual entry. No spreadsheets. No forgetting.

Tracks:
  - Loan closed in whose name (broker / mini-corr / correspondent)
  - Lender that funded
  - Comp model (YSP / borrower-paid / lender-paid referral)
  - Expected comp vs. received comp
  - Pipeline: submitted → approved → closed → paid
  - Running totals: MTD / YTD / all-time

Storage: SQLite at C:/DandyDon/investor_site/comp_data/comp.db
Reports: console, JSON, CSV

CLI:
  python comp_tracker.py log          — log a new closed loan
  python comp_tracker.py report       — current pipeline + paid
  python comp_tracker.py report --mtd — month-to-date
  python comp_tracker.py report --ytd — year-to-date
  python comp_tracker.py pending      — all loans awaiting comp

Authors: Don Brown & Claude (Spock/Specter)
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional


DB_DIR  = Path("C:/DandyDon/investor_site/comp_data")
DB_PATH = DB_DIR / "comp.db"

# Loan pipeline stages
STAGE_SUBMITTED  = "submitted"
STAGE_APPROVED   = "approved"
STAGE_CLEARED    = "cleared_to_close"
STAGE_CLOSED     = "closed"
STAGE_FUNDED     = "funded"
STAGE_COMP_SENT  = "comp_sent"       # lender sent comp check / wire
STAGE_COMP_RCVD  = "comp_received"   # money in account
STAGE_DENIED     = "denied"
STAGE_WITHDRAWN  = "withdrawn"


# ============================================================
#  DATABASE SETUP
# ============================================================

def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS loans (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      TEXT UNIQUE,          -- from qualification_engine (CCC-YYYYMMDDHHMMSS)
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,

        -- Borrower
        borrower_name   TEXT,
        borrower_email  TEXT,
        borrower_phone  TEXT,

        -- Deal
        loan_type       TEXT,                 -- dscr, fix-flip, bridge, cmbs, sba504, etc.
        property_type   TEXT,
        property_state  TEXT,
        property_zip    TEXT,
        loan_amount     REAL,
        purchase_price  REAL,
        ltv_pct         REAL,
        credit_score    INTEGER,

        -- Lender
        lender_name     TEXT,
        lender_id       TEXT,                 -- key from LENDER_ROUTING_MATRIX.json
        close_model     TEXT,                 -- 'broker' | 'mini_corr' | 'correspondent'
        mini_corr_lender TEXT,               -- if mini-corr, which investor purchased

        -- Pipeline
        stage           TEXT DEFAULT 'submitted',
        submitted_date  TEXT,
        approved_date   TEXT,
        ctc_date        TEXT,                 -- clear to close
        close_date      TEXT,
        funded_date     TEXT,
        comp_expected_date TEXT,

        -- Compensation
        comp_model      TEXT,                 -- 'ysp' | 'borrower_paid' | 'lender_referral' | 'mini_corr_spread'
        comp_pct        REAL,                 -- percentage (e.g. 1.5 = 1.5%)
        comp_expected   REAL,                 -- dollar amount expected
        comp_received   REAL,                 -- dollar amount actually received
        comp_received_date TEXT,
        comp_notes      TEXT,

        -- Mini-corr specific
        note_rate       REAL,                 -- rate closed at
        buy_rate        REAL,                 -- rate investor pays (SRP income)
        srp_income      REAL,                 -- service release premium

        -- Meta
        notes           TEXT,
        referral_source TEXT
    );

    CREATE TABLE IF NOT EXISTS pipeline_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id     INTEGER REFERENCES loans(id),
        event_at    TEXT NOT NULL,
        stage_from  TEXT,
        stage_to    TEXT,
        notes       TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_loans_stage       ON loans(stage);
    CREATE INDEX IF NOT EXISTS idx_loans_close_date  ON loans(close_date);
    CREATE INDEX IF NOT EXISTS idx_loans_lender      ON loans(lender_name);
    CREATE INDEX IF NOT EXISTS idx_events_loan       ON pipeline_events(loan_id);
    """)
    conn.commit()


# ============================================================
#  LOG A LOAN
# ============================================================

def log_loan(
    borrower_name: str,
    loan_type: str,
    property_state: str,
    loan_amount: float,
    lender_name: str,
    comp_model: str,
    comp_pct: float,
    *,
    request_id: str = None,
    borrower_email: str = "",
    borrower_phone: str = "",
    property_type: str = "",
    property_zip: str = "",
    purchase_price: float = 0,
    ltv_pct: float = 0,
    credit_score: int = 0,
    lender_id: str = "",
    close_model: str = "broker",
    mini_corr_lender: str = "",
    stage: str = STAGE_SUBMITTED,
    submitted_date: str = None,
    referral_source: str = "",
    notes: str = "",
    note_rate: float = 0,
    buy_rate: float = 0,
    loan_type_specific: str = None,
) -> int:
    """
    Log a new loan into the pipeline.
    Returns the loan ID.
    """
    now = datetime.now().isoformat()
    req_id = request_id or f"CCC-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    # Calculate expected comp
    comp_expected = round(loan_amount * (comp_pct / 100), 2) if loan_amount and comp_pct else 0

    # Mini-corr SRP calculation
    srp_income = 0
    if close_model == "mini_corr" and note_rate and buy_rate:
        # SRP = (note_rate - buy_rate) * loan_amount * 100 / 10000 (rough)
        srp_income = round((note_rate - buy_rate) / 100 * loan_amount, 2)
        comp_expected = max(comp_expected, srp_income)

    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO loans (
                request_id, created_at, updated_at,
                borrower_name, borrower_email, borrower_phone,
                loan_type, property_type, property_state, property_zip,
                loan_amount, purchase_price, ltv_pct, credit_score,
                lender_name, lender_id, close_model, mini_corr_lender,
                stage, submitted_date,
                comp_model, comp_pct, comp_expected,
                note_rate, buy_rate, srp_income,
                referral_source, notes
            ) VALUES (
                ?,?,?,  ?,?,?,  ?,?,?,?,  ?,?,?,?,  ?,?,?,?,  ?,?,  ?,?,?,  ?,?,?,  ?,?
            )
        """, (
            req_id, now, now,
            borrower_name, borrower_email, borrower_phone,
            loan_type, property_type, property_state, property_zip,
            loan_amount, purchase_price, ltv_pct, credit_score,
            lender_name, lender_id, close_model, mini_corr_lender or "",
            stage, submitted_date or now[:10],
            comp_model, comp_pct, comp_expected,
            note_rate, buy_rate, srp_income,
            referral_source, notes,
        ))
        loan_id = cur.lastrowid
        conn.commit()

        # Log initial pipeline event
        _log_event(conn, loan_id, None, stage, f"Loan submitted — ${loan_amount:,.0f} via {lender_name}")
        print(f"[COMP] Logged loan #{loan_id}: {borrower_name} | ${loan_amount:,.0f} | {lender_name} | est comp ${comp_expected:,.0f}")
        return loan_id
    finally:
        conn.close()


# ============================================================
#  ADVANCE PIPELINE STAGE
# ============================================================

def advance_stage(
    loan_id: int,
    new_stage: str,
    *,
    notes: str = "",
    comp_received: float = None,
    comp_received_date: str = None,
) -> bool:
    """
    Move a loan to the next pipeline stage.
    Records the event. Updates timestamps.
    """
    conn = get_db()
    try:
        row = conn.execute("SELECT stage, borrower_name, loan_amount, comp_expected FROM loans WHERE id=?", (loan_id,)).fetchone()
        if not row:
            print(f"[COMP] Loan #{loan_id} not found")
            return False

        old_stage = row["stage"]
        now = datetime.now().isoformat()
        today = now[:10]

        # Build update fields
        updates = {"stage": new_stage, "updated_at": now}
        if new_stage == STAGE_APPROVED:    updates["approved_date"] = today
        if new_stage == STAGE_CLEARED:     updates["ctc_date"] = today
        if new_stage == STAGE_CLOSED:      updates["close_date"] = today
        if new_stage == STAGE_FUNDED:      updates["funded_date"] = today
        if new_stage in (STAGE_COMP_SENT, STAGE_COMP_RCVD):
            updates["comp_expected_date"] = today
        if new_stage == STAGE_COMP_RCVD and comp_received is not None:
            updates["comp_received"] = comp_received
            updates["comp_received_date"] = comp_received_date or today

        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE loans SET {set_clause} WHERE id=?", (*updates.values(), loan_id))
        conn.commit()

        _log_event(conn, loan_id, old_stage, new_stage, notes)

        if new_stage == STAGE_COMP_RCVD and comp_received:
            expected = row["comp_expected"] or 0
            variance = comp_received - expected
            print(f"[COMP] PAID — Loan #{loan_id} ({row['borrower_name']})")
            print(f"       Received: ${comp_received:,.2f} | Expected: ${expected:,.2f} | Variance: ${variance:+,.2f}")
        else:
            print(f"[COMP] Loan #{loan_id} advanced: {old_stage} -> {new_stage}")
        return True
    finally:
        conn.close()


def _log_event(conn, loan_id: int, stage_from: Optional[str], stage_to: str, notes: str = ""):
    conn.execute("""
        INSERT INTO pipeline_events (loan_id, event_at, stage_from, stage_to, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (loan_id, datetime.now().isoformat(), stage_from, stage_to, notes))
    conn.commit()


# ============================================================
#  REPORTS
# ============================================================

def report_pipeline(filter_stage: str = None, mtd: bool = False, ytd: bool = False) -> dict:
    """Generate pipeline + comp report."""
    conn = get_db()
    try:
        # Build query filters
        where_clauses = []
        params = []

        if filter_stage:
            where_clauses.append("stage = ?")
            params.append(filter_stage)

        today = date.today()
        if mtd:
            where_clauses.append("substr(created_at,1,7) = ?")
            params.append(today.strftime("%Y-%m"))
        elif ytd:
            where_clauses.append("substr(created_at,1,4) = ?")
            params.append(str(today.year))

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        loans = conn.execute(f"""
            SELECT * FROM loans {where}
            ORDER BY created_at DESC
        """, params).fetchall()

        # Aggregates
        total_loans = len(loans)
        total_volume = sum(r["loan_amount"] or 0 for r in loans)
        total_comp_expected = sum(r["comp_expected"] or 0 for r in loans)
        total_comp_received = sum(r["comp_received"] or 0 for r in loans if r["comp_received"])

        active_loans = [r for r in loans if r["stage"] not in (STAGE_COMP_RCVD, STAGE_DENIED, STAGE_WITHDRAWN)]
        pipeline_value = sum(r["loan_amount"] or 0 for r in active_loans)
        pipeline_comp   = sum(r["comp_expected"] or 0 for r in active_loans)

        # By stage breakdown
        by_stage = {}
        for r in loans:
            s = r["stage"]
            if s not in by_stage:
                by_stage[s] = {"count": 0, "volume": 0, "comp_expected": 0}
            by_stage[s]["count"] += 1
            by_stage[s]["volume"] += r["loan_amount"] or 0
            by_stage[s]["comp_expected"] += r["comp_expected"] or 0

        # By lender
        by_lender = {}
        for r in loans:
            lender = r["lender_name"] or "Unknown"
            if lender not in by_lender:
                by_lender[lender] = {"count": 0, "volume": 0, "comp_expected": 0, "comp_received": 0}
            by_lender[lender]["count"] += 1
            by_lender[lender]["volume"] += r["loan_amount"] or 0
            by_lender[lender]["comp_expected"] += r["comp_expected"] or 0
            by_lender[lender]["comp_received"] += r["comp_received"] or 0

        result = {
            "generated_at": datetime.now().isoformat(),
            "period": "mtd" if mtd else ("ytd" if ytd else "all_time"),
            "summary": {
                "total_loans": total_loans,
                "total_volume": total_volume,
                "total_comp_expected": total_comp_expected,
                "total_comp_received": total_comp_received,
                "comp_outstanding": total_comp_expected - total_comp_received,
                "pipeline_loans": len(active_loans),
                "pipeline_volume": pipeline_value,
                "pipeline_comp_expected": pipeline_comp,
            },
            "by_stage": by_stage,
            "by_lender": by_lender,
            "loans": [dict(r) for r in loans],
        }
        return result
    finally:
        conn.close()


def print_report(data: dict):
    """Human-readable console report."""
    s = data["summary"]
    period = data["period"].upper()
    print(f"\n{'='*65}")
    print(f"  CLICK CLICK CLOSE — COMP REPORT ({period})")
    print(f"  {data['generated_at'][:16]}")
    print("="*65)
    print(f"  TOTAL LOANS:        {s['total_loans']:>6}")
    print(f"  TOTAL VOLUME:       ${s['total_volume']:>14,.0f}")
    print(f"  COMP EXPECTED:      ${s['total_comp_expected']:>14,.2f}")
    print(f"  COMP RECEIVED:      ${s['total_comp_received']:>14,.2f}")
    print(f"  COMP OUTSTANDING:   ${s['comp_outstanding']:>14,.2f}")
    print(f"\n  PIPELINE (active):")
    print(f"  Loans:              {s['pipeline_loans']:>6}")
    print(f"  Volume:             ${s['pipeline_volume']:>14,.0f}")
    print(f"  Expected comp:      ${s['pipeline_comp_expected']:>14,.2f}")

    if data["by_stage"]:
        print(f"\n  BY STAGE:")
        for stage, stats in sorted(data["by_stage"].items()):
            print(f"    {stage:<22} {stats['count']:>3} loans   ${stats['volume']:>12,.0f}   ~${stats['comp_expected']:>10,.0f} comp")

    if data["by_lender"]:
        print(f"\n  BY LENDER:")
        for lender, stats in sorted(data["by_lender"].items(), key=lambda x: -x[1]["volume"]):
            print(f"    {lender[:28]:<28} {stats['count']:>3} loans   ${stats['volume']:>12,.0f}")

    if data["loans"]:
        print(f"\n  RECENT LOANS (last 10):")
        for r in data["loans"][:10]:
            comp_rcvd = f"PAID ${r['comp_received']:,.0f}" if r.get("comp_received") else f"exp ${r.get('comp_expected',0):,.0f}"
            print(f"    [{r['stage'][:12]:<12}] {(r['borrower_name'] or 'Unknown')[:20]:<20} ${r.get('loan_amount',0):>10,.0f}  {r['lender_name'][:20]:<20} {comp_rcvd}")

    print("="*65)


def export_csv(output_path: str = None) -> str:
    """Export all loans to CSV."""
    import csv
    from io import StringIO

    conn = get_db()
    loans = conn.execute("SELECT * FROM loans ORDER BY created_at DESC").fetchall()
    conn.close()

    if not loans:
        print("[COMP] No loans to export.")
        return ""

    output_path = output_path or str(DB_DIR / f"comp_export_{datetime.now().strftime('%Y%m%d')}.csv")
    fields = loans[0].keys()

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([dict(r) for r in loans])

    print(f"[COMP] Exported {len(loans)} loans → {output_path}")
    return output_path


# ============================================================
#  AUTO-LOG FROM QUALIFICATION ENGINE SUBMISSION
# ============================================================

def log_from_submission(submission_path: str) -> Optional[int]:
    """
    Auto-log a loan from a qualification_engine submission JSON file.
    Called automatically when a submission file is created.
    """
    try:
        data = json.loads(Path(submission_path).read_text(encoding="utf-8"))
        admin = data.get("admin_result", {})
        borrower = admin.get("borrower", {})
        deal = admin.get("deal_summary", {})
        matches = admin.get("lender_matches", [])

        if not matches:
            return None

        top = matches[0]

        return log_loan(
            borrower_name=borrower.get("name", "Unknown"),
            loan_type=deal.get("type", ""),
            property_state=deal.get("state", ""),
            loan_amount=deal.get("loan_amount", 0),
            lender_name=top.get("lender_name", ""),
            comp_model=top.get("comp_model", "YSP"),
            comp_pct=_parse_comp_pct(top.get("comp_range", "1%")),
            request_id=data.get("request_id"),
            borrower_email=borrower.get("email", ""),
            borrower_phone=borrower.get("phone", ""),
            property_type=deal.get("property_type", ""),
            loan_type_specific=deal.get("type"),
            purchase_price=deal.get("purchase_price", 0),
            ltv_pct=deal.get("ltv_pct", 0),
            credit_score=deal.get("credit_score", 0),
            lender_id=top.get("lender_id", ""),
            referral_source=borrower.get("referral", ""),
            stage=STAGE_SUBMITTED,
        )
    except Exception as e:
        print(f"[COMP] log_from_submission error: {e}")
        return None


def _parse_comp_pct(comp_range: str) -> float:
    """Parse '1-2%' → 1.5 (midpoint)."""
    try:
        raw = comp_range.replace("%", "").replace(" ", "")
        if "-" in raw:
            parts = raw.split("-")
            return round((float(parts[0]) + float(parts[1])) / 2, 3)
        return float(raw)
    except Exception:
        return 1.0


# ============================================================
#  MINI-CORR TRACKING
# ============================================================

def log_mini_corr_loan(
    borrower_name: str,
    loan_type: str,
    property_state: str,
    loan_amount: float,
    funding_lender: str,
    note_rate: float,
    buy_rate: float,
    *,
    borrower_email: str = "",
    borrower_phone: str = "",
    credit_score: int = 0,
    notes: str = "",
) -> int:
    """
    Log a mini-correspondent loan where Click Click Close closes in its own name
    and sells to the investor/lender at the buy rate.
    SRP (service release premium) = (note_rate - buy_rate) × loan_amount / 100
    """
    srp = round((note_rate - buy_rate) / 100 * loan_amount, 2)
    print(f"[MINI-CORR] {borrower_name} | ${loan_amount:,.0f} | rate {note_rate}% | buy {buy_rate}% | SRP ${srp:,.0f}")

    return log_loan(
        borrower_name=borrower_name,
        loan_type=loan_type,
        property_state=property_state,
        loan_amount=loan_amount,
        lender_name=funding_lender,
        comp_model="mini_corr_spread",
        comp_pct=round((note_rate - buy_rate), 4),
        borrower_email=borrower_email,
        borrower_phone=borrower_phone,
        credit_score=credit_score,
        close_model="mini_corr",
        mini_corr_lender=funding_lender,
        note_rate=note_rate,
        buy_rate=buy_rate,
        notes=notes or f"Mini-corr: SRP = ${srp:,.0f}",
    )


# ============================================================
#  CLI
# ============================================================

def _cmd_report(args):
    mtd = "--mtd" in args
    ytd = "--ytd" in args
    data = report_pipeline(mtd=mtd, ytd=ytd)
    print_report(data)
    if "--json" in args:
        print(json.dumps(data, indent=2, default=str))
    if "--csv" in args:
        export_csv()


def _cmd_pending(args):
    conn = get_db()
    pending = conn.execute("""
        SELECT id, borrower_name, loan_amount, lender_name, comp_expected, stage, close_date
        FROM loans
        WHERE stage NOT IN (?, ?, ?)
        ORDER BY created_at DESC
    """, (STAGE_COMP_RCVD, STAGE_DENIED, STAGE_WITHDRAWN)).fetchall()
    conn.close()

    print(f"\n{'='*65}")
    print(f"  PENDING COMP — {len(pending)} loans")
    print("="*65)
    total_pending = 0
    for r in pending:
        print(f"  #{r['id']} [{r['stage'][:12]:<12}] {(r['borrower_name'] or 'Unknown')[:22]:<22} "
              f"${r.get('loan_amount',0):>10,.0f}  {(r['lender_name'] or '')[:20]:<20}  "
              f"exp ${r.get('comp_expected',0):>8,.0f}")
        total_pending += r.get("comp_expected") or 0
    print(f"\n  TOTAL PENDING: ${total_pending:,.2f}")
    print("="*65)


def _cmd_advance(args):
    """advance <loan_id> <new_stage> [--comp=AMOUNT]"""
    if len(args) < 2:
        print("Usage: python comp_tracker.py advance <loan_id> <stage>")
        return
    loan_id = int(args[0])
    new_stage = args[1]
    comp = None
    for a in args:
        if a.startswith("--comp="):
            comp = float(a.split("=")[1].replace(",", "").replace("$", ""))
    advance_stage(loan_id, new_stage, comp_received=comp)


def _cmd_log(args):
    """Interactive: log a new loan from CLI."""
    print("\n  LOG NEW LOAN — Click Click Close Comp Tracker")
    print("  (Press Enter to skip optional fields)\n")
    name = input("  Borrower name: ").strip()
    loan_type = input("  Loan type (dscr/fix-flip/bridge/cmbs/sba504/etc): ").strip()
    state = input("  Property state (2-letter): ").strip().upper()
    amt = float(input("  Loan amount ($): ").replace(",","").replace("$","").strip() or "0")
    lender = input("  Lender name: ").strip()
    comp_model = input("  Comp model (YSP/lender_referral/borrower_paid/mini_corr_spread): ").strip() or "YSP"
    comp_pct = float(input("  Comp percentage (e.g. 1.5): ").strip() or "1")
    close_model = input("  Close model (broker/mini_corr/correspondent) [broker]: ").strip() or "broker"

    loan_id = log_loan(
        borrower_name=name,
        loan_type=loan_type,
        property_state=state,
        loan_amount=amt,
        lender_name=lender,
        comp_model=comp_model,
        comp_pct=comp_pct,
        close_model=close_model,
    )
    print(f"\n  [OK] Logged loan #{loan_id}. Run 'python comp_tracker.py report' to see pipeline.\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "report"
    rest = args[1:]

    if cmd == "report":
        _cmd_report(rest)
    elif cmd == "pending":
        _cmd_pending(rest)
    elif cmd == "advance":
        _cmd_advance(rest)
    elif cmd == "log":
        _cmd_log(rest)
    elif cmd == "export":
        export_csv()
    elif cmd == "demo":
        # Seed some demo data
        print("[DEMO] Seeding comp tracker with sample loans...")
        id1 = log_loan("Maria Hernandez", "dscr", "TX", 285000, "RCN Capital",
                        "YSP", 1.5, borrower_email="maria@email.com",
                        credit_score=720, close_model="broker")
        advance_stage(id1, STAGE_APPROVED, notes="Clean file, fast track")
        advance_stage(id1, STAGE_CLEARED, notes="CTC issued")
        advance_stage(id1, STAGE_CLOSED, notes="Closed 2026-03-15")
        advance_stage(id1, STAGE_FUNDED)
        advance_stage(id1, STAGE_COMP_RCVD, comp_received=4140, notes="Wire received")

        id2 = log_loan("James Lee", "fix-flip", "FL", 210000, "Lima One Capital",
                        "lender_referral", 1.0, credit_score=680, close_model="broker")
        advance_stage(id2, STAGE_APPROVED)

        id3 = log_loan("Andrés Flores", "dscr", "AZ", 420000, "Angel Oak",
                        "YSP", 2.0, credit_score=740, close_model="broker")

        id4 = log_mini_corr_loan("Stephanie Kim", "dscr", "CA", 650000,
                                  "Visio Lending", note_rate=7.5, buy_rate=7.0,
                                  credit_score=760)
        advance_stage(id4, STAGE_APPROVED)
        advance_stage(id4, STAGE_CLEARED)
        advance_stage(id4, STAGE_CLOSED)
        advance_stage(id4, STAGE_FUNDED)

        id5 = log_loan("Robert Chen", "bank-statement", "CA", 890000, "Defy Mortgage",
                        "YSP", 1.75, credit_score=700, close_model="broker")
        advance_stage(id5, STAGE_APPROVED, notes="30 days bank statements provided")

        data = report_pipeline()
        print_report(data)
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: report [--mtd|--ytd] [--csv] [--json] | pending | advance <id> <stage> [--comp=AMOUNT] | log | export | demo")
