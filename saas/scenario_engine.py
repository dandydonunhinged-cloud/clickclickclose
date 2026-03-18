"""
Click Click Close — Multi-Scenario Qualification Engine

Borrowers enter multiple properties/deals. The engine:
1. Qualifies each deal individually
2. Evaluates deals together (portfolio effects, cross-collateral, experience upgrades)
3. Identifies what small changes unlock better programs
4. Updates dynamically as scenarios are added/modified

"Add one more property and you qualify for a portfolio loan at better terms."
"Build 5 units instead of 4 and you unlock agency multifamily — non-recourse, lower rate."
"Your combined NOI qualifies you for CMBS that individual properties don't."
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from config import PRODUCTS, Subscriber, RoutingEngine


class Scenario:
    """A single property/deal scenario"""

    def __init__(self, scenario_id: int, data: Dict):
        self.id = scenario_id
        self.data = data
        self.individual_matches = []
        self.combined_matches = []
        self.upgrade_tips = []

    @property
    def property_type(self) -> str:
        return self.data.get("property", {}).get("type", "unknown")

    @property
    def units(self) -> int:
        return self.data.get("property", {}).get("units", 1)

    @property
    def loan_amount(self) -> float:
        return self.data.get("property", {}).get("loan_amount", 0)

    @property
    def value(self) -> float:
        return self.data.get("property", {}).get("value", 0)

    @property
    def noi(self) -> float:
        return self.data.get("financials", {}).get("noi", 0)

    @property
    def monthly_rent(self) -> float:
        return self.data.get("financials", {}).get("monthly_rent", 0)

    @property
    def purpose(self) -> str:
        return self.data.get("loan", {}).get("purpose", "purchase")

    @property
    def occupancy(self) -> str:
        return self.data.get("property", {}).get("occupancy", "investment")


class MultiScenarioEngine:
    """
    Evaluates multiple deals together, finding cross-scenario opportunities
    that single-deal qualification misses.
    """

    def __init__(self, subscriber: Subscriber):
        self.subscriber = subscriber
        self.scenarios: List[Scenario] = []
        self.routing = RoutingEngine()
        self.portfolio_analysis = {}
        self.combined_results = {}

    def add_scenario(self, data: Dict) -> Scenario:
        """Add a property/deal scenario"""
        scenario = Scenario(len(self.scenarios) + 1, data)
        self.scenarios.append(scenario)
        self._requalify_all()
        return scenario

    def remove_scenario(self, scenario_id: int):
        """Remove a scenario and requalify"""
        self.scenarios = [s for s in self.scenarios if s.id != scenario_id]
        self._requalify_all()

    def update_scenario(self, scenario_id: int, data: Dict):
        """Update a scenario and requalify"""
        for s in self.scenarios:
            if s.id == scenario_id:
                s.data = data
                break
        self._requalify_all()

    def _requalify_all(self):
        """Requalify all scenarios individually and combined"""
        # Step 1: Individual qualification
        for scenario in self.scenarios:
            result = self.routing.qualify_application(scenario.data, self.subscriber)
            scenario.individual_matches = result["direct_matches"] + result["overflow_matches"]

        # Step 2: Portfolio/combined analysis
        self._analyze_portfolio()

        # Step 3: Find upgrade opportunities
        self._find_upgrades()

    def _analyze_portfolio(self):
        """Analyze all scenarios together for portfolio-level opportunities"""
        if len(self.scenarios) < 1:
            return

        total_properties = len(self.scenarios)
        total_units = sum(s.units for s in self.scenarios)
        total_loan = sum(s.loan_amount for s in self.scenarios)
        total_value = sum(s.value for s in self.scenarios)
        total_noi = sum(s.noi for s in self.scenarios)
        total_rent = sum(s.monthly_rent for s in self.scenarios)

        investment_properties = [s for s in self.scenarios if s.occupancy == "investment"]
        commercial_properties = [s for s in self.scenarios if s.units >= 5 or s.property_type in ["office", "retail", "industrial", "mixed_use", "self_storage", "hotel"]]

        self.portfolio_analysis = {
            "total_properties": total_properties,
            "total_units": total_units,
            "total_loan_amount": total_loan,
            "total_value": total_value,
            "total_noi": total_noi,
            "total_monthly_rent": total_rent,
            "investment_count": len(investment_properties),
            "commercial_count": len(commercial_properties),
            "combined_ltv": (total_loan / total_value * 100) if total_value > 0 else 0,
            "combined_dscr": self._calc_combined_dscr(total_rent, total_loan),
            "portfolio_eligible": len(investment_properties) >= 5,
            "blanket_eligible": len(investment_properties) >= 2,
        }

        # Combined qualification results
        self.combined_results = {
            "individual": [
                {
                    "scenario_id": s.id,
                    "property": s.data.get("property", {}).get("address", f"Property {s.id}"),
                    "matches": len(s.individual_matches),
                    "best_match": s.individual_matches[0] if s.individual_matches else None,
                }
                for s in self.scenarios
            ],
            "portfolio_programs": self._get_portfolio_programs(),
            "cross_collateral_options": self._get_cross_collateral(),
            "upgrade_tips": [],
        }

    def _calc_combined_dscr(self, total_rent: float, total_loan: float) -> float:
        """Calculate combined DSCR across all properties"""
        if total_loan <= 0:
            return 0
        monthly_rate = 0.075 / 12
        n = 360
        monthly_payment = total_loan * (monthly_rate * (1 + monthly_rate)**n) / ((1 + monthly_rate)**n - 1)
        taxes_insurance = total_loan * 0.015 / 12  # rough estimate
        total_debt_service = monthly_payment + taxes_insurance
        return total_rent / total_debt_service if total_debt_service > 0 else 0

    def _get_portfolio_programs(self) -> List[Dict]:
        """Check which portfolio-level programs the combined scenarios qualify for"""
        programs = []
        pa = self.portfolio_analysis

        # Portfolio/Blanket loan
        if pa["investment_count"] >= 5:
            programs.append({
                "program": "Portfolio / Blanket Loan",
                "category": "investor",
                "product": "portfolio",
                "benefit": f"Combine all {pa['investment_count']} investment properties into ONE loan. One closing. One payment. Better terms than individual DSCR loans.",
                "total_loan": pa["total_loan_amount"],
                "combined_dscr": round(pa["combined_dscr"], 2),
            })

        # If 2-4 properties, suggest blanket for efficiency
        if 2 <= pa["investment_count"] < 5:
            programs.append({
                "program": "Blanket Loan (2-4 Properties)",
                "category": "investor",
                "product": "portfolio",
                "benefit": f"Combine your {pa['investment_count']} properties into a single blanket loan. Fewer closings, potential rate improvement.",
                "total_loan": pa["total_loan_amount"],
            })

        # Combined NOI might qualify for CMBS
        if pa["total_noi"] > 0 and pa["total_loan_amount"] >= 2000000:
            debt_yield = pa["total_noi"] / pa["total_loan_amount"] * 100 if pa["total_loan_amount"] > 0 else 0
            if debt_yield >= 8:
                programs.append({
                    "program": "CMBS / Conduit (Combined Portfolio)",
                    "category": "commercial",
                    "product": "cmbs",
                    "benefit": f"Your combined portfolio NOI of ${pa['total_noi']:,.0f} and loan of ${pa['total_loan_amount']:,.0f} qualifies for non-recourse CMBS financing. Debt yield: {debt_yield:.1f}%.",
                    "non_recourse": True,
                })

        # Agency multifamily if total units >= 5
        if pa["total_units"] >= 5:
            all_residential = all(s.property_type in ["sfr", "condo", "townhome", "2_4_unit", "multifamily"] for s in self.scenarios)
            if all_residential:
                programs.append({
                    "program": "Agency Multifamily (Combined Units)",
                    "category": "commercial",
                    "product": "agency_multifamily",
                    "benefit": f"Your combined {pa['total_units']} units across {pa['total_properties']} properties may qualify for agency (Fannie/Freddie) multifamily financing with non-recourse terms.",
                    "non_recourse": True,
                })

        return programs

    def _get_cross_collateral(self) -> List[Dict]:
        """Find cross-collateral opportunities"""
        options = []

        # If one property has high equity and another needs more leverage
        high_equity = [s for s in self.scenarios if s.value > 0 and (s.loan_amount / s.value) < 0.6]
        high_ltv = [s for s in self.scenarios if s.value > 0 and (s.loan_amount / s.value) > 0.75]

        if high_equity and high_ltv:
            equity_available = sum(s.value * 0.8 - s.loan_amount for s in high_equity if s.value * 0.8 > s.loan_amount)
            options.append({
                "strategy": "Cross-Collateral Leverage",
                "benefit": f"You have ${equity_available:,.0f} in excess equity across {len(high_equity)} properties. This equity can be used to reduce down payment requirements on your higher-leverage deals.",
                "properties_with_equity": [s.id for s in high_equity],
                "properties_needing_leverage": [s.id for s in high_ltv],
            })

        return options

    def _find_upgrades(self):
        """Find small changes that unlock better programs"""
        tips = []
        pa = self.portfolio_analysis

        # Tip: Add one more property to hit portfolio threshold
        if pa["investment_count"] == 4:
            tips.append({
                "type": "portfolio_threshold",
                "message": "You have 4 investment properties. Add ONE more and you qualify for a portfolio/blanket loan — one closing, one payment, potentially better rate than 5 individual DSCR loans.",
                "action": "Add 1 more investment property",
                "impact": "Unlocks portfolio loan program",
                "priority": "high",
            })

        # Tip: If a property has 4 units, building 5 unlocks agency
        for s in self.scenarios:
            if s.units == 4:
                tips.append({
                    "type": "unit_threshold",
                    "message": f"Property {s.id} has 4 units. If you build or acquire 5+ units instead, you unlock agency multifamily financing — non-recourse, lowest rates in CRE, up to 80% LTV, terms up to 35 years.",
                    "action": f"Increase Property {s.id} to 5+ units",
                    "impact": "Unlocks Fannie Mae / Freddie Mac agency financing",
                    "priority": "high",
                    "scenario_id": s.id,
                })

        # Tip: Combined loan amount close to CMBS threshold
        if pa["total_loan_amount"] >= 1500000 and pa["total_loan_amount"] < 2000000:
            gap = 2000000 - pa["total_loan_amount"]
            tips.append({
                "type": "cmbs_threshold",
                "message": f"Your combined portfolio is ${gap:,.0f} away from the $2M CMBS minimum. At $2M+, you unlock non-recourse CMBS conduit financing.",
                "action": f"Increase total loan amount by ${gap:,.0f}",
                "impact": "Unlocks non-recourse CMBS financing",
                "priority": "medium",
            })

        # Tip: DSCR improvement
        for s in self.scenarios:
            if s.monthly_rent > 0 and s.loan_amount > 0:
                dscr = self._calc_combined_dscr(s.monthly_rent, s.loan_amount)
                if 0.75 <= dscr < 1.0:
                    rent_needed = s.loan_amount * 0.075 / 12 * 1.0 * 1.2  # rough estimate for DSCR 1.0
                    rent_gap = rent_needed - s.monthly_rent
                    tips.append({
                        "type": "dscr_improvement",
                        "message": f"Property {s.id} has a DSCR of {dscr:.2f}. Increasing rent by ~${max(0, rent_gap):,.0f}/month would bring you to 1.0 DSCR, qualifying you for better rates and more lender options.",
                        "action": "Increase rent or decrease loan amount",
                        "impact": "Better rates, more lender options",
                        "priority": "medium",
                        "scenario_id": s.id,
                    })

                if 1.0 <= dscr < 1.25:
                    tips.append({
                        "type": "dscr_optimization",
                        "message": f"Property {s.id} has a DSCR of {dscr:.2f}. At 1.25+ DSCR, you qualify with most lenders at the best rates. Consider a larger down payment or higher rent.",
                        "action": "Target 1.25+ DSCR",
                        "impact": "Unlocks best-rate lenders",
                        "priority": "low",
                        "scenario_id": s.id,
                    })

        # Tip: SBA eligibility
        for s in self.scenarios:
            if s.occupancy == "owner_occupied" and s.loan_amount <= 5000000:
                if not any(m["product"] in ["sba_504", "sba_7a"] for m in s.individual_matches):
                    tips.append({
                        "type": "sba_eligible",
                        "message": f"Property {s.id} is owner-occupied — you may qualify for SBA 504 (90% LTV, below-market rate) or SBA 7(a). These are the best terms available for owner-occupied commercial.",
                        "action": "Confirm 51%+ owner-occupancy",
                        "impact": "Unlocks SBA 504 (90% LTV) or SBA 7(a)",
                        "priority": "high",
                        "scenario_id": s.id,
                    })

        # Tip: VA eligibility
        borrower = self.scenarios[0].data.get("borrower", {}) if self.scenarios else {}
        if borrower.get("is_veteran") and any(s.occupancy == "primary" for s in self.scenarios):
            for s in self.scenarios:
                if s.occupancy == "primary":
                    if not any(m["product"] == "va" for m in s.individual_matches):
                        tips.append({
                            "type": "va_eligible",
                            "message": f"You're a veteran and Property {s.id} is your primary residence. VA loans offer 0% down and no PMI — the best loan in America.",
                            "action": "Apply for VA financing",
                            "impact": "0% down, no PMI, best rates",
                            "priority": "high",
                            "scenario_id": s.id,
                        })

        # Tip: Construction-to-permanent savings
        construction_scenarios = [s for s in self.scenarios if s.purpose == "construction"]
        rental_scenarios = [s for s in self.scenarios if s.purpose in ["purchase", "refinance"] and s.occupancy == "investment"]
        if construction_scenarios and rental_scenarios:
            tips.append({
                "type": "c2p_opportunity",
                "message": "You have both construction and rental scenarios. Consider construction-to-permanent (Build2Rent) programs that roll your construction loan directly into DSCR permanent financing — one closing instead of two.",
                "action": "Use Build2Rent or Fix2Rent program",
                "impact": "Save on closing costs, streamline financing",
                "priority": "medium",
            })

        # Tip: Bridge-to-permanent strategy
        bridge_scenarios = [s for s in self.scenarios if s.purpose == "bridge"]
        if bridge_scenarios:
            for s in bridge_scenarios:
                tips.append({
                    "type": "bridge_exit",
                    "message": f"Property {s.id} is a bridge loan. Plan your exit: stabilize to 90%+ occupancy and 1.25+ DSCR, then refinance into agency permanent (lowest rates, non-recourse, up to 35 years).",
                    "action": "Plan bridge exit to permanent financing",
                    "impact": "Long-term non-recourse financing at best rates",
                    "priority": "medium",
                    "scenario_id": s.id,
                })

        # Store tips on combined results
        self.combined_results["upgrade_tips"] = tips

        # Also store on individual scenarios
        for tip in tips:
            sid = tip.get("scenario_id")
            if sid:
                for s in self.scenarios:
                    if s.id == sid:
                        s.upgrade_tips.append(tip)

    def get_full_report(self) -> Dict:
        """Generate the complete multi-scenario report"""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_scenarios": len(self.scenarios),
            "portfolio_analysis": self.portfolio_analysis,
            "individual_results": [
                {
                    "scenario_id": s.id,
                    "property": s.data.get("property", {}),
                    "matches": [
                        {"program": m["label"], "category": m["category_label"], "handled_by": m["handled_by"]}
                        for m in s.individual_matches
                    ],
                    "match_count": len(s.individual_matches),
                    "upgrade_tips": s.upgrade_tips,
                }
                for s in self.scenarios
            ],
            "portfolio_programs": self.combined_results.get("portfolio_programs", []),
            "cross_collateral": self.combined_results.get("cross_collateral_options", []),
            "upgrade_tips": self.combined_results.get("upgrade_tips", []),
            "summary": self._generate_summary(),
        }

    def _generate_summary(self) -> str:
        """Generate a human-readable summary"""
        pa = self.portfolio_analysis
        if not pa:
            return "No scenarios entered yet."

        lines = []
        lines.append(f"PORTFOLIO SUMMARY: {pa['total_properties']} properties, {pa['total_units']} total units")
        lines.append(f"Combined loan: ${pa['total_loan_amount']:,.0f} | Combined value: ${pa['total_value']:,.0f}")

        if pa.get("combined_dscr"):
            lines.append(f"Combined DSCR: {pa['combined_dscr']:.2f}")

        if pa.get("portfolio_eligible"):
            lines.append("PORTFOLIO LOAN ELIGIBLE — qualify for blanket financing")

        programs = self.combined_results.get("portfolio_programs", [])
        if programs:
            lines.append(f"\nPORTFOLIO-LEVEL PROGRAMS ({len(programs)}):")
            for p in programs:
                lines.append(f"  > {p['program']}: {p['benefit']}")

        tips = self.combined_results.get("upgrade_tips", [])
        high_tips = [t for t in tips if t.get("priority") == "high"]
        if high_tips:
            lines.append(f"\nHIGH-PRIORITY OPPORTUNITIES ({len(high_tips)}):")
            for t in high_tips:
                lines.append(f"  * {t['message']}")

        return "\n".join(lines)


# ================================================================
# DEMO / TEST
# ================================================================

if __name__ == "__main__":
    # Create Click Click Close as enterprise subscriber
    ccc = Subscriber("CCC-001", "Click Click Close", "enterprise")
    engine = MultiScenarioEngine(ccc)

    # Scenario 1: DSCR rental property
    s1 = engine.add_scenario({
        "borrower": {"credit_score": 720, "is_veteran": True, "has_ssn": True, "citizenship": "us_citizen"},
        "property": {"type": "sfr", "units": 1, "loan_amount": 280000, "value": 350000, "occupancy": "investment", "address": "123 Main St, Dallas TX"},
        "financials": {"monthly_rent": 2200, "noi": 0},
        "loan": {"purpose": "purchase"},
        "income": {"is_self_employed": False},
        "assets": {},
    })
    print(f"Added Scenario 1: {len(s1.individual_matches)} individual matches")

    # Scenario 2: Another rental
    s2 = engine.add_scenario({
        "borrower": {"credit_score": 720, "is_veteran": True, "has_ssn": True, "citizenship": "us_citizen"},
        "property": {"type": "sfr", "units": 1, "loan_amount": 200000, "value": 250000, "occupancy": "investment", "address": "456 Oak Ave, Houston TX"},
        "financials": {"monthly_rent": 1800, "noi": 0},
        "loan": {"purpose": "purchase"},
        "income": {"is_self_employed": False},
        "assets": {},
    })
    print(f"Added Scenario 2: {len(s2.individual_matches)} individual matches")

    # Scenario 3: A 4-unit building
    s3 = engine.add_scenario({
        "borrower": {"credit_score": 720, "is_veteran": True, "has_ssn": True, "citizenship": "us_citizen"},
        "property": {"type": "2_4_unit", "units": 4, "loan_amount": 500000, "value": 650000, "occupancy": "investment", "address": "789 Elm Blvd, Austin TX"},
        "financials": {"monthly_rent": 4800, "noi": 0},
        "loan": {"purpose": "purchase"},
        "income": {"is_self_employed": False},
        "assets": {},
    })
    print(f"Added Scenario 3: {len(s3.individual_matches)} individual matches")

    # Scenario 4: Another rental
    s4 = engine.add_scenario({
        "borrower": {"credit_score": 720, "is_veteran": True, "has_ssn": True, "citizenship": "us_citizen"},
        "property": {"type": "sfr", "units": 1, "loan_amount": 180000, "value": 230000, "occupancy": "investment", "address": "321 Pine Dr, San Antonio TX"},
        "financials": {"monthly_rent": 1600, "noi": 0},
        "loan": {"purpose": "purchase"},
        "income": {"is_self_employed": False},
        "assets": {},
    })
    print(f"Added Scenario 4: {len(s4.individual_matches)} individual matches")

    # Get the full report
    report = engine.get_full_report()

    print("\n" + "=" * 60)
    print(report["summary"])
    print("=" * 60)

    # Show upgrade tips
    print(f"\nAll Upgrade Tips ({len(report['upgrade_tips'])}):")
    for tip in report["upgrade_tips"]:
        priority = tip.get("priority", "").upper()
        print(f"  [{priority}] {tip['message']}")
        print(f"         Action: {tip['action']}")
        print(f"         Impact: {tip['impact']}")
        print()
