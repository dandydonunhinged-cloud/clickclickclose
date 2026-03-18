#!/usr/bin/env python3
"""
qualification_engine.py — Click Click Close Instant Qualification Engine
=========================================================================
No human in the loop. Instant decision from form input.

Returns in < 200ms:
  - Decision: QUALIFIED | CONDITIONAL | NOT_QUALIFIED
  - Top lender matches with program details
  - Rate range estimate
  - Close timeline estimate
  - Borrower-facing summary (no lender names)
  - Admin payload with full lender details + comp

Callable as:
  1. Python function: qualify(form_data) -> dict
  2. HTTP API:        POST /api/qualify  (returns JSON)
  3. CLI test:        python qualification_engine.py

Architecture:
  form_data → parse_deal() → route_deal() → qualify_decision()
  → client_payload + admin_payload → emit

Authors: Don Brown & Claude (Spock/Specter)
"""

import json
import os
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import the core routing engine
import sys
sys.path.insert(0, str(Path(__file__).parent))
from routing_engine import (
    Deal, LenderMatch, Lender,
    parse_deal, route_deal,
    client_report, admin_report,
    send_don_notification, send_borrower_confirmation,
    SUBMISSIONS_DIR
)


# ============================================================
#  QUALIFICATION DECISION LAYER
# ============================================================

DECISION_QUALIFIED    = "QUALIFIED"
DECISION_CONDITIONAL  = "CONDITIONAL"
DECISION_NOT_QUALIFIED = "NOT_QUALIFIED"

# Hard disqualifiers — instant NO
HARD_STOPS = [
    ("credit_score_below_580",  lambda d: d.credit_score > 0 and d.credit_score < 580,
     "Credit score below 580 — no eligible programs at this time."),
    ("loan_below_50k",          lambda d: 0 < d.loan_amount < 50000,
     "Loan amount below $50,000 — below minimum for all programs."),
    ("loan_above_500m",         lambda d: d.loan_amount > 500_000_000,
     "Loan amount exceeds $500M — contact us directly for jumbo structuring."),
    ("ltv_above_100",           lambda d: d.ltv > 100,
     "LTV exceeds 100% — not fundable in current structure."),
]

# Conditional flags — approval with conditions
CONDITIONAL_FLAGS = [
    ("credit_580_to_619",  lambda d: 580 <= d.credit_score < 620,
     "Credit 580-619: limited programs available, higher rate expected."),
    ("ltv_above_90",       lambda d: d.ltv > 90,
     "LTV above 90%: fewer options, may require additional documentation."),
    ("dscr_below_1",       lambda d: 0 < d.dscr < 1.0,
     "DSCR below 1.0: sub-1 DSCR programs exist but rates will be higher."),
    ("no_entity",          lambda d: d.entity_type in ("personal", "", None) and d.loan_type == "dscr",
     "DSCR loans strongly prefer LLC or Corp — entity formation recommended."),
    ("first_time_investor",lambda d: d.experience == "first" and d.loan_type in ("fix-flip", "construction"),
     "First-time investors require lender review for fix-flip/construction — approval likely with documentation."),
]


def qualify_decision(deal: Deal, matches: List[LenderMatch]) -> dict:
    """
    Core decision function. Returns qualification payload.
    No external calls. Pure logic. < 5ms execution.
    """
    hard_stops_triggered = []
    conditional_flags_triggered = []

    # Check hard stops
    for stop_id, check, message in HARD_STOPS:
        if check(deal):
            hard_stops_triggered.append({"code": stop_id, "message": message})

    # Check conditionals (only if no hard stops)
    if not hard_stops_triggered:
        for flag_id, check, message in CONDITIONAL_FLAGS:
            if check(deal):
                conditional_flags_triggered.append({"code": flag_id, "message": message})

    # Determine decision
    if hard_stops_triggered:
        decision = DECISION_NOT_QUALIFIED
        decision_message = hard_stops_triggered[0]["message"]
        confidence = 0
    elif not matches:
        decision = DECISION_NOT_QUALIFIED
        decision_message = "No matching programs found for this deal profile."
        confidence = 0
    elif conditional_flags_triggered:
        decision = DECISION_CONDITIONAL
        decision_message = f"Conditional approval likely. {len(matches)} program(s) match. Review required."
        confidence = max(40, min(75, matches[0].fit_score))
    else:
        decision = DECISION_QUALIFIED
        decision_message = f"Qualified. {len(matches)} program(s) matched. Best rate: {matches[0].estimated_rate}."
        confidence = min(95, max(60, matches[0].fit_score))

    # Best program summary for borrower
    best_match = matches[0] if matches else None

    return {
        "decision": decision,
        "decision_message": decision_message,
        "confidence_pct": confidence,
        "programs_found": len(matches),
        "hard_stops": hard_stops_triggered,
        "conditional_flags": conditional_flags_triggered,
        "best_match": {
            "rate_range": best_match.estimated_rate if best_match else None,
            "close_estimate": best_match.estimated_close if best_match else None,
            "reasons": best_match.reasons if best_match else [],
        } if best_match else None,
        "all_matches_count": len(matches),
    }


