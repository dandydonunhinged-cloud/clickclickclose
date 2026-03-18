"""
Click Click Close — SaaS Configuration Engine
Custom Configured Secured Loan Collection System

Feature flags, tier management, product routing, overflow matching.
The platform never says no. Every application finds a home.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import sqlite3
import hashlib
import secrets

# ================================================================
# PRODUCT DEFINITIONS
# ================================================================

PRODUCTS = {
    "residential": {
        "label": "Home Loans",
        "products": {
            "conventional": {"label": "Conventional", "min_credit": 620, "min_down": 3, "max_ltv": 97, "max_loan": 766550},
            "fha": {"label": "FHA", "min_credit": 580, "min_down": 3.5, "max_ltv": 96.5, "max_loan": 498257},
            "va": {"label": "VA", "min_credit": 580, "min_down": 0, "max_ltv": 100, "max_loan": None, "requires": "veteran"},
            "usda": {"label": "USDA", "min_credit": 640, "min_down": 0, "max_ltv": 100, "max_loan": None, "requires": "rural"},
            "jumbo": {"label": "Jumbo", "min_credit": 700, "min_down": 10, "max_ltv": 90, "min_loan": 766551},
            "refinance": {"label": "Refinance", "min_credit": 620, "subtypes": ["rate_term", "fha_streamline", "va_irrrl", "usda_streamline"]},
            "cashout": {"label": "Cash-Out / HELOC", "min_credit": 620, "max_ltv": 80, "subtypes": ["cashout_refi", "home_equity", "heloc"]},
            "first_time": {"label": "First-Time Buyer", "min_credit": 580, "min_down": 3, "includes_dpa": True},
        }
    },
    "investor": {
        "label": "Investment Property",
        "products": {
            "dscr": {"label": "DSCR / Rental", "min_credit": 620, "min_dscr": 0.75, "max_ltv": 85, "no_income": True},
            "fix_flip": {"label": "Fix & Flip", "min_credit": 620, "max_ltc": 95, "max_arv": 75, "term_months": 24},
            "bridge": {"label": "Bridge", "min_credit": 620, "max_ltv": 90, "term_months": 18},
            "construction": {"label": "Ground-Up Construction", "min_credit": 650, "max_ltc": 85, "term_months": 24},
            "str": {"label": "Short-Term Rental / Airbnb", "min_credit": 620, "max_ltv": 80, "uses_str_income": True},
            "portfolio": {"label": "Portfolio / Blanket", "min_credit": 660, "min_properties": 5},
            "construction_perm": {"label": "Construction-to-Permanent", "min_credit": 650},
        }
    },
    "commercial": {
        "label": "Commercial Real Estate",
        "products": {
            "agency_multifamily": {"label": "Agency Multifamily", "min_units": 5, "min_occupancy": 90, "max_ltv": 80, "non_recourse": True, "min_loan": 750000},
            "cmbs": {"label": "CMBS / Conduit", "min_loan": 2000000, "max_ltv": 75, "non_recourse": True},
            "sba_504": {"label": "SBA 504", "max_ltv": 90, "requires": "owner_occupied_51", "structure": "50_40_10"},
            "sba_7a": {"label": "SBA 7(a)", "max_loan": 5000000, "requires": "owner_occupied_51"},
            "cre_bridge": {"label": "CRE Bridge", "min_loan": 1000000, "max_ltc": 80, "term_months": 36},
            "cre_construction": {"label": "CRE Construction", "min_loan": 2000000, "max_ltc": 75, "term_months": 24},
            "mezzanine": {"label": "Mezzanine / Pref Equity", "min_loan": 1000000, "rate_range": "10-18%", "total_leverage": 90},
            "hud_multifamily": {"label": "HUD / FHA Multifamily", "max_ltv": 85, "max_term_years": 40, "non_recourse": True},
            "hud_232": {"label": "HUD 232 Senior Housing", "max_ltv": 85, "max_term_years": 35, "non_recourse": True},
            "usda_bi": {"label": "USDA B&I", "requires": "rural_50k"},
        }
    },
    "non_qm": {
        "label": "Non-QM / Alternative",
        "products": {
            "bank_statement": {"label": "Bank Statement", "min_credit": 620, "max_ltv": 90, "months_required": [12, 24]},
            "foreign_national": {"label": "Foreign National", "max_ltv": 75, "no_ssn": True, "no_us_credit": True},
            "asset_depletion": {"label": "Asset Depletion", "no_income": True, "no_employment": True},
            "itin": {"label": "ITIN", "no_ssn": True, "alternative_credit": True},
            "pl_loan": {"label": "P&L Loan", "requires": "cpa_pl", "min_credit": 620},
            "1099_income": {"label": "1099 Income", "min_credit": 620},
        }
    },
    "specialty": {
        "label": "Specialty / Niche",
        "products": {
            "mobile_home_park": {"label": "Mobile Home Park", "min_loan": 1500000},
            "self_storage": {"label": "Self-Storage", "min_loan": 500000},
            "hospitality": {"label": "Hotel / Hospitality", "min_loan": 1000000},
            "senior_housing": {"label": "Senior Housing / Healthcare", "min_loan": 1000000},
            "medical_office": {"label": "Medical Office", "min_loan": 500000},
            "church": {"label": "Church / Religious", "min_loan": 500000},
            "gas_station_carwash": {"label": "Gas Station / Car Wash", "min_loan": 250000},
            "cannabis": {"label": "Cannabis / Dispensary", "max_ltv": 65, "hard_money_only": True},
            "data_center": {"label": "Data Center", "min_loan": 5000000},
            "student_housing": {"label": "Student Housing", "min_loan": 1000000},
        }
    }
}

# ================================================================
# TIER DEFINITIONS
# ================================================================

TIERS = {
    "solo_residential": {
        "label": "Solo Broker — Residential",
        "price": 199,
        "max_loan_officers": 1,
        "categories_enabled": ["residential"],
        "smart_contracts": False,
        "white_label": False,
        "api_access": False,
        "overflow_routing": True,  # Always on — platform never says no
    },
    "solo_investor": {
        "label": "Solo Broker — Investor",
        "price": 199,
        "max_loan_officers": 1,
        "categories_enabled": ["investor"],
        "smart_contracts": False,
        "white_label": False,
        "api_access": False,
        "overflow_routing": True,
    },
    "solo_commercial": {
        "label": "Solo Broker — Commercial",
        "price": 299,
        "max_loan_officers": 1,
        "categories_enabled": ["commercial"],
        "smart_contracts": False,
        "white_label": False,
        "api_access": False,
        "overflow_routing": True,
    },
    "brokerage": {
        "label": "Brokerage",
        "price": 499,
        "max_loan_officers": 25,
        "categories_enabled": ["residential", "investor", "non_qm"],  # toggleable
        "categories_available": ["residential", "investor", "commercial", "non_qm", "specialty"],
        "smart_contracts": True,
        "white_label": False,
        "api_access": True,
        "overflow_routing": True,
    },
    "enterprise": {
        "label": "Enterprise",
        "price": 999,
        "max_loan_officers": None,  # unlimited
        "categories_enabled": ["residential", "investor", "commercial", "non_qm", "specialty"],
        "smart_contracts": True,
        "white_label": True,
        "api_access": True,
        "overflow_routing": True,
        "compliance_reporting": True,
        "custom_lender_matrix": True,
    }
}


# ================================================================
# SUBSCRIBER MANAGEMENT
# ================================================================

class Subscriber:
    """A broker/company using the Click Click Close SaaS platform"""

    def __init__(self, subscriber_id: str, name: str, tier: str, db_path: str = "C:/DandyDon/investor_site/saas/ccc_saas.db"):
        self.subscriber_id = subscriber_id
        self.name = name
        self.tier = tier
        self.tier_config = TIERS.get(tier, {})
        self.db_path = db_path

        # Product toggles — start with tier defaults
        self.enabled_categories = set(self.tier_config.get("categories_enabled", []))
        self.enabled_products = {}  # category -> set of product keys
        self.disabled_products = {}  # explicitly disabled within enabled categories

        # Initialize all products in enabled categories as ON
        for cat in self.enabled_categories:
            if cat in PRODUCTS:
                self.enabled_products[cat] = set(PRODUCTS[cat]["products"].keys())

    def enable_category(self, category: str) -> bool:
        """Turn on a category if allowed by tier"""
        available = self.tier_config.get("categories_available", self.tier_config.get("categories_enabled", []))
        if category in available:
            self.enabled_categories.add(category)
            if category in PRODUCTS:
                self.enabled_products[category] = set(PRODUCTS[category]["products"].keys())
            return True
        return False

    def disable_category(self, category: str):
        """Turn off a category"""
        self.enabled_categories.discard(category)
        self.enabled_products.pop(category, None)

    def enable_product(self, category: str, product: str) -> bool:
        """Turn on a specific product within a category"""
        if category in self.enabled_categories and product in PRODUCTS.get(category, {}).get("products", {}):
            if category not in self.enabled_products:
                self.enabled_products[category] = set()
            self.enabled_products[category].add(product)
            if category in self.disabled_products:
                self.disabled_products[category].discard(product)
            return True
        return False

    def disable_product(self, category: str, product: str):
        """Turn off a specific product"""
        if category in self.enabled_products:
            self.enabled_products[category].discard(product)
            if category not in self.disabled_products:
                self.disabled_products[category] = set()
            self.disabled_products[category].add(product)

    def can_handle(self, category: str, product: str) -> bool:
        """Check if this subscriber can handle a specific product"""
        if category not in self.enabled_categories:
            return False
        if category not in self.enabled_products:
            return False
        return product in self.enabled_products[category]

    def get_enabled_products(self) -> Dict[str, List[str]]:
        """Get all enabled products grouped by category"""
        result = {}
        for cat in self.enabled_categories:
            if cat in self.enabled_products and self.enabled_products[cat]:
                result[cat] = sorted(self.enabled_products[cat])
        return result

    def get_form_config(self) -> Dict:
        """Generate the form configuration for this subscriber's application"""
        config = {
            "subscriber_id": self.subscriber_id,
            "subscriber_name": self.name,
            "tier": self.tier,
            "categories": {},
            "smart_contracts": self.tier_config.get("smart_contracts", False),
            "white_label": self.tier_config.get("white_label", False),
        }

        for cat in self.enabled_categories:
            if cat in self.enabled_products and self.enabled_products[cat]:
                cat_config = {
                    "label": PRODUCTS[cat]["label"],
                    "products": {}
                }
                for prod_key in self.enabled_products[cat]:
                    prod_def = PRODUCTS[cat]["products"].get(prod_key, {})
                    cat_config["products"][prod_key] = {
                        "label": prod_def.get("label", prod_key),
                        **{k: v for k, v in prod_def.items() if k != "label"}
                    }
                config["categories"][cat] = cat_config

        return config


