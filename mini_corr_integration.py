#!/usr/bin/env python3
"""
mini_corr_integration.py — Click Click Close Mini-Correspondent Integration
============================================================================
Manages the transition from broker → table-funding → mini-corr → full correspondent.

Three things this module does:
  1. CHANNEL ROUTER — given a deal, returns the best close channel
     (broker / table_fund / mini_corr / correspondent) and why
  2. COMP CALCULATOR — exact comp projection for each channel option
  3. LENDER CHANNEL REGISTRY — every lender, every channel they offer,
     with onboarding requirements and dry-state restrictions

Key research findings (verified 2026-03-18):
  - A&D Mortgage      → explicitly offers "Mini Correspondent" (3-tier)
  - Lima One          → "White-Label Table Funding" — best for new brokerage
  - Roc Capital       → "White-Label Table Funding / TPO" — 4,000+ lenders, no buyback
  - RCN Capital       → "Correspondent Program" — white-label, 44 states
  - Angel Oak         → Non-Delegated + Delegated Correspondent
  - Deephaven         → Correspondent (200+ lenders)
  - JMAC Lending      → Correspondent channel
  - Visio Lending     → Broker ONLY — no correspondent path
  - Kiavi             → Direct only — no TPO program

CFPB Warning (2014, still active):
  Must actually function as a lender to claim mini-corr status.
  You must: issue your own disclosures, control QC/compliance, order appraisals,
  fund the closing (even via table funding), and sell to the investor.
  Acting like a broker while calling yourself a mini-corr = enforcement risk.

Table Funding Note:
  Dry-funding states (AZ, CA, HI, ID, NM, OR, WA) require funds disbursed
  only AFTER all docs are reviewed. True simultaneous assignment is harder.
  Wet-funding states: all others — table funding is clean.

Authors: Don Brown & Claude (Spock/Specter)
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
#  CHANNEL DEFINITIONS
# ============================================================

CHANNEL_BROKER        = "broker"          # YSP or borrower-paid, ~2.75% ceiling, full disclosure
CHANNEL_TABLE_FUND    = "table_fund"      # close in our name, investor funds at table, no warehouse line
CHANNEL_MINI_CORR     = "mini_corr"       # close in our name, warehouse line required, non-delegated UW
CHANNEL_CORRESPONDENT = "correspondent"   # close in our name, delegated UW, full lender authority

CHANNEL_LABELS = {
    CHANNEL_BROKER:        "Broker",
    CHANNEL_TABLE_FUND:    "Table Funding (close in our name, no warehouse line)",
    CHANNEL_MINI_CORR:     "Mini-Correspondent (close in our name, warehouse line)",
    CHANNEL_CORRESPONDENT: "Full Correspondent (close in our name, delegated UW)",
}

# Dry-funding states — table funding is structurally harder
DRY_FUNDING_STATES = {"AZ", "CA", "HI", "ID", "NM", "OR", "WA"}


# ============================================================
#  LENDER CHANNEL REGISTRY
# ============================================================

@dataclass
class LenderChannel:
    lender_id: str
    lender_name: str
    channels: List[str]                          # which channels this lender supports
    loan_types: List[str]                        # dscr, fix-flip, bridge, non-qm, etc.
    states_available: str                        # "nationwide" or list
    states_excluded: List[str] = field(default_factory=list)

    # Broker channel
    broker_comp_ceiling: float = 2.75            # % max comp in broker channel
    broker_notes: str = ""

    # Table funding
    table_fund_available: bool = False
    table_fund_no_buyback: bool = False          # does lender take buyback risk?
    table_fund_no_warehouse: bool = True         # can we table fund without our own warehouse?
    table_fund_notes: str = ""

    # Mini-corr / correspondent
    corr_delegated: bool = False                 # delegated underwriting available?
    corr_min_net_worth: int = 0                  # $ minimum net worth for corr channel
    corr_requires_warehouse: bool = False
    corr_portal_url: str = ""
    corr_notes: str = ""

    # Comp in lender channel
    corr_comp_ceiling: float = 10.0              # % max comp in correspondent/table-fund channel
    corr_comp_notes: str = ""

    # Onboarding
    signup_url: str = ""
    contact: str = ""


LENDER_CHANNELS: Dict[str, LenderChannel] = {

    "rcn_capital": LenderChannel(
        lender_id="rcn_capital",
        lender_name="RCN Capital",
        channels=[CHANNEL_BROKER, CHANNEL_TABLE_FUND, CHANNEL_MINI_CORR],
        loan_types=["dscr", "fix_flip", "bridge", "construction"],
        states_available="44 states",
        states_excluded=["AK", "SD", "ND", "VT", "NV", "MN"],
        broker_comp_ceiling=2.75,
        broker_notes="Standard YSP. Fast close. 44 states.",
        table_fund_available=True,
        table_fund_no_buyback=False,
        table_fund_no_warehouse=True,
        table_fund_notes="White-label branding. Borrower sees Click Click Close. Close in our name.",
        corr_delegated=False,
        corr_requires_warehouse=False,
        corr_comp_ceiling=6.0,
        corr_comp_notes="Flexible yield spread. Accelerated Launch Program (bonus comp first 90 days). Executive Advantage Program for high volume.",
        corr_portal_url="https://rcncapital.com/correspondent-program/",
        contact="Dave Young, Correspondent Lending Manager",
        signup_url="https://rcncapital.com/correspondent-program/",
    ),

    "lima_one_capital": LenderChannel(
        lender_id="lima_one_capital",
        lender_name="Lima One Capital",
        channels=[CHANNEL_BROKER, CHANNEL_TABLE_FUND],
        loan_types=["dscr", "fix_flip", "bridge", "construction"],
        states_available="nationwide",
        broker_comp_ceiling=2.75,
        table_fund_available=True,
        table_fund_no_buyback=True,
        table_fund_no_warehouse=True,
        table_fund_notes=(
            "White-Label Table Funding. Lima One funds 100% at closing. "
            "Loan closes in Click Click Close name. Lima One underwrites (non-delegated). "
            "No warehouse line. No buyback risk. Borrower sees only our brand. "
            "Separate programs for short-term (fix-flip) and long-term (rental/DSCR)."
        ),
        corr_delegated=False,
        corr_comp_ceiling=8.0,
        corr_comp_notes="Yield spread captured between investor net yield and rate charged to borrower.",
        corr_portal_url="https://www.limaone.com/white-label-table-funding-and-loan-origination/",
        signup_url="https://www.limaone.com/white-label-table-funding-and-loan-origination/",
    ),

    "roc_capital": LenderChannel(
        lender_id="roc_capital",
        lender_name="Roc Capital",
        channels=[CHANNEL_BROKER, CHANNEL_TABLE_FUND],
        loan_types=["dscr", "fix_flip", "bridge"],
        states_available="44 states",
        states_excluded=["AK", "SD", "ND", "VT"],
        broker_comp_ceiling=2.75,
        table_fund_available=True,
        table_fund_no_buyback=True,
        table_fund_no_warehouse=True,
        table_fund_notes=(
            "White-Label Table Funding / TPO model. 4,000+ private lenders. "
            "No reps-and-warranties buyback. Roc takes the balance sheet risk. "
            "Historical: Roc 90% / partner 10% capital — but 0% partner capital now available. "
            "Loan documents in Click Click Close name. Assigned to Roc post-close."
        ),
        corr_comp_ceiling=8.0,
        corr_portal_url="https://roccapital.com/white-label-table-funding/",
        signup_url="https://roccapital.com/white-label-table-funding/",
    ),

    "ad_mortgage": LenderChannel(
        lender_id="ad_mortgage",
        lender_name="A&D Mortgage",
        channels=[CHANNEL_BROKER, CHANNEL_MINI_CORR, CHANNEL_CORRESPONDENT],
        loan_types=["dscr", "bank_statement", "asset_depletion", "foreign_national", "itin"],
        states_available="nationwide",
        broker_comp_ceiling=2.75,
        broker_notes="Top 5 wholesale lender. 24-hour UW turnaround.",
        table_fund_available=False,
        corr_delegated=True,
        corr_requires_warehouse=True,
        corr_min_net_worth=100000,
        corr_comp_ceiling=10.0,
        corr_comp_notes=(
            "Three-tier: Mini Correspondent (non-delegated, light warehouse) → "
            "Non-Delegated Correspondent → Full Delegated Correspondent. "
            "A&D explicitly uses 'Mini Correspondent' terminology. "
            "DSCR: ratios as low as 0, min credit 620, 3 months reserves."
        ),
        corr_portal_url="https://adcorrespondent.com/",
        contact="adcorrespondent.com — dedicated correspondent portal",
        signup_url="https://admortgage.com/correspondent/",
    ),

    "angel_oak": LenderChannel(
        lender_id="angel_oak",
        lender_name="Angel Oak Mortgage Solutions",
        channels=[CHANNEL_BROKER, CHANNEL_MINI_CORR, CHANNEL_CORRESPONDENT],
        loan_types=["dscr", "bank_statement", "asset_depletion", "1099_loan", "foreign_national"],
        states_available="40+ states",
        broker_comp_ceiling=2.75,
        corr_delegated=True,
        corr_requires_warehouse=True,
        corr_min_net_worth=250000,
        corr_comp_ceiling=10.0,
        corr_comp_notes=(
            "Non-Delegated Correspondent: Angel Oak UW and conditions before you close. "
            "Delegated Correspondent: you UW in-house. Application via Comergence. "
            "DSCR 'Investor Cash Flow': to $1.5M, min DSCR 1.0 OR no DSCR with 700 FICO + 75% LTV."
        ),
        corr_portal_url="https://angeloakms.com/application-packages/",
        contact="(855) 539-4910 / info@angeloakms.com",
        signup_url="https://angeloakms.com/application-packages/",
    ),

    "deephaven_mortgage": LenderChannel(
        lender_id="deephaven_mortgage",
        lender_name="Deephaven Mortgage",
        channels=[CHANNEL_BROKER, CHANNEL_MINI_CORR, CHANNEL_CORRESPONDENT],
        loan_types=["dscr", "bank_statement", "asset_depletion", "non_qm"],
        states_available="nationwide",
        broker_comp_ceiling=2.75,
        corr_delegated=True,
        corr_requires_warehouse=True,
        corr_min_net_worth=100000,
        corr_comp_ceiling=10.0,
        corr_comp_notes=(
            "Buys both delegated and non-delegated non-QM loans from 200+ correspondent lenders. "
            "1:1 non-QM origination training. Scenario desk staffed by human underwriters. "
            "Credit floor 620. Max loan $3.5M."
        ),
        corr_portal_url="https://deephavenmortgage.com/correspondent/",
        contact="1-844-346-2677",
        signup_url="https://deephavenmortgage.com/correspondent/",
    ),

    "jmac_lending": LenderChannel(
        lender_id="jmac_lending",
        lender_name="JMAC Lending",
        channels=[CHANNEL_BROKER, CHANNEL_CORRESPONDENT],
        loan_types=["dscr", "bank_statement", "non_qm"],
        states_available="nationwide",
        broker_comp_ceiling=2.75,
        corr_delegated=False,
        corr_requires_warehouse=True,
        corr_comp_ceiling=8.0,
        corr_portal_url="https://www.jmaclending.com/correspondent-product-list",
        signup_url="https://www.jmaclending.com/",
    ),

    "visio_lending": LenderChannel(
        lender_id="visio_lending",
        lender_name="Visio Lending",
        channels=[CHANNEL_BROKER],
        loan_types=["dscr", "str", "portfolio"],
        states_available="nationwide",
        broker_comp_ceiling=5.0,  # Up to 5% — highest broker comp in DSCR space
        broker_notes=(
            "BROKER ONLY — no correspondent or table-funding program. "
            "Up to 5% broker comp. No NMLS required in most states (only AZ and CA). "
            "Best-in-class for DSCR broker comp. Use for broker channel; route elsewhere for mini-corr."
        ),
        table_fund_available=False,
        signup_url="https://www.visiolending.com/partner-programs",
    ),

    "new_silver": LenderChannel(
        lender_id="new_silver",
        lender_name="New Silver",
        channels=[CHANNEL_TABLE_FUND, CHANNEL_MINI_CORR],
        loan_types=["fix_flip", "bridge", "construction"],
        states_available="nationwide",
        table_fund_available=True,
        table_fund_no_buyback=True,
        table_fund_no_warehouse=True,
        table_fund_notes=(
            "White-Label Correspondent. Fix-and-flip and ground-up construction. "
            "Loans to $5M. Close in Click Click Close name."
        ),
        corr_comp_ceiling=8.0,
        signup_url="https://newsilver.com/the-lender/white-label-hard-money-lenders/",
    ),
}


# ============================================================
#  COMP CALCULATOR
# ============================================================

@dataclass
class CompScenario:
    channel: str
    channel_label: str
    lender_name: str
    est_comp_pct: float
    est_comp_dollars: float
    vs_broker_delta_dollars: float
    requires_warehouse: bool
    requires_lender_license: bool
    dry_state_risk: bool
    notes: str


def calculate_comp_scenarios(
    loan_amount: float,
    property_state: str,
    loan_type: str,
    *,
    note_rate: float = 7.5,      # rate charged to borrower
    broker_comp_pct: float = 1.75,  # current broker comp assumption
) -> List[CompScenario]:
    """
    For a given deal, show what comp looks like across every available channel.
    Sorted by comp dollars descending.
    """
    if not loan_amount:
        return []

    broker_comp = loan_amount * (broker_comp_pct / 100)
    is_dry_state = property_state.upper() in DRY_FUNDING_STATES
    scenarios = []

    for lender_id, lc in LENDER_CHANNELS.items():
        # Does this lender handle this loan type?
        lt_normalized = loan_type.replace("-", "_")
        if not any(t in lc.loan_types for t in [lt_normalized, loan_type]):
            continue

        # Broker scenario
        if CHANNEL_BROKER in lc.channels:
            comp = loan_amount * (broker_comp_pct / 100)
            scenarios.append(CompScenario(
                channel=CHANNEL_BROKER,
                channel_label=f"Broker — {lc.lender_name}",
                lender_name=lc.lender_name,
                est_comp_pct=broker_comp_pct,
                est_comp_dollars=comp,
                vs_broker_delta_dollars=0,
                requires_warehouse=False,
                requires_lender_license=False,
                dry_state_risk=False,
                notes=lc.broker_notes or f"Standard broker comp. YSP capped at ~{lc.broker_comp_ceiling}%.",
            ))

        # Table funding scenario
        if CHANNEL_TABLE_FUND in lc.channels and lc.table_fund_available:
            # Estimate: spread between note rate and investor net yield
            # Assume investor net yield demand = note_rate - 0.75 (rough)
            est_spread_pct = 0.75   # conservative estimate of spread capture
            comp = loan_amount * (est_spread_pct / 100) + (loan_amount * 0.01)  # spread + 1pt
            comp_pct = (comp / loan_amount) * 100

            scenarios.append(CompScenario(
                channel=CHANNEL_TABLE_FUND,
                channel_label=f"Table Funding — {lc.lender_name}",
                lender_name=lc.lender_name,
                est_comp_pct=round(comp_pct, 2),
                est_comp_dollars=comp,
                vs_broker_delta_dollars=comp - broker_comp,
                requires_warehouse=False,
                requires_lender_license=True,
                dry_state_risk=is_dry_state,
                notes=(
                    f"Close in Click Click Close name. {lc.lender_name} funds at table. "
                    f"{'NO buyback risk. ' if lc.table_fund_no_buyback else ''}"
                    f"{'NO warehouse line needed. ' if lc.table_fund_no_warehouse else ''}"
                    f"{'DRY STATE: table funding is more complex here. ' if is_dry_state else ''}"
                    f"{lc.table_fund_notes}"
                ),
            ))

        # Mini-corr / correspondent scenario
        if any(c in lc.channels for c in [CHANNEL_MINI_CORR, CHANNEL_CORRESPONDENT]):
            # Conservative: capture 2x broker comp with lender status
            est_pct = min(lc.corr_comp_ceiling, broker_comp_pct * 2.5)
            comp = loan_amount * (est_pct / 100)
            channel = CHANNEL_MINI_CORR if CHANNEL_MINI_CORR in lc.channels else CHANNEL_CORRESPONDENT

            scenarios.append(CompScenario(
                channel=channel,
                channel_label=f"{'Mini-Corr' if channel == CHANNEL_MINI_CORR else 'Correspondent'} — {lc.lender_name}",
                lender_name=lc.lender_name,
                est_comp_pct=round(est_pct, 2),
                est_comp_dollars=comp,
                vs_broker_delta_dollars=comp - broker_comp,
                requires_warehouse=lc.corr_requires_warehouse,
                requires_lender_license=True,
                dry_state_risk=is_dry_state and not lc.corr_requires_warehouse,
                notes=(
                    f"{'Delegated UW available. ' if lc.corr_delegated else 'Non-delegated UW. '}"
                    f"{'Warehouse line required. ' if lc.corr_requires_warehouse else ''}"
                    f"Min net worth: ${lc.corr_min_net_worth:,}. " if lc.corr_min_net_worth else ""
                    f"{lc.corr_comp_notes}"
                ),
            ))

    # Sort: highest comp first
    scenarios.sort(key=lambda s: s.est_comp_dollars, reverse=True)
    return scenarios


def format_comp_report(
    loan_amount: float,
    property_state: str,
    loan_type: str,
    borrower_name: str = "",
) -> str:
    """Human-readable comp scenario comparison."""
    scenarios = calculate_comp_scenarios(loan_amount, property_state, loan_type)

    lines = [
        f"",
        f"{'='*70}",
        f"  COMP SCENARIOS — {borrower_name or 'Deal'}",
        f"  ${loan_amount:,.0f} {loan_type.upper()} | {property_state}",
        f"{'='*70}",
    ]

    if not scenarios:
        lines.append("  No scenarios available for this loan type.")
        return "\n".join(lines)

    broker_dollars = next((s.est_comp_dollars for s in scenarios if s.channel == CHANNEL_BROKER), 0)

    prev_channel = None
    for s in scenarios:
        if s.channel != prev_channel:
            lines.append(f"\n  --- {CHANNEL_LABELS.get(s.channel, s.channel).upper()} ---")
            prev_channel = s.channel

        delta = f"+${s.vs_broker_delta_dollars:,.0f}" if s.vs_broker_delta_dollars > 0 else ""
        warn = " [DRY STATE RISK]" if s.dry_state_risk else ""
        lic = " [LENDER LICENSE REQ]" if s.requires_lender_license else ""
        wh = " [WAREHOUSE REQ]" if s.requires_warehouse else ""

        lines.append(
            f"  {s.lender_name:<28} {s.est_comp_pct:>5.2f}%  ${s.est_comp_dollars:>10,.0f}"
            f"  {delta:<12}{warn}{lic}{wh}"
        )
        if s.notes:
            # Wrap note
            note_lines = [s.notes[i:i+64] for i in range(0, min(len(s.notes), 192), 64)]
            for nl in note_lines[:2]:
                lines.append(f"    {nl}")

    lines.append(f"\n  BROKER BASELINE:  ${broker_dollars:,.0f}")
    best = scenarios[0]
    lines.append(f"  BEST SCENARIO:    ${best.est_comp_dollars:,.0f}  ({best.channel_label})")
    if best.vs_broker_delta_dollars > 0:
        lines.append(f"  ADDITIONAL COMP:  +${best.vs_broker_delta_dollars:,.0f} vs broker")
    lines.append(f"{'='*70}")

    return "\n".join(lines)


# ============================================================
#  CHANNEL ROUTER
# ============================================================

@dataclass
class ChannelRecommendation:
    recommended_channel: str
    recommended_lender: str
    reason: str
    comp_est_dollars: float
    comp_est_pct: float
    vs_broker_uplift: float
    action_items: List[str]
    all_options: List[CompScenario]


def recommend_channel(
    loan_amount: float,
    property_state: str,
    loan_type: str,
    *,
    has_lender_license: bool = False,
    has_warehouse_line: bool = False,
    preferred_lenders: List[str] = None,
) -> ChannelRecommendation:
    """
    Given the deal and Click Click Close's current licensing status,
    recommend the optimal close channel and lender.
    """
    all_scenarios = calculate_comp_scenarios(loan_amount, property_state, loan_type)
    is_dry = property_state.upper() in DRY_FUNDING_STATES

    # Filter to what we can actually do right now
    viable = []
    for s in all_scenarios:
        if s.requires_lender_license and not has_lender_license:
            continue
        if s.requires_warehouse and not has_warehouse_line:
            continue
        viable.append(s)

    # Also keep table-fund options that don't need warehouse
    # even without lender license (as aspirational next step)
    near_term = [s for s in all_scenarios
                 if s.channel == CHANNEL_TABLE_FUND and not s.requires_warehouse]

    if viable:
        best = viable[0]
        reason = f"Best available given current licensing status."
        action = []
        if not has_lender_license:
            action.append("Get Mortgage Lender license in target states to unlock table-funding and mini-corr channels.")
    elif near_term:
        best = near_term[0]
        reason = "Table funding is next step — requires lender license but no warehouse line."
        action = [
            f"Apply for Mortgage Lender license in {property_state}.",
            f"Apply to {best.lender_name} table-funding program.",
            "No warehouse line needed — lender funds at closing table.",
        ]
    else:
        # Fall back to broker
        broker_opts = [s for s in all_scenarios if s.channel == CHANNEL_BROKER]
        best = broker_opts[0] if broker_opts else None
        reason = "Broker channel only — no correspondent or table-funding options for this loan type."
        action = []

    if not best:
        return ChannelRecommendation(
            recommended_channel="none",
            recommended_lender="Manual review required",
            reason="No programs available",
            comp_est_dollars=0,
            comp_est_pct=0,
            vs_broker_uplift=0,
            action_items=["Contact Don — manual review needed."],
            all_options=all_scenarios,
        )

    broker_comp = next((s.est_comp_dollars for s in all_scenarios if s.channel == CHANNEL_BROKER), 0)

    # Build action items
    if best.channel == CHANNEL_BROKER:
        lc = LENDER_CHANNELS.get(next(
            (lid for lid, lc in LENDER_CHANNELS.items() if lc.lender_name == best.lender_name), ""
        ))
        action = [
            f"Submit deal to {best.lender_name} broker channel.",
            f"Expected comp: ${best.est_comp_dollars:,.0f} ({best.est_comp_pct:.2f}%)",
            f"Signup: {lc.signup_url if lc else ''}",
        ]

    return ChannelRecommendation(
        recommended_channel=best.channel,
        recommended_lender=best.lender_name,
        reason=reason,
        comp_est_dollars=best.est_comp_dollars,
        comp_est_pct=best.est_comp_pct,
        vs_broker_uplift=best.vs_broker_delta_dollars,
        action_items=action,
        all_options=all_scenarios,
    )


# ============================================================
#  ONBOARDING ROADMAP
# ============================================================

ONBOARDING_ROADMAP = """
CLICK CLICK CLOSE — MINI-CORR ONBOARDING ROADMAP
==================================================

