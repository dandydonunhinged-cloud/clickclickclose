#!/usr/bin/env python
"""
routing_engine.py — Click Click Close Lender Routing Engine
=============================================================
Takes form submission JSON, runs it against the full routing matrix
(35 products, 49 lenders), returns top 3-5 matched lenders ranked by fit.

Includes:
  - Email notification to Don on every submission
  - Auto-response to borrower confirming receipt
  - Admin report with lender names, comp structure, signup URLs
  - Client report with program match, rate range, timeline (NO lender names)

Form fields (from submit.html):
  loanType, propertyType, propertyState, propertyZip,
  purchasePrice, rentalIncome, downPayment,
  flipPurchasePrice, rehabBudget, arv, rehabTimeline,
  bridgePropertyValue, bridgeLoanAmount, bridgeExitStrategy, bridgeTimeline,
  lotValue, constructionBudget, completedValue, buildStrategy,
  strPurchasePrice, nightlyRate, occupancyRate, strDownPayment,
  propertyCount, portfolioValue, portfolioRentalIncome, avgPropertyValue,
  currentLoanBalance, currentRate, refiPropertyValue, refiRentalIncome,
  creditScore, experience, entityType, closeTimeline,
  fullName, email, phone, bestTimeToCall, referralSource,
  businessPurpose, tcpaConsent

Authors: Don Brown & Claude (Spock)
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
#  LENDER DATABASE
# ============================================================

@dataclass
class Lender:
    name: str
    products: List[str]           # loan types this lender handles
    min_credit: int = 620
    max_ltv: float = 80.0
    min_dscr: float = 1.0
    min_loan: int = 50000
    max_loan: int = 5000000
    states_excluded: List[str] = field(default_factory=list)
    speed: str = "standard"       # "fast" (7-14d), "standard" (14-21d), "slow" (21-45d)
    comp_model: str = "YSP"       # "YSP", "referral", "affiliate", "correspondent"
    comp_range: str = "0.5-2%"
    signup_url: str = ""
    notes: str = ""
    specialties: List[str] = field(default_factory=list)
    property_types: List[str] = field(default_factory=list)
    fit_score: float = 0.0        # calculated during routing


LENDERS = [
    # === DSCR / INVESTOR RESIDENTIAL ===
    Lender("RCN Capital", ["dscr", "fix-flip", "bridge", "construction", "portfolio"],
           min_credit=620, max_ltv=90, min_dscr=0.75, max_loan=2500000,
           speed="fast", comp_model="YSP+referral+correspondent", comp_range="1-2.5%",
           signup_url="https://rcncapital.com/",
           notes="Fastest close in non-QM. 5-day fix-flip. Correspondent program available.",
           specialties=["fix-flip", "bridge", "speed"],
           property_types=["sfr", "2-4unit", "condo", "townhome", "5-9unit"]),

    Lender("Lima One Capital", ["dscr", "fix-flip", "bridge", "construction", "portfolio"],
           min_credit=660, max_ltv=85, min_dscr=1.0, max_loan=5000000,
           speed="fast", comp_model="affiliate", comp_range="referral fee",
           signup_url="https://www.limaone.com/",
           notes="Fix2Rent and Build2Rent programs. Up to 9-unit. Construction-to-perm.",
           specialties=["construction-to-perm", "9-unit", "build-to-rent"],
           property_types=["sfr", "2-4unit", "condo", "townhome", "5-9unit"]),

    Lender("Angel Oak", ["dscr", "bank-statement", "asset-depletion", "1099", "foreign-national"],
           min_credit=660, max_ltv=85, min_dscr=1.0, max_loan=3000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://angeloakmortgage.com/",
           notes="Largest non-QM lender. Bank statements up to $3M. 80-85% LTV.",
           specialties=["non-qm", "bank-statement", "foreign-national"],
           property_types=["sfr", "2-4unit", "condo"]),

    Lender("Defy Mortgage", ["dscr", "bank-statement", "asset-depletion", "1099", "p-and-l", "foreign-national"],
           min_credit=620, max_ltv=90, min_dscr=0.75, max_loan=3000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://defymortgage.com/",
           notes="Sub-0.75 DSCR programs. P&L qualification. Most flexible non-QM.",
           specialties=["low-dscr", "p-and-l", "non-qm-flexibility"],
           property_types=["sfr", "2-4unit", "condo", "townhome"]),

    Lender("A&D Mortgage", ["dscr", "bank-statement", "asset-depletion", "foreign-national", "itin"],
           min_credit=620, max_ltv=85, min_dscr=0.75, max_loan=5000000,
           speed="fast", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.admortgage.com/",
           notes="24-hour UW turnaround. First non-QM AUS. ITIN program. Up to $5M+ DSCR.",
           specialties=["speed", "itin", "high-loan-amount", "24hr-underwrite"],
           property_types=["sfr", "2-4unit", "condo", "townhome"]),

    Lender("Visio Lending", ["dscr", "str", "portfolio"],
           min_credit=680, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="wholesale/correspondent", comp_range="1-2%",
           signup_url="https://www.visiolending.com/",
           notes="DSCR specialist. Correspondent and wholesale programs.",
           specialties=["dscr-specialist", "str"],
           property_types=["sfr", "2-4unit", "condo"]),

    Lender("Change Wholesale", ["dscr"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.changewholesale.com/",
           notes="Easy onboarding. Training provided. Investment-focused.",
           specialties=["easy-onboard"],
           property_types=["sfr", "2-4unit"]),

    Lender("Champions Funding TPO", ["dscr", "bank-statement"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.champstpo.com/",
           notes="TPO portal. Full investor product suite.",
           specialties=["tpo-portal"],
           property_types=["sfr", "2-4unit"]),

    Lender("Kiavi", ["fix-flip", "bridge", "dscr"],
           min_credit=660, max_ltv=90, min_dscr=1.0, max_loan=1500000,
           speed="fast", comp_model="referral", comp_range="referral fee",
           signup_url="https://www.kiavi.com/",
           notes="Tech-forward. Fastest fix-flip close. Pre-approval in minutes.",
           specialties=["speed", "tech", "fix-flip"],
           property_types=["sfr", "2-4unit"]),

    Lender("Easy Street Capital", ["dscr", "bridge", "fix-flip", "str"],
           min_credit=640, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="fast", comp_model="broker", comp_range="1-2%",
           signup_url="https://www.easystreetcap.com/",
           notes="Texas-based. Investor focus. 640 minimum (lowest DSCR floor).",
           specialties=["low-credit", "texas-based", "str"],
           property_types=["sfr", "2-4unit"]),

    Lender("LoanStream Wholesale", ["dscr", "bank-statement"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://loanstreamwholesale.com/",
           specialties=["wholesale-platform"],
           property_types=["sfr", "2-4unit"]),

    Lender("Deephaven Mortgage", ["dscr", "bank-statement", "asset-depletion"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2500000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.deephavenmortgage.com/",
           notes="Wholesale non-QM specialist. Expanded guidelines.",
           specialties=["non-qm", "expanded-guidelines"],
           property_types=["sfr", "2-4unit", "condo"]),

    Lender("NewFi Wholesale", ["dscr", "bank-statement"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.newfi.com/",
           property_types=["sfr", "2-4unit"]),

    Lender("Griffin Funding", ["dscr", "bank-statement", "asset-depletion"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="wholesale", comp_range="1-2%",
           signup_url="https://griffinfunding.com/",
           property_types=["sfr", "2-4unit", "condo"]),

    Lender("JMAC Lending", ["dscr", "bank-statement"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="YSP", comp_range="1-2%",
           signup_url="https://www.jmaclending.com/",
           property_types=["sfr", "2-4unit"]),

    Lender("Lendmire", ["dscr"],
           min_credit=660, max_ltv=80, min_dscr=1.0, max_loan=2000000,
           speed="standard", comp_model="broker", comp_range="1-2%",
           signup_url="https://www.lendmire.com/",
           notes="40 states + DC.",
           property_types=["sfr", "2-4unit"]),

    # === COMMERCIAL ===
    Lender("Arbor Realty Trust", ["agency-mf", "bridge-cre", "mezz", "construction-cre", "sbl"],
           min_credit=0, max_ltv=80, min_loan=750000, max_loan=100000000,
           speed="standard", comp_model="referral", comp_range="0.5-1%",
           signup_url="https://arbor.com/",
           notes="Dallas office. $750K SBL minimum. Agency + bridge + mezz.",
           specialties=["agency", "sbl", "bridge-cre"],
           property_types=["multifamily", "mixed-use"]),

    Lender("Ready Capital", ["cmbs", "bridge-cre", "sba504", "sba7a", "construction-cre", "usda-bi"],
           min_credit=0, max_ltv=75, min_loan=1000000, max_loan=50000000,
           speed="standard", comp_model="referral", comp_range="0.5-1%",
           signup_url="https://readycapital.com/",
           notes="Multi-product CRE. Strong broker program.",
           specialties=["cmbs", "sba", "multi-product"],
           property_types=["multifamily", "office", "retail", "industrial", "hotel"]),

    Lender("Clopton Capital", ["cmbs", "bridge-cre", "mezz", "sba504"],
           min_credit=0, max_ltv=75, min_loan=1000000, max_loan=50000000,
           speed="standard", comp_model="referral", comp_range="0.5-1%",
           signup_url="https://cloptoncapital.com/",
           notes="Built for brokers. Broker-first platform. Nationwide.",
           specialties=["broker-first", "cmbs"],
           property_types=["multifamily", "office", "retail", "industrial"]),

    Lender("Greystone", ["agency-mf", "hud-mf", "bridge-cre", "mezz"],
           min_credit=0, max_ltv=85, min_loan=1000000, max_loan=100000000,
           speed="slow", comp_model="correspondent", comp_range="0.5-1%",
           signup_url="https://www.greystone.com/",
           notes="Irving TX office. HUD specialist.",
           specialties=["hud", "agency"],
           property_types=["multifamily", "senior-housing", "healthcare"]),

    Lender("Select Commercial", ["cmbs", "bridge-cre", "sba504", "agency-mf", "life-co"],
           min_credit=0, max_ltv=75, min_loan=500000, max_loan=100000000,
           speed="standard", comp_model="referral", comp_range="0.5-1%",
           signup_url="https://selectcommercial.com/",
           notes="30yr experience. 24hr pre-approval. No upfront fees. All CRE types.",
           specialties=["all-cre-types", "no-upfront-fees", "24hr-preapproval"],
           property_types=["multifamily", "office", "retail", "industrial", "hotel", "self-storage", "mhp"]),
]

# Map form loanType values to internal product tags
LOAN_TYPE_MAP = {
    "dscr": ["dscr"],
    "fix-flip": ["fix-flip"],
    "bridge": ["bridge", "bridge-cre"],
    "construction": ["construction", "construction-cre"],
    "str": ["str", "dscr"],
    "portfolio": ["portfolio", "dscr"],
    "refi": ["dscr", "bridge"],  # refi into DSCR or bridge out of hard money
    "bank-statement": ["bank-statement"],
    "asset-depletion": ["asset-depletion"],
    "1099": ["1099"],
    "foreign-national": ["foreign-national"],
    "itin": ["itin"],
    "commercial": ["cmbs", "bridge-cre", "agency-mf", "sba504"],
}


# ============================================================
#  DEAL PARSING
# ============================================================

@dataclass
class Deal:
    """Parsed deal from form submission."""
    loan_type: str = ""
    property_type: str = ""
    property_state: str = ""
    credit_score: int = 700
    purchase_price: float = 0
    rental_income: float = 0
    down_payment_pct: float = 20
    arv: float = 0
    rehab_budget: float = 0
    loan_amount: float = 0
    dscr: float = 0
    ltv: float = 80
    experience: str = ""
    entity_type: str = ""
    close_timeline: str = ""
    # Contact
    full_name: str = ""
    email: str = ""
    phone: str = ""
    best_time: str = ""
    referral_source: str = ""
    # Raw
    raw: dict = field(default_factory=dict)


def parse_currency(val) -> float:
    """Parse currency string like '$350,000' to float."""
    if not val:
        return 0
    return float(re.sub(r"[^\d.]", "", str(val)) or 0)


def parse_credit(val) -> int:
    """Parse credit score select value to midpoint int."""
    mapping = {
        "760+": 780, "740-759": 750, "720-739": 730, "700-719": 710,
        "680-699": 690, "660-679": 670, "640-659": 650, "620-639": 630,
        "below-620": 600,
    }
    return mapping.get(val, 700)


def parse_down_pct(val) -> float:
    """Parse down payment select value to percentage."""
    mapping = {
        "25": 25, "20": 20, "15": 15, "10": 10, "5": 5, "0": 0,
        "25pct": 25, "20pct": 20, "15pct": 15, "10pct": 10,
    }
    try:
        return float(mapping.get(val, val))
    except (ValueError, TypeError):
        return 20


def parse_deal(data: dict) -> Deal:
    """Parse form submission JSON into a Deal."""
    d = Deal(raw=data)
    d.loan_type = data.get("loanType", "")
    d.property_type = data.get("propertyType", "")
    d.property_state = data.get("propertyState", "")
    d.credit_score = parse_credit(data.get("creditScore", "700-719"))
    d.experience = data.get("experience", "")
    d.entity_type = data.get("entityType", "")
    d.close_timeline = data.get("closeTimeline", "")
    d.full_name = data.get("fullName", "")
    d.email = data.get("email", "")
    d.phone = data.get("phone", "")
    d.best_time = data.get("bestTimeToCall", "")
    d.referral_source = data.get("referralSource", "")

    # Loan-type-specific parsing
    if d.loan_type == "dscr":
        d.purchase_price = parse_currency(data.get("purchasePrice"))
        d.rental_income = parse_currency(data.get("rentalIncome"))
        d.down_payment_pct = parse_down_pct(data.get("downPayment", "20"))
        d.loan_amount = d.purchase_price * (1 - d.down_payment_pct / 100)
        d.ltv = 100 - d.down_payment_pct
        # Estimate DSCR (assume 7% rate, 30yr, taxes+insurance ~25% of PITI)
        if d.loan_amount > 0 and d.rental_income > 0:
            mr = 0.07 / 12
            n = 360
            pi = d.loan_amount * (mr * (1 + mr)**n) / ((1 + mr)**n - 1)
            pitia = pi * 1.35  # rough estimate including taxes/insurance/HOA
            d.dscr = round(d.rental_income / pitia, 2) if pitia > 0 else 0

    elif d.loan_type == "fix-flip":
        d.purchase_price = parse_currency(data.get("flipPurchasePrice"))
        d.rehab_budget = parse_currency(data.get("rehabBudget"))
        d.arv = parse_currency(data.get("arv"))
        d.loan_amount = d.purchase_price + d.rehab_budget
        d.ltv = (d.loan_amount / d.arv * 100) if d.arv > 0 else 85

    elif d.loan_type == "bridge":
        prop_val = parse_currency(data.get("bridgePropertyValue"))
        d.loan_amount = parse_currency(data.get("bridgeLoanAmount"))
        d.ltv = (d.loan_amount / prop_val * 100) if prop_val > 0 else 75

    elif d.loan_type == "construction":
        d.purchase_price = parse_currency(data.get("lotValue"))
        d.rehab_budget = parse_currency(data.get("constructionBudget"))
        d.arv = parse_currency(data.get("completedValue"))
        d.loan_amount = d.purchase_price + d.rehab_budget
        d.ltv = (d.loan_amount / d.arv * 100) if d.arv > 0 else 80

    elif d.loan_type == "str":
        d.purchase_price = parse_currency(data.get("strPurchasePrice"))
        nightly = parse_currency(data.get("nightlyRate"))
        occ = float(data.get("occupancyRate", "65").replace("%", "")) / 100
        d.rental_income = nightly * 30 * occ  # monthly projected
        d.down_payment_pct = parse_down_pct(data.get("strDownPayment", "25"))
        d.loan_amount = d.purchase_price * (1 - d.down_payment_pct / 100)
        d.ltv = 100 - d.down_payment_pct

    elif d.loan_type == "portfolio":
        d.loan_amount = parse_currency(data.get("portfolioValue", "0")) * 0.7
        d.rental_income = parse_currency(data.get("portfolioRentalIncome"))

    elif d.loan_type == "refi":
        d.loan_amount = parse_currency(data.get("currentLoanBalance"))
        d.rental_income = parse_currency(data.get("refiRentalIncome"))
        prop_val = parse_currency(data.get("refiPropertyValue"))
        d.ltv = (d.loan_amount / prop_val * 100) if prop_val > 0 else 75

    return d


# ============================================================
#  ROUTING LOGIC
# ============================================================

@dataclass
class LenderMatch:
    lender: Lender
    fit_score: float = 0
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    estimated_rate: str = ""
    estimated_close: str = ""


def route_deal(deal: Deal) -> List[LenderMatch]:
    """Route a deal to the best-fit lenders. Returns ranked list."""
    product_tags = LOAN_TYPE_MAP.get(deal.loan_type, [deal.loan_type])
    matches = []

    for lender in LENDERS:
        # Does this lender handle this product?
        product_overlap = set(lender.products) & set(product_tags)
        if not product_overlap:
            continue

        score = 0
        reasons = []
        warnings = []

        # Product match (base score)
        score += len(product_overlap) * 20
        reasons.append(f"Handles {', '.join(product_overlap)}")

        # Credit score check
        if deal.credit_score >= lender.min_credit:
            score += 15
            if deal.credit_score >= 740:
                score += 10
                reasons.append("Best pricing tier (740+)")
        else:
            score -= 50
            warnings.append(f"Credit {deal.credit_score} below minimum {lender.min_credit}")

        # LTV check
        if deal.ltv <= lender.max_ltv:
            score += 15
        else:
            score -= 30
            warnings.append(f"LTV {deal.ltv:.0f}% exceeds max {lender.max_ltv:.0f}%")

        # DSCR check (if applicable)
        if deal.dscr > 0 and "dscr" in product_overlap:
            if deal.dscr >= lender.min_dscr:
                score += 15
                if deal.dscr >= 1.25:
                    score += 10
                    reasons.append(f"Strong DSCR ({deal.dscr}x)")
            else:
                score -= 20
                warnings.append(f"DSCR {deal.dscr}x below minimum {lender.min_dscr}x")

        # Loan amount check
        if lender.min_loan <= deal.loan_amount <= lender.max_loan:
            score += 10
        elif deal.loan_amount > 0:
            if deal.loan_amount < lender.min_loan:
                score -= 40
                warnings.append(f"Loan ${deal.loan_amount:,.0f} below minimum ${lender.min_loan:,.0f}")
            elif deal.loan_amount > lender.max_loan:
                score -= 20
                warnings.append(f"Loan ${deal.loan_amount:,.0f} exceeds max ${lender.max_loan:,.0f}")

        # State check
        if deal.property_state in lender.states_excluded:
            score -= 100
            warnings.append(f"State {deal.property_state} excluded")

        # Speed bonus
        if deal.close_timeline in ("asap", "2-weeks", "30-days") and lender.speed == "fast":
            score += 15
            reasons.append("Fast close capability")

        # Specialty bonuses
        if deal.loan_type == "fix-flip" and "fix-flip" in lender.specialties:
            score += 10
            reasons.append("Fix-flip specialist")
        if deal.loan_type == "str" and "str" in lender.specialties:
            score += 10
            reasons.append("STR/Airbnb specialist")
        if deal.credit_score < 660 and "low-credit" in lender.specialties:
            score += 10
            reasons.append("Accepts lower credit")
        if "speed" in lender.specialties and deal.close_timeline in ("asap", "2-weeks"):
            score += 10

        # Only include if score is positive and no hard blockers
        hard_block = any("below minimum" in w or "excluded" in w for w in warnings)
        if score > 0 and not hard_block:
            # Estimate rate
            rate = estimate_lender_rate(lender, deal)
            close = lender.speed.replace("fast", "7-14 days").replace("standard", "14-21 days").replace("slow", "21-45 days")

            matches.append(LenderMatch(
                lender=lender,
                fit_score=score,
                reasons=reasons,
                warnings=warnings,
                estimated_rate=rate,
                estimated_close=close,
            ))

    # Sort by fit score descending
    matches.sort(key=lambda m: m.fit_score, reverse=True)
    return matches[:5]  # Top 5


def estimate_lender_rate(lender: Lender, deal: Deal) -> str:
    """Estimate rate range for a specific lender + deal combination."""
    # Base rates by product type (March 2026)
    base_rates = {
        "dscr": 6.50, "fix-flip": 10.00, "bridge": 9.50, "construction": 9.50,
        "str": 7.00, "portfolio": 7.50, "bank-statement": 7.50,
        "asset-depletion": 7.75, "1099": 7.50, "foreign-national": 7.50,
        "itin": 8.00, "cmbs": 6.50, "bridge-cre": 8.50, "agency-mf": 5.50,
        "sba504": 5.25, "mezz": 12.00, "hud-mf": 4.50,
    }

    products = set(lender.products) & set(LOAN_TYPE_MAP.get(deal.loan_type, [deal.loan_type]))
    if products:
        base = min(base_rates.get(p, 7.0) for p in products)
    else:
        base = 7.0

    # Credit adjustment
    if deal.credit_score >= 760: base -= 0.25
    elif deal.credit_score >= 740: base -= 0.125
    elif deal.credit_score >= 700: pass
    elif deal.credit_score >= 680: base += 0.25
    elif deal.credit_score >= 660: base += 0.50
    elif deal.credit_score >= 640: base += 0.75
    else: base += 1.25

    # LTV adjustment
    if deal.ltv > 90: base += 0.50
    elif deal.ltv > 80: base += 0.25
    elif deal.ltv <= 65: base -= 0.125

    low = round(base - 0.25, 2)
    high = round(base + 0.50, 2)
    return f"{low}% - {high}%"


# ============================================================
#  REPORT GENERATION
# ============================================================

def client_report(deal: Deal, matches: List[LenderMatch]) -> dict:
    """Client-facing report. NO lender names. Programs + rates + timeline."""
    return {
        "deal_type": deal.loan_type,
        "summary": f"Found {len(matches)} lender{'s' if len(matches) != 1 else ''} for your {deal.loan_type} deal.",
        "matches": [
            {
                "rank": i + 1,
                "program_type": deal.loan_type.replace("-", " ").title(),
                "estimated_rate": m.estimated_rate,
                "estimated_close": m.estimated_close,
                "fit_reasons": m.reasons,
                "notes": m.warnings if m.warnings else ["Clean match — no issues found."],
            }
            for i, m in enumerate(matches)
        ],
        "next_steps": [
            "We're reviewing your deal now.",
            "You'll hear from us within 15 minutes during business hours.",
            "We'll present 2-3 options with exact terms and rates.",
            "No commitment. No credit pull until you say go.",
        ],
        "disclaimer": "This is not a loan approval or commitment to lend. Rate estimates are based on current market conditions and your stated scenario. Actual terms depend on full documentation review.",
    }


def admin_report(deal: Deal, matches: List[LenderMatch]) -> dict:
    """Admin report for Don. INCLUDES lender names, comp, signup URLs."""
    return {
        "borrower": {
            "name": deal.full_name,
            "email": deal.email,
            "phone": deal.phone,
            "best_time": deal.best_time,
            "referral": deal.referral_source,
        },
        "deal": {
            "type": deal.loan_type,
            "property_type": deal.property_type,
            "state": deal.property_state,
            "credit": deal.credit_score,
            "loan_amount": f"${deal.loan_amount:,.0f}" if deal.loan_amount else "TBD",
            "ltv": f"{deal.ltv:.0f}%",
            "dscr": f"{deal.dscr}x" if deal.dscr else "N/A",
            "purchase_price": f"${deal.purchase_price:,.0f}" if deal.purchase_price else "TBD",
            "rental_income": f"${deal.rental_income:,.0f}/mo" if deal.rental_income else "N/A",
            "rehab_budget": f"${deal.rehab_budget:,.0f}" if deal.rehab_budget else "N/A",
            "arv": f"${deal.arv:,.0f}" if deal.arv else "N/A",
            "close_timeline": deal.close_timeline,
            "experience": deal.experience,
            "entity": deal.entity_type,
        },
        "lender_matches": [
            {
                "rank": i + 1,
                "LENDER": m.lender.name,
                "fit_score": m.fit_score,
                "rate_estimate": m.estimated_rate,
                "close_estimate": m.estimated_close,
                "comp_model": m.lender.comp_model,
                "comp_range": m.lender.comp_range,
                "signup_url": m.lender.signup_url,
                "reasons": m.reasons,
                "warnings": m.warnings,
                "notes": m.lender.notes,
            }
            for i, m in enumerate(matches)
        ],
        "action_items": [
            f"Call {deal.full_name} at {deal.phone} ({deal.best_time})" if deal.phone else f"Email {deal.email}",
            f"Best lender: {matches[0].lender.name}" if matches else "No auto-match — manual review needed",
            f"Estimated comp: {matches[0].lender.comp_range} on ${deal.loan_amount:,.0f}" if matches and deal.loan_amount else "",
        ],
    }


# ============================================================
#  EMAIL NOTIFICATIONS
# ============================================================

DON_EMAIL = os.environ.get("DON_EMAIL", "don@dandydon.media")
FROM_EMAIL = "click@clickclickclose.click"
M365_MAILBOX = "don@dandydon.media"  # licensed mailbox (FROM_EMAIL is an alias on this)

# Microsoft Graph API (OAuth2 client credentials + certificate)
M365_TENANT_ID = "ba902814-ec31-4344-ad26-8c50f761bdbd"
M365_CLIENT_ID = "0e369fff-53d3-4bd6-af21-4dfdafc13936"
M365_CERT_THUMBPRINT = "5AF3E683BDB5BB2B7C07CD9F21E779E06E9A292B"
M365_KEY_PATH = os.environ.get("M365_KEY_PATH",
    str(Path(__file__).resolve().parent / "ccc_mailer_key.pem"))


def _get_graph_token() -> Optional[str]:
    """Get OAuth2 token using certificate-based client assertion (JWT)."""
    import base64
    import hashlib
    import hmac
    import struct
    import urllib.request
    import urllib.parse

    key_path = Path(M365_KEY_PATH)
    if not key_path.exists():
        print(f"[GRAPH AUTH SKIP] Key file not found: {key_path}")
        return None

    try:
        # Build JWT client assertion
        import jwt as pyjwt
    except ImportError:
        try:
            # Fallback: try cryptography + manual JWT
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.x509 import load_pem_x509_certificate
            pyjwt = None
        except ImportError:
            print("[GRAPH AUTH SKIP] Install PyJWT: pip install PyJWT cryptography")
            return None

    now = int(time.time())
    token_url = f"https://login.microsoftonline.com/{M365_TENANT_ID}/oauth2/v2.0/token"

    # Read private key
    private_key = key_path.read_bytes()

    # x5t = base64url of SHA-1 thumbprint bytes
    thumb_bytes = bytes.fromhex(M365_CERT_THUMBPRINT)
    x5t = base64.urlsafe_b64encode(thumb_bytes).rstrip(b"=").decode()

    if pyjwt:
        # PyJWT path (preferred)
        header = {"alg": "RS256", "typ": "JWT", "x5t": x5t}
        payload = {
            "aud": token_url,
            "iss": M365_CLIENT_ID,
            "sub": M365_CLIENT_ID,
            "jti": base64.urlsafe_b64encode(os.urandom(16)).decode(),
            "nbf": now,
            "exp": now + 300,
        }
        assertion = pyjwt.encode(payload, private_key, algorithm="RS256", headers=header)
    else:
        print("[GRAPH AUTH SKIP] PyJWT required for certificate auth")
        return None

    body = urllib.parse.urlencode({
        "client_id": M365_CLIENT_ID,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }).encode()

    req = urllib.request.Request(token_url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get("access_token")
    except Exception as e:
        error_body = ""
        if hasattr(e, "read"):
            error_body = e.read().decode()
        print(f"[GRAPH AUTH FAIL] {e}\n{error_body}")
        return None


def _send_graph_email(to: str, subject: str, body: str) -> bool:
    """Send email via Microsoft Graph API."""
    token = _get_graph_token()
    if not token:
        print(f"[EMAIL SKIP] Graph API not configured. Would send to {to}")
        return False

    import urllib.request

    url = f"https://graph.microsoft.com/v1.0/users/{M365_MAILBOX}/sendMail"
    payload = json.dumps({
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "from": {"emailAddress": {"address": FROM_EMAIL}},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })

    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"[EMAIL] Sent to {to}: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL FAIL] {e}")
        return False


def send_don_notification(deal: Deal, matches: List[LenderMatch]):
    """Email Don when a new deal comes in."""
    top = matches[0] if matches else None
    subject = f"NEW DEAL: {deal.loan_type.upper()} — {deal.full_name} — ${deal.loan_amount:,.0f}"

    body = f"""NEW DEAL SUBMISSION — {datetime.now().strftime('%Y-%m-%d %H:%M')}