# ================================================================
# APPLICATION ROUTING ENGINE
# ================================================================

class RoutingEngine:
    """Routes loan applications to the right product and handles overflow"""

    def __init__(self, db_path: str = "C:/DandyDon/investor_site/saas/ccc_saas.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the routing database"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            subscriber_id TEXT NOT NULL,
            borrower_hash TEXT NOT NULL,
            category TEXT,
            product TEXT,
            status TEXT DEFAULT 'submitted',
            routed_to TEXT,
            overflow BOOLEAN DEFAULT FALSE,
            overflow_from TEXT,
            qualification_result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS subscribers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tier TEXT NOT NULL,
            config TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS overflow_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            application_id TEXT NOT NULL,
            from_subscriber TEXT NOT NULL,
            to_subscriber TEXT NOT NULL,
            category TEXT NOT NULL,
            product TEXT NOT NULL,
            referral_fee REAL,
            status TEXT DEFAULT 'pending'
        )''')

        conn.commit()
        conn.close()

    def qualify_application(self, application: Dict, subscriber: Subscriber) -> Dict:
        """
        Qualify an application against all available products.
        Returns matching products with estimated terms.
        """
        matches = []
        overflow_needed = []

        borrower = application.get("borrower", {})
        property_info = application.get("property", {})
        income = application.get("income", {})
        assets = application.get("assets", {})

        credit_score = borrower.get("credit_score", 0)
        down_payment_pct = property_info.get("down_payment_pct", 0)
        loan_amount = property_info.get("loan_amount", 0)
        property_type = property_info.get("property_type", "")
        occupancy = property_info.get("occupancy", "")
        is_veteran = borrower.get("is_veteran", False)
        is_self_employed = income.get("is_self_employed", False)
        has_ssn = borrower.get("has_ssn", True)
        citizenship = borrower.get("citizenship", "us_citizen")

        # Check every product in every category
        for cat_key, cat_def in PRODUCTS.items():
            for prod_key, prod_def in cat_def["products"].items():

                # Check minimum credit
                min_credit = prod_def.get("min_credit", 0)
                if credit_score and credit_score < min_credit:
                    continue

                # Check loan amount limits
                max_loan = prod_def.get("max_loan")
                min_loan = prod_def.get("min_loan", 0)
                if max_loan and loan_amount > max_loan:
                    continue
                if min_loan and loan_amount < min_loan:
                    continue

                # Check special requirements
                requires = prod_def.get("requires", "")
                if requires == "veteran" and not is_veteran:
                    continue
                if requires == "rural" and not property_info.get("is_rural", False):
                    continue
                if requires == "owner_occupied_51" and occupancy != "owner_occupied":
                    continue

                # Check SSN requirements
                if prod_def.get("no_ssn") and has_ssn:
                    pass  # Product is for no-SSN but borrower has one — still eligible
                if not prod_def.get("no_ssn", True) and not has_ssn:
                    continue  # Product requires SSN but borrower doesn't have one

                # Foreign national check
                if citizenship == "foreign_national":
                    if prod_key not in ["foreign_national", "dscr"]:
                        if not prod_def.get("no_us_credit", False):
                            continue

                # Build match
                match = {
                    "category": cat_key,
                    "product": prod_key,
                    "label": prod_def.get("label", prod_key),
                    "category_label": cat_def["label"],
                    "max_ltv": prod_def.get("max_ltv", prod_def.get("max_ltc", None)),
                    "non_recourse": prod_def.get("non_recourse", False),
                    "no_income": prod_def.get("no_income", False),
                }

                # Can this subscriber handle it?
                if subscriber.can_handle(cat_key, prod_key):
                    match["handled_by"] = "direct"
                    matches.append(match)
                else:
                    match["handled_by"] = "overflow"
                    overflow_needed.append(match)

        return {
            "direct_matches": matches,
            "overflow_matches": overflow_needed,
            "total_options": len(matches) + len(overflow_needed),
            "qualified": len(matches) + len(overflow_needed) > 0,
        }

    def route_overflow(self, application_id: str, category: str, product: str, from_subscriber: str) -> Optional[str]:
        """Find a subscriber who can handle an overflow application"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Find active subscribers who handle this product
        c.execute("SELECT id, config FROM subscribers WHERE active = TRUE AND id != ?", (from_subscriber,))
        rows = c.fetchall()

        for row in rows:
            sub_id, config_json = row
            try:
                config = json.loads(config_json) if config_json else {}
                enabled = config.get("enabled_products", {})
                if category in enabled and product in enabled.get(category, []):
                    # Log the overflow
                    c.execute('''INSERT INTO overflow_log
                        (timestamp, application_id, from_subscriber, to_subscriber, category, product)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                        (datetime.now().isoformat(), application_id, from_subscriber, sub_id, category, product))
                    conn.commit()
                    conn.close()
                    return sub_id
            except:
                continue

        conn.close()
        return None