PHASE 1: NOW (broker license, no warehouse line)
-------------------------------------------------
Priority signups (broker channel):
  1. Visio Lending     → up to 5% comp, no NMLS required most states, DSCR
  2. RCN Capital       → broker channel, YSP + referral, 44 states
  3. Lima One Capital  → broker affiliate, fix-flip + rental
  4. A&D Mortgage      → wholesale, 24hr UW, DSCR + non-QM

PHASE 2: NEAR-TERM (get lender license, use table funding — no warehouse needed)
-------------------------------------------------
Get Mortgage Lender license in TX (and priority states).
Then apply to:
  1. Lima One Capital  → White-Label Table Funding (BEST for new company)
     - No warehouse needed. No buyback risk. Borrower sees only Click Click Close.
     - Fix-flip and DSCR programs. Apply: limaone.com/white-label-table-funding
  2. Roc Capital       → White-Label Table Funding / TPO
     - 4,000+ lenders already using this. No buyback risk.
     - Apply: roccapital.com/white-label-table-funding
  3. RCN Capital       → Correspondent Program
     - White-label branding. Accelerated Launch bonus (first 90 days).
     - Apply: rcncapital.com/correspondent-program

PHASE 3: MEDIUM-TERM (established volume + history, add warehouse line)
-------------------------------------------------
  1. A&D Mortgage Mini-Corr → adcorrespondent.com — explicit "mini-corr" tier
  2. Angel Oak Non-Delegated Correspondent → deepest non-QM product
  3. Deephaven Correspondent → $3.5M max, 200+ lender network