# ============================================================
#  INSTANT QUAL (PARTIAL FORM — called as user types)
# ============================================================

def qualify_partial(partial_data: dict) -> dict:
    """
    Real-time qualification from partial form input.
    Called on every field change in the browser form.
    Returns a lightweight signal: can_qualify / cannot_qualify / needs_more_info
    """
    credit_raw = partial_data.get("creditScore", "")
    loan_type = partial_data.get("loanType", "")
    property_state = partial_data.get("propertyState", "")
    loan_amount_raw = partial_data.get("purchasePrice") or partial_data.get("bridgeLoanAmount") or "0"

    # Parse what we have
    credit = 700  # default
    credit_map = {
        "760+": 780, "740-759": 750, "720-739": 730, "700-719": 710,
        "680-699": 690, "660-679": 670, "640-659": 650, "620-639": 630,
        "below-620": 590,
    }
    if credit_raw in credit_map:
        credit = credit_map[credit_raw]

    loan_amount = float(re.sub(r"[^\d.]", "", str(loan_amount_raw)) or 0)

    signals = []
    status = "collecting"

    # Instant disqualifiers even on partial data
    if credit_raw and credit < 580:
        return {
            "status": "not_qualified",
            "message": "Credit below 580 — no eligible programs.",
            "signals": ["HARD STOP: credit below minimum"],
        }

    if loan_amount > 0 and loan_amount < 50000:
        return {
            "status": "not_qualified",
            "message": "Loan amount below $50,000 minimum.",
            "signals": ["HARD STOP: below minimum loan amount"],
        }

    # Positive signals
    if credit >= 720:
        signals.append("Credit score: excellent — best rates available")
    elif credit >= 680:
        signals.append("Credit score: good — standard programs available")
    elif credit >= 620:
        signals.append("Credit score: fair — programs available, rate premium expected")

    if loan_type:
        product_labels = {
            "dscr": "DSCR — qualify on rental income only, no W-2 needed",
            "fix-flip": "Fix & Flip — short-term, fast close available",
            "bridge": "Bridge — 12-24 month, interest-only",
            "bank-statement": "Bank Statement — no tax returns needed",
            "foreign-national": "Foreign National — US property, no US credit required",
        }
        if loan_type in product_labels:
            signals.append(f"Program: {product_labels[loan_type]}")

    # Has enough info for full qualification?
    has_credit = bool(credit_raw)
    has_loan_type = bool(loan_type)
    has_state = bool(property_state)
    has_amount = loan_amount > 0

    if has_credit and has_loan_type and has_state and has_amount:
        status = "ready_to_qualify"
    elif has_credit and has_loan_type:
        status = "partial"

    return {
        "status": status,
        "message": "Looking good — keep going." if status == "partial" else (
            "Ready to match." if status == "ready_to_qualify" else "Tell us more."
        ),
        "signals": signals,
    }


# ============================================================
#  FULL QUALIFICATION (complete form submission)
# ============================================================