# ================================================================
# DOCUMENT COLLECTION
# ================================================================

DOCUMENT_REQUIREMENTS = {
    "w2_employed": {
        "label": "W-2 Employed",
        "required": [
            {"id": "w2_2yr", "label": "W-2s (Last 2 Years)", "accept": ".pdf,.jpg,.png"},
            {"id": "tax_returns_2yr", "label": "Tax Returns (Last 2 Years)", "accept": ".pdf"},
            {"id": "pay_stubs_30d", "label": "Pay Stubs (Last 30 Days)", "accept": ".pdf,.jpg,.png"},
            {"id": "bank_statements_2mo", "label": "Bank Statements (Last 2 Months)", "accept": ".pdf"},
            {"id": "photo_id", "label": "Photo ID", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "self_employed": {
        "label": "Self-Employed",
        "required": [
            {"id": "personal_tax_2yr", "label": "Personal Tax Returns (Last 2 Years)", "accept": ".pdf"},
            {"id": "business_tax_2yr", "label": "Business Tax Returns (Last 2 Years)", "accept": ".pdf"},
            {"id": "ytd_pl", "label": "Year-to-Date Profit & Loss", "accept": ".pdf,.xlsx"},
            {"id": "bank_statements_2mo", "label": "Bank Statements (Last 2 Months)", "accept": ".pdf"},
            {"id": "business_license", "label": "Business License", "accept": ".pdf,.jpg,.png"},
            {"id": "photo_id", "label": "Photo ID", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "bank_statement": {
        "label": "Bank Statement (Non-QM)",
        "required": [
            {"id": "bank_statements_12_24", "label": "Bank Statements (12 or 24 Months)", "accept": ".pdf"},
            {"id": "photo_id", "label": "Photo ID", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "dscr": {
        "label": "DSCR / Investor",
        "required": [
            {"id": "lease_agreement", "label": "Property Lease or Rent Schedule", "accept": ".pdf"},
            {"id": "entity_docs", "label": "Entity Documents (if LLC)", "accept": ".pdf", "optional": True},
            {"id": "photo_id", "label": "Photo ID", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "foreign_national": {
        "label": "Foreign National",
        "required": [
            {"id": "passport", "label": "Passport", "accept": ".pdf,.jpg,.png"},
            {"id": "foreign_credit", "label": "Foreign Credit References or Bank Statements", "accept": ".pdf"},
            {"id": "entity_docs", "label": "Entity Documents (if applicable)", "accept": ".pdf", "optional": True},
        ]
    },
    "va": {
        "label": "VA (Additional)",
        "required": [
            {"id": "dd214_coe", "label": "DD-214 or Certificate of Eligibility", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "itin": {
        "label": "ITIN",
        "required": [
            {"id": "itin_letter", "label": "ITIN Assignment Letter", "accept": ".pdf,.jpg,.png"},
            {"id": "itin_tax_returns", "label": "ITIN Tax Returns (if available)", "accept": ".pdf", "optional": True},
            {"id": "bank_statements_12", "label": "Bank Statements (12 Months)", "accept": ".pdf"},
            {"id": "alt_credit", "label": "Alternative Credit (Rent, Utilities, Phone)", "accept": ".pdf,.jpg,.png"},
            {"id": "photo_id", "label": "Photo ID (Passport or Matricula)", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "asset_depletion": {
        "label": "Asset Depletion",
        "required": [
            {"id": "asset_statements", "label": "Investment/Bank/Retirement Statements (Last 2 Months)", "accept": ".pdf"},
            {"id": "photo_id", "label": "Photo ID", "accept": ".pdf,.jpg,.png"},
        ]
    },
    "commercial": {
        "label": "Commercial",
        "required": [
            {"id": "t12_financials", "label": "Trailing 12-Month Financials (T-12)", "accept": ".pdf,.xlsx"},
            {"id": "rent_roll", "label": "Current Rent Roll", "accept": ".pdf,.xlsx"},
            {"id": "sponsor_financials", "label": "Sponsor Financial Statement", "accept": ".pdf"},
            {"id": "entity_docs", "label": "Entity/Operating Agreement", "accept": ".pdf"},
            {"id": "property_photos", "label": "Property Photos", "accept": ".jpg,.png,.pdf", "optional": True},
            {"id": "business_plan", "label": "Business Plan (Value-Add/Construction)", "accept": ".pdf", "optional": True},
        ]
    }
}

def get_required_documents(income_type: str, product: str, is_veteran: bool = False) -> List[Dict]:
    """Get the document checklist based on borrower profile and product"""
    docs = []

    # Base docs by income type
    if income_type in DOCUMENT_REQUIREMENTS:
        docs.extend(DOCUMENT_REQUIREMENTS[income_type]["required"])

    # Product-specific additions
    if product in DOCUMENT_REQUIREMENTS:
        for doc in DOCUMENT_REQUIREMENTS[product]["required"]:
            if doc["id"] not in [d["id"] for d in docs]:
                docs.append(doc)

    # VA addition
    if is_veteran and product != "va":
        for doc in DOCUMENT_REQUIREMENTS["va"]["required"]:
            if doc["id"] not in [d["id"] for d in docs]:
                docs.append(doc)

    return docs


# ================================================================
# APPLICATION ID GENERATION
# ================================================================

def generate_application_id() -> str:
    """Generate a unique application ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_part = secrets.token_hex(4).upper()
    return f"CCC-{timestamp}-{random_part}"


def hash_borrower_data(ssn: str = "", name: str = "", dob: str = "") -> str:
    """Hash borrower PII for storage — we never store raw PII"""
    data = f"{ssn}:{name}:{dob}"
    return hashlib.sha256(data.encode()).hexdigest()


# ================================================================
# DEMO / TEST
# ================================================================

if __name__ == "__main__":
    # Create a demo subscriber — Click Click Close itself (Enterprise, everything ON)
    ccc = Subscriber(
        subscriber_id="CCC-001",
        name="Click Click Close",
        tier="enterprise"
    )

    print(f"Subscriber: {ccc.name}")
    print(f"Tier: {ccc.tier}")
    print(f"Enabled Products:")
    for cat, products in ccc.get_enabled_products().items():
        print(f"  {PRODUCTS[cat]['label']}:")
        for p in products:
            print(f"    - {PRODUCTS[cat]['products'][p]['label']}")

    print(f"\nForm Config Keys: {list(ccc.get_form_config()['categories'].keys())}")

    # Test a solo residential broker
    solo = Subscriber(
        subscriber_id="BROKER-001",
        name="Jane's Home Loans",
        tier="solo_residential"
    )

    print(f"\n--- Solo Broker: {solo.name} ---")
    print(f"Can handle conventional? {solo.can_handle('residential', 'conventional')}")
    print(f"Can handle DSCR? {solo.can_handle('investor', 'dscr')}")
    print(f"Can handle CMBS? {solo.can_handle('commercial', 'cmbs')}")

    # Test qualification
    engine = RoutingEngine()
    test_app = {
        "borrower": {"credit_score": 720, "is_veteran": False, "has_ssn": True, "citizenship": "us_citizen"},
        "property": {"loan_amount": 350000, "down_payment_pct": 10, "property_type": "sfr", "occupancy": "primary"},
        "income": {"is_self_employed": False},
        "assets": {}
    }

    result = engine.qualify_application(test_app, solo)
    print(f"\nQualification Result:")
    print(f"  Direct matches: {len(result['direct_matches'])}")
    for m in result['direct_matches']:
        print(f"    - {m['category_label']}: {m['label']}")
    print(f"  Overflow matches: {len(result['overflow_matches'])}")
    for m in result['overflow_matches']:
        print(f"    - {m['category_label']}: {m['label']} (would route to another broker)")
    print(f"  Total options: {result['total_options']}")

    # Test document requirements
    print(f"\nDocuments for W-2 borrower, conventional:")
    for doc in get_required_documents("w2_employed", "conventional"):
        optional = " (optional)" if doc.get("optional") else ""
        print(f"  - {doc['label']}{optional}")

    print(f"\nDocuments for DSCR investor:")
    for doc in get_required_documents("dscr", "dscr"):
        optional = " (optional)" if doc.get("optional") else ""
        print(f"  - {doc['label']}{optional}")

    print(f"\nApplication ID: {generate_application_id()}")