PHASE 4: FULL CORRESPONDENT (warehouse line + delegated UW)
-------------------------------------------------
  1. A&D Mortgage Full Delegated Correspondent
  2. Angel Oak Delegated Correspondent
  3. Build proprietary non-QM products

COMP TRAJECTORY (per $300K loan):
  Phase 1 (broker):        ~$5,250  (1.75%)
  Phase 2 (table fund):    ~$8,250  (2.75% spread + points)
  Phase 3 (mini-corr):     ~$12,000 (4%)
  Phase 4 (full corr):     ~$21,000 (7%)

At 5 loans/month:
  Phase 1:  ~$26K/mo
  Phase 2:  ~$41K/mo
  Phase 3:  ~$60K/mo
  Phase 4:  ~$105K/mo

CFPB COMPLIANCE NOTE:
  To maintain mini-corr status you MUST actually function as a lender.
  Required: issue your own disclosures, control QC/compliance, order appraisals,
  fund the closing (via table funding counts), and sell to investor.
  See: files.consumerfinance.gov/f/201407_cfpb_guidance_mini-correspondent-lenders.pdf

DRY-FUNDING STATE NOTE:
  AZ, CA, HI, ID, NM, OR, WA — funds cannot disburse until all docs reviewed.
  Table funding is more complex in these states. Wet-funding states (TX, FL, etc.)
  are cleaner for table-fund structures.