def qualify(form_data: dict) -> dict:
    """
    Full qualification pipeline. Called on form submission.
    Returns complete client + admin payloads.
    Saves to submissions DB. Fires emails.
    No human in the loop.
    """
    ts = datetime.now().isoformat()
    req_id = f"CCC-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Parse and route
    deal = parse_deal(form_data)
    matches = route_deal(deal)

    # Make the decision
    qual = qualify_decision(deal, matches)

    # Build client payload (no lender names)
    client_payload = {
        "request_id": req_id,
        "timestamp": ts,
        "decision": qual["decision"],
        "decision_message": qual["decision_message"],
        "confidence_pct": qual["confidence_pct"],
        "programs_found": qual["programs_found"],
        "conditional_flags": [f["message"] for f in qual["conditional_flags"]],
        "rate_range": qual["best_match"]["rate_range"] if qual["best_match"] else None,
        "close_estimate": qual["best_match"]["close_estimate"] if qual["best_match"] else None,
        "next_steps": _build_next_steps(qual["decision"], deal),
        "disclaimer": (
            "This is not a loan approval or commitment to lend. "
            "Rate estimates reflect current market conditions. "
            "Actual terms depend on full documentation review and lender approval."
        ),
    }

    # Build admin payload (full lender details)
    admin_payload = {
        "request_id": req_id,
        "timestamp": ts,
        "decision": qual,
        "borrower": {
            "name": deal.full_name,
            "email": deal.email,
            "phone": deal.phone,
            "best_time": deal.best_time,
            "referral": deal.referral_source,
        },
        "deal_summary": {
            "type": deal.loan_type,
            "property_type": deal.property_type,
            "state": deal.property_state,
            "credit_score": deal.credit_score,
            "loan_amount": deal.loan_amount,
            "ltv_pct": round(deal.ltv, 1),
            "dscr": deal.dscr,
            "purchase_price": deal.purchase_price,
            "rental_income": deal.rental_income,
            "close_timeline": deal.close_timeline,
            "experience": deal.experience,
            "entity": deal.entity_type,
        },
        "lender_matches": [
            {
                "rank": i + 1,
                "lender_name": m.lender.name,
                "fit_score": m.fit_score,
                "rate_estimate": m.estimated_rate,
                "close_estimate": m.estimated_close,
                "comp_model": m.lender.comp_model,
                "comp_range": m.lender.comp_range,
                "est_comp_dollars": _estimate_comp_dollars(m.lender, deal.loan_amount),
                "signup_url": m.lender.signup_url,
                "reasons": m.reasons,
                "warnings": m.warnings,
                "notes": m.lender.notes,
            }
            for i, m in enumerate(matches)
        ],
        "action_items": _build_action_items(deal, matches),
    }

    # Save to submissions folder
    _save_submission(req_id, form_data, client_payload, admin_payload)

    # Fire emails (non-blocking — if email fails, qual still succeeds)
    try:
        send_don_notification(deal, matches)
        send_borrower_confirmation(deal)
    except Exception as e:
        print(f"[EMAIL WARNING] {e}")

    return {
        "client": client_payload,
        "admin": admin_payload,
    }


def _build_next_steps(decision: str, deal: Deal) -> list:
    if decision == DECISION_NOT_QUALIFIED:
        return [
            "Your current profile doesn't match available programs.",
            "Credit improvement or deal restructuring may open options.",
            "Call us — some scenarios have workarounds not visible in the form.",
            "click@clickclickclose.click | We respond same day.",
        ]
    elif decision == DECISION_CONDITIONAL:
        return [
            "Conditional match found — a quick review will confirm.",
            "We'll contact you within 15 minutes during business hours.",
            "Have your most recent bank statements or rental leases ready.",
            "No credit pull until you say go.",
        ]
    else:
        return [
            "You're matched — we're preparing your program options now.",
            "You'll hear from us within 15 minutes during business hours (M-F 8am-6pm CT).",
            "We'll present 2-3 options with exact rates, terms, and close timelines.",
            "No commitment. No credit pull. No BS.",
        ]


def _estimate_comp_dollars(lender: Lender, loan_amount: float) -> str:
    """Estimate broker comp in dollars from comp_range string and loan amount."""
    if not loan_amount:
        return "TBD"
    try:
        # Parse "0.5-2%" → take midpoint
        raw = lender.comp_range.replace("%", "").replace(" ", "")
        if "-" in raw:
            parts = raw.split("-")
            mid = (float(parts[0]) + float(parts[1])) / 2
        elif raw.replace(".", "").isdigit():
            mid = float(raw)
        else:
            return "See lender"
        est = loan_amount * (mid / 100)
        return f"~${est:,.0f}"
    except Exception:
        return "See lender"


def _build_action_items(deal: Deal, matches: List[LenderMatch]) -> list:
    items = []
    if deal.phone:
        items.append(f"CALL: {deal.full_name} at {deal.phone} ({deal.best_time or 'anytime'})")
    if deal.email:
        items.append(f"EMAIL: {deal.email}")
    if matches:
        top = matches[0]
        items.append(f"BEST LENDER: {top.lender.name} — {top.estimated_rate} — comp {top.lender.comp_range}")
        if deal.loan_amount:
            items.append(f"EST COMP: {_estimate_comp_dollars(top.lender, deal.loan_amount)}")
        items.append(f"SIGNUP: {top.lender.signup_url}")
    else:
        items.append("NO AUTO-MATCH — manual review required")
    return items


def _save_submission(req_id: str, form_data: dict, client: dict, admin: dict):
    """Save submission JSON to disk."""
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]", "_", form_data.get("fullName", "anon"))[:30]
    filepath = SUBMISSIONS_DIR / f"{req_id}_{slug}.json"
    payload = {
        "request_id": req_id,
        "submitted_at": datetime.now().isoformat(),
        "form_data": form_data,
        "client_result": client,
        "admin_result": admin,
    }
    filepath.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"[SAVED] {filepath}")