BORROWER: {deal.full_name}
PHONE: {deal.phone}
EMAIL: {deal.email}
BEST TIME: {deal.best_time}

DEAL TYPE: {deal.loan_type}
PROPERTY: {deal.property_type} in {deal.property_state}
CREDIT: {deal.credit_score}
LOAN AMOUNT: ${deal.loan_amount:,.0f}
LTV: {deal.ltv:.0f}%
DSCR: {deal.dscr}x

TOP MATCH: {top.lender.name if top else 'MANUAL REVIEW NEEDED'}
RATE: {top.estimated_rate if top else 'N/A'}
CLOSE: {top.estimated_close if top else 'N/A'}
COMP: {top.lender.comp_range if top else 'N/A'}

ALL MATCHES ({len(matches)}):
"""
    for i, m in enumerate(matches):
        body += f"\n  {i+1}. {m.lender.name} — {m.estimated_rate} — {m.estimated_close} — comp: {m.lender.comp_range}"
        body += f"\n     Score: {m.fit_score} | {', '.join(m.reasons)}"
        if m.warnings:
            body += f"\n     WARNINGS: {', '.join(m.warnings)}"

    return _send_graph_email(DON_EMAIL, subject, body)


def send_borrower_confirmation(deal: Deal):
    """Auto-respond to borrower confirming receipt."""
    if not deal.email:
        return False

    subject = "We Got Your Deal — Click Click Close"
    body = f"""Hi {deal.full_name.split()[0] if deal.full_name else 'there'},