"""


# ============================================================
#  CLI
# ============================================================

if __name__ == "__main__":
    import sys

    print(ONBOARDING_ROADMAP)

    # Demo comp scenarios
    test_deals = [
        ("Maria Hernandez", 285000, "TX", "dscr"),
        ("James Lee",        450000, "FL", "fix_flip"),
        ("Robert Chen",      890000, "CA", "dscr"),
    ]

    for name, amt, state, lt in test_deals:
        print(format_comp_report(amt, state, lt, name))

        rec = recommend_channel(
            amt, state, lt,
            has_lender_license=False,
            has_warehouse_line=False,
        )
        print(f"\n  RECOMMENDED (broker license only):")
        print(f"    Channel: {CHANNEL_LABELS.get(rec.recommended_channel, rec.recommended_channel)}")
        print(f"    Lender:  {rec.recommended_lender}")
        print(f"    Comp:    ${rec.comp_est_dollars:,.0f} ({rec.comp_est_pct:.2f}%)")
        if rec.vs_broker_uplift > 0:
            print(f"    Uplift:  +${rec.vs_broker_uplift:,.0f} vs broker")

        rec2 = recommend_channel(
            amt, state, lt,
            has_lender_license=True,
            has_warehouse_line=False,
        )
        print(f"\n  RECOMMENDED (with lender license, no warehouse):")
        print(f"    Channel: {CHANNEL_LABELS.get(rec2.recommended_channel, rec2.recommended_channel)}")
        print(f"    Lender:  {rec2.recommended_lender}")
        print(f"    Comp:    ${rec2.comp_est_dollars:,.0f} ({rec2.comp_est_pct:.2f}%)")
        if rec2.vs_broker_uplift > 0:
            print(f"    Uplift:  +${rec2.vs_broker_uplift:,.0f} vs broker baseline")