# ============================================================
#  HTTP API SERVER
# ============================================================

class QualHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server. Runs standalone on port 8765."""

    def log_message(self, format, *args):
        # Suppress default request logging (too noisy)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {args[0]} {args[1]}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return

        t0 = datetime.now()

        if self.path == "/api/qualify":
            result = qualify(data)
            status = 200
        elif self.path == "/api/qualify/partial":
            result = qualify_partial(data)
            status = 200
        else:
            result = {"error": f"Unknown endpoint: {self.path}"}
            status = 404

        elapsed = (datetime.now() - t0).total_seconds() * 1000
        if "admin" in result:
            result["admin"]["response_ms"] = round(elapsed, 1)

        response = json.dumps(result, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self._cors()
        self.end_headers()
        self.wfile.write(response)


def run_server(port: int = 8765):
    server = HTTPServer(("0.0.0.0", port), QualHandler)
    print(f"[QUAL ENGINE] Listening on http://0.0.0.0:{port}")
    print(f"  POST /api/qualify          — full qualification")
    print(f"  POST /api/qualify/partial  — real-time partial form signal")
    server.serve_forever()


# ============================================================
#  CLI TEST
# ============================================================

if __name__ == "__main__":
    import sys

    if "--server" in sys.argv:
        port = int(os.environ.get("QUAL_PORT", 8765))
        run_server(port)
        sys.exit(0)

    # Test scenarios
    test_cases = [
        {
            "label": "DSCR — Strong TX investor",
            "data": {
                "loanType": "dscr", "propertyType": "sfr", "propertyState": "TX",
                "purchasePrice": "$350,000", "rentalIncome": "$2,800",
                "downPayment": "25", "creditScore": "720-739",
                "experience": "2-5", "entityType": "llc", "closeTimeline": "30-days",
                "fullName": "Test Investor", "email": "test@ccc.com",
                "phone": "(214) 555-0001", "bestTimeToCall": "morning",
            }
        },
        {
            "label": "Fix & Flip — Marginal credit",
            "data": {
                "loanType": "fix-flip", "propertyType": "sfr", "propertyState": "FL",
                "flipPurchasePrice": "$180,000", "rehabBudget": "$45,000", "arv": "$310,000",
                "creditScore": "640-659", "experience": "first",
                "entityType": "llc", "closeTimeline": "asap",
                "fullName": "First Flipper", "email": "flip@test.com", "phone": "(813) 555-0002",
            }
        },
        {
            "label": "Foreign National — DSCR condo",
            "data": {
                "loanType": "foreign-national", "propertyType": "condo", "propertyState": "FL",
                "purchasePrice": "$450,000", "rentalIncome": "$3,200",
                "downPayment": "25", "creditScore": "720-739",
                "experience": "first", "entityType": "llc", "closeTimeline": "45-days",
                "fullName": "Intl Investor", "email": "intl@test.com", "phone": "+44 777 555 0003",
            }
        },
        {
            "label": "Hard stop — credit 540",
            "data": {
                "loanType": "dscr", "propertyType": "sfr", "propertyState": "CA",
                "purchasePrice": "$600,000", "rentalIncome": "$3,800",
                "downPayment": "20", "creditScore": "below-620",
                "fullName": "Low Credit", "email": "low@test.com", "phone": "(310) 555-0004",
            }
        },
    ]

    for tc in test_cases:
        print(f"\n{'='*70}")
        print(f"  TEST: {tc['label']}")
        print("="*70)

        result = qualify(tc["data"])
        c = result["client"]
        a = result["admin"]

        print(f"  DECISION:    {c['decision']}")
        print(f"  MESSAGE:     {c['decision_message']}")
        print(f"  CONFIDENCE:  {c['confidence_pct']}%")
        print(f"  PROGRAMS:    {c['programs_found']}")
        if c.get("rate_range"):
            print(f"  RATE RANGE:  {c['rate_range']}")
        if c.get("close_estimate"):
            print(f"  CLOSE:       {c['close_estimate']}")
        if c.get("conditional_flags"):
            print(f"  CONDITIONS:  {'; '.join(c['conditional_flags'])}")

        print(f"\n  TOP LENDERS (admin):")
        for lm in a["lender_matches"][:3]:
            print(f"    #{lm['rank']} {lm['lender_name']}")
            print(f"        Rate: {lm['rate_estimate']} | Comp: {lm['comp_range']} ({lm['est_comp_dollars']})")
            print(f"        Why:  {', '.join(lm['reasons'][:2])}")

        print(f"\n  ACTION ITEMS:")
        for item in a["action_items"]:
            print(f"    > {item}")