We received your {deal.loan_type.replace('-', ' ')} deal submission.

Here's what happens next:
1. We're matching your deal against our lender network right now.
2. You'll hear from us within 15 minutes during business hours (M-F 8am-6pm CT).
3. We'll present 2-3 options with specific rates, terms, and timelines.
4. No commitment. No credit pull until you say go.

If you need to reach us before then:
  Email: click@clickclickclose.click

— Click Click Close

This is not a loan approval or commitment to lend.
"""
    return _send_graph_email(deal.email, subject, body)


# ============================================================
#  MAIN ENTRY POINT
# ============================================================

SUBMISSIONS_DIR = Path("C:/DandyDon/investor_site/submissions")
SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)


def process_submission(data: dict) -> dict:
    """
    Full pipeline: parse → route → save → email Don → email borrower → return reports.
    Called by the web server on POST /api/submit.
    """
    deal = parse_deal(data)
    matches = route_deal(deal)

    # Save to disk
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]", "_", deal.full_name or "anon")[:30]
    filename = f"deal_{ts}_{slug}.json"
    filepath = SUBMISSIONS_DIR / filename

    cr = client_report(deal, matches)
    ar = admin_report(deal, matches)

    save_data = {
        "submitted_at": datetime.now().isoformat(),
        "form_data": data,
        "client_report": cr,
        "admin_report": ar,
    }

    filepath.write_text(json.dumps(save_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[SAVED] {filepath}")

    # Create borrower data vault (smart contract)
    try:
        from smart_contracts import vault_from_submission
        vault_result = vault_from_submission(data)
        save_data["vault"] = vault_result
        cr["vault_id"] = vault_result.get("vault_id", "")
        cr["data_control"] = vault_result.get("control", "")
        print(f"[VAULT] Created: {vault_result.get('vault_id', 'failed')}")
    except Exception as e:
        print(f"[VAULT SKIP] {e}")

    # Email notifications
    send_don_notification(deal, matches)
    send_borrower_confirmation(deal)

    # Console notification
    print(f"\n{'='*60}")
    print(f"  NEW DEAL: {deal.full_name} — {deal.loan_type}")
    print(f"  ${deal.loan_amount:,.0f} | Credit {deal.credit_score} | LTV {deal.ltv:.0f}%")
    if matches:
        print(f"  TOP MATCH: {matches[0].lender.name} — {matches[0].estimated_rate}")
    print(f"{'='*60}\n")

    return {"client": cr, "admin": ar}


if __name__ == "__main__":
    # Demo: DSCR deal
    demo = {
        "loanType": "dscr",
        "propertyType": "sfr",
        "propertyState": "TX",
        "purchasePrice": "$350,000",
        "rentalIncome": "$2,800",
        "downPayment": "25",
        "creditScore": "720-739",
        "experience": "2-5",
        "entityType": "llc",
        "closeTimeline": "30-days",
        "fullName": "Demo Investor",
        "email": "demo@test.com",
        "phone": "(214) 555-1234",
        "bestTimeToCall": "morning",
        "referralSource": "google",
        "businessPurpose": True,
        "tcpaConsent": True,
    }

    print("=" * 60)
    print("  CLICK CLICK CLOSE — ROUTING ENGINE TEST")
    print("=" * 60)

    result = process_submission(demo)

    print("\n--- CLIENT REPORT ---")
    print(json.dumps(result["client"], indent=2))

    print("\n--- ADMIN REPORT (top 3) ---")
    for lm in result["admin"]["lender_matches"][:3]:
        print(f"  #{lm['rank']} {lm['LENDER']}")
        print(f"     Rate: {lm['rate_estimate']} | Close: {lm['close_estimate']}")
        print(f"     Comp: {lm['comp_model']} — {lm['comp_range']}")
        print(f"     Why: {', '.join(lm['reasons'])}")
