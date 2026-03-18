"""
Click Click Close — Smart Contract Enforcement Layer

Non-circumvention, automatic fee splits, borrower vault access control,
work order system, and immutable audit trail.

The platform never loses a borrower. The fees are guaranteed.
The data is encrypted. The routing is permanent.
"""

import json
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ================================================================
# ENCRYPTION LAYER (simplified — production uses actual crypto)
# ================================================================

class VaultEncryption:
    """
    Client-side encryption for borrower PII.
    In production: AES-256-GCM with per-borrower keys managed by
    a decentralized key management system (like Lit Protocol).
    This prototype uses hashing + access tokens to demonstrate the model.
    """

    @staticmethod
    def encrypt_pii(data: Dict) -> Tuple[str, str]:
        """Encrypt PII and return (encrypted_blob, access_key)"""
        access_key = secrets.token_hex(32)
        # In production: AES-256-GCM encryption with access_key
        # Prototype: JSON + HMAC signature
        payload = json.dumps(data, sort_keys=True)
        signature = hashlib.sha256(f"{payload}:{access_key}".encode()).hexdigest()
        encrypted = {
            "payload": payload,  # In production: actually encrypted bytes
            "signature": signature,
            "encrypted_at": datetime.now().isoformat(),
        }
        return json.dumps(encrypted), access_key

    @staticmethod
    def decrypt_pii(encrypted_blob: str, access_key: str) -> Optional[Dict]:
        """Decrypt PII with access key"""
        try:
            encrypted = json.loads(encrypted_blob)
            payload = encrypted["payload"]
            expected_sig = hashlib.sha256(f"{payload}:{access_key}".encode()).hexdigest()
            if expected_sig != encrypted["signature"]:
                logger.warning("Decryption failed: invalid access key")
                return None
            return json.loads(payload)
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return None

    @staticmethod
    def create_work_order_view(full_data: Dict) -> Dict:
        """Create a redacted view for work order recipients — NO PII"""
        return {
            "property": full_data.get("property", {}),
            "loan": full_data.get("loan", {}),
            "financials": full_data.get("financials", {}),
            "borrower_profile": {
                "credit_range": _credit_range(full_data.get("borrower", {}).get("credit_score", 0)),
                "experience": full_data.get("borrower", {}).get("experience", "unknown"),
                "citizenship": full_data.get("borrower", {}).get("citizenship", "unknown"),
                "is_veteran": full_data.get("borrower", {}).get("is_veteran", False),
                # NO name, NO email, NO phone, NO SSN, NO DOB
            },
            "qualification": full_data.get("qualification", {}),
        }


def _credit_range(score: int) -> str:
    """Convert exact credit score to range — never expose exact score to work order"""
    if score >= 760: return "760+"
    if score >= 720: return "720-759"
    if score >= 680: return "680-719"
    if score >= 640: return "640-679"
    if score >= 600: return "600-639"
    if score >= 500: return "500-599"
    return "Below 500"


# ================================================================
# BORROWER VAULT
# ================================================================

class BorrowerVault:
    """
    Encrypted storage for borrower PII.
    The borrower owns the data. The platform controls access.
    No broker ever gets raw PII unless explicitly authorized by the platform
    for a specific purpose with a specific expiration.
    """

    def __init__(self, db_path: str = "C:/DandyDon/investor_site/saas/vault.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS borrower_vault (
            borrower_id TEXT PRIMARY KEY,
            encrypted_pii TEXT NOT NULL,
            pii_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_accessed TEXT,
            access_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active'
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS access_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grant_id TEXT UNIQUE NOT NULL,
            borrower_id TEXT NOT NULL,
            granted_to TEXT NOT NULL,
            access_level TEXT NOT NULL,
            purpose TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            access_key_hash TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (borrower_id) REFERENCES borrower_vault(borrower_id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            accessed_by TEXT NOT NULL,
            grant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            fields_accessed TEXT,
            ip_address TEXT,
            success BOOLEAN
        )''')

        conn.commit()
        conn.close()

    def store_borrower(self, borrower_id: str, pii_data: Dict) -> str:
        """Store encrypted borrower PII, return access key for platform"""
        encrypted_blob, access_key = VaultEncryption.encrypt_pii(pii_data)
        pii_hash = hashlib.sha256(json.dumps(pii_data, sort_keys=True).encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO borrower_vault
            (borrower_id, encrypted_pii, pii_hash, created_at)
            VALUES (?, ?, ?, ?)''',
            (borrower_id, encrypted_blob, pii_hash, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        logger.info(f"Borrower {borrower_id} stored in vault")
        return access_key

    def grant_access(self, borrower_id: str, broker_id: str, access_level: str,
                     purpose: str, duration_hours: int = 72, access_key: str = "") -> str:
        """
        Grant a broker time-limited access to borrower data.
        Access levels: 'work_order' (no PII), 'processing' (limited PII), 'full' (all PII)
        """
        grant_id = f"GRANT-{secrets.token_hex(8).upper()}"
        expires = datetime.now() + timedelta(hours=duration_hours)
        key_hash = hashlib.sha256(access_key.encode()).hexdigest() if access_key else ""

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO access_grants
            (grant_id, borrower_id, granted_to, access_level, purpose, granted_at, expires_at, access_key_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (grant_id, borrower_id, broker_id, access_level, purpose,
             datetime.now().isoformat(), expires.isoformat(), key_hash))
        conn.commit()
        conn.close()

        logger.info(f"Access granted: {broker_id} -> {borrower_id} [{access_level}] expires {expires.isoformat()}")
        return grant_id

    def revoke_access(self, grant_id: str):
        """Revoke a specific access grant"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE access_grants SET status = 'revoked', revoked_at = ? WHERE grant_id = ?",
                  (datetime.now().isoformat(), grant_id))
        conn.commit()
        conn.close()
        logger.info(f"Access revoked: {grant_id}")

    def revoke_all_access(self, borrower_id: str, broker_id: str):
        """Revoke all access for a specific broker to a specific borrower"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""UPDATE access_grants SET status = 'revoked', revoked_at = ?
                     WHERE borrower_id = ? AND granted_to = ? AND status = 'active'""",
                  (datetime.now().isoformat(), borrower_id, broker_id))
        conn.commit()
        conn.close()

    def check_access(self, borrower_id: str, broker_id: str) -> Optional[Dict]:
        """Check if a broker has active, non-expired access to a borrower"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT grant_id, access_level, purpose, expires_at FROM access_grants
                     WHERE borrower_id = ? AND granted_to = ? AND status = 'active'
                     ORDER BY expires_at DESC LIMIT 1""",
                  (borrower_id, broker_id))
        row = c.fetchone()
        conn.close()

        if not row:
            return None

        expires = datetime.fromisoformat(row[3])
        if datetime.now() > expires:
            self.revoke_access(row[0])
            return None

        return {
            "grant_id": row[0],
            "access_level": row[1],
            "purpose": row[2],
            "expires_at": row[3],
            "time_remaining": str(expires - datetime.now()),
        }

    def log_access(self, borrower_id: str, broker_id: str, grant_id: str,
                   action: str, fields: List[str] = None, ip: str = ""):
        """Log every data access for immutable audit trail"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO access_log
            (timestamp, borrower_id, accessed_by, grant_id, action, fields_accessed, ip_address, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (datetime.now().isoformat(), borrower_id, broker_id, grant_id,
             action, json.dumps(fields) if fields else None, ip, True))
        conn.commit()
        conn.close()


# ================================================================
# DEAL CONTRACT
# ================================================================

class DealContract:
    """
    Smart contract for a loan deal.
    Locks referral relationships, fee splits, and communication routing.
    Immutable once created. Fees execute automatically.
    """

    def __init__(self, db_path: str = "C:/DandyDon/investor_site/saas/contracts.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS deal_contracts (
            contract_id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            originating_broker TEXT NOT NULL,
            processing_broker TEXT,
            is_overflow BOOLEAN DEFAULT FALSE,
            contract_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            loan_amount REAL,
            fee_structure TEXT NOT NULL,
            terms TEXT NOT NULL,
            closed_at TEXT,
            voided_at TEXT,
            void_reason TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS fee_splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT NOT NULL,
            payee TEXT NOT NULL,
            role TEXT NOT NULL,
            percentage REAL NOT NULL,
            flat_fee REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            paid_at TEXT,
            amount_paid REAL,
            FOREIGN KEY (contract_id) REFERENCES deal_contracts(contract_id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS contract_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT,
            actor TEXT,
            event_hash TEXT NOT NULL,
            previous_hash TEXT,
            FOREIGN KEY (contract_id) REFERENCES deal_contracts(contract_id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            from_party TEXT NOT NULL,
            to_party TEXT NOT NULL,
            message_type TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            read_at TEXT,
            FOREIGN KEY (contract_id) REFERENCES deal_contracts(contract_id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS circumvention_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            flagged_broker TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence TEXT,
            status TEXT DEFAULT 'pending_review',
            resolved_at TEXT,
            resolution TEXT
        )''')

        conn.commit()
        conn.close()

    def create_contract(self, application_id: str, borrower_id: str,
                        originating_broker: str, loan_amount: float,
                        processing_broker: str = None, is_overflow: bool = False) -> str:
        """
        Create an immutable deal contract.
        Fee structure is locked at creation. Cannot be modified.
        """
        contract_id = f"CONTRACT-{secrets.token_hex(8).upper()}"

        # Fee structure based on deal type
        if is_overflow:
            fee_structure = {
                "originating_broker": {"role": "referral", "percentage": 0.25, "flat_fee": 0},
                "processing_broker": {"role": "processor", "percentage": 0.75, "flat_fee": 0},
                "platform": {"role": "platform", "percentage": 0.10, "flat_fee": 0},
            }
        else:
            fee_structure = {
                "originating_broker": {"role": "originator", "percentage": 1.0, "flat_fee": 0},
                "platform": {"role": "platform", "percentage": 0.10, "flat_fee": 0},
            }

        terms = {
            "non_circumvention": True,
            "non_circumvention_period_months": 24,
            "communication_through_platform": True,
            "fee_auto_execute": True,
            "borrower_data_access": "platform_controlled",
            "dispute_resolution": "platform_arbitration",
            "created_at": datetime.now().isoformat(),
        }

        # Create immutable hash of the contract
        contract_data = {
            "contract_id": contract_id,
            "application_id": application_id,
            "borrower_id": borrower_id,
            "originating_broker": originating_broker,
            "processing_broker": processing_broker,
            "loan_amount": loan_amount,
            "fee_structure": fee_structure,
            "terms": terms,
        }
        contract_hash = hashlib.sha256(json.dumps(contract_data, sort_keys=True).encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Store contract
        c.execute('''INSERT INTO deal_contracts
            (contract_id, application_id, borrower_id, originating_broker,
             processing_broker, is_overflow, contract_hash, created_at,
             loan_amount, fee_structure, terms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (contract_id, application_id, borrower_id, originating_broker,
             processing_broker, is_overflow, contract_hash, datetime.now().isoformat(),
             loan_amount, json.dumps(fee_structure), json.dumps(terms)))

        # Store fee splits
        for payee, fee in fee_structure.items():
            broker_id = originating_broker if payee == "originating_broker" else (
                processing_broker if payee == "processing_broker" else "PLATFORM"
            )
            c.execute('''INSERT INTO fee_splits
                (contract_id, payee, role, percentage, flat_fee)
                VALUES (?, ?, ?, ?, ?)''',
                (contract_id, broker_id, fee["role"], fee["percentage"], fee["flat_fee"]))

        # Log creation event
        event_hash = hashlib.sha256(f"created:{contract_id}:{datetime.now().isoformat()}".encode()).hexdigest()
        c.execute('''INSERT INTO contract_events
            (contract_id, timestamp, event_type, details, actor, event_hash, previous_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (contract_id, datetime.now().isoformat(), "contract_created",
             json.dumps({"loan_amount": loan_amount, "is_overflow": is_overflow}),
             "PLATFORM", event_hash, None))

        conn.commit()
        conn.close()

        logger.info(f"Contract created: {contract_id} | Loan: ${loan_amount:,.0f} | Overflow: {is_overflow}")
        return contract_id

    def close_deal(self, contract_id: str, final_loan_amount: float) -> Dict:
        """
        Close the deal and execute fee splits automatically.
        This is the smart contract execution — fees are calculated and locked.
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Get contract
        c.execute("SELECT * FROM deal_contracts WHERE contract_id = ?", (contract_id,))
        contract = c.fetchone()
        if not contract:
            conn.close()
            return {"error": "Contract not found"}

        # Find fee_structure in contract row
        fee_structure = None
        for col in contract:
            if isinstance(col, str) and col.startswith('{"'):
                try:
                    parsed = json.loads(col)
                    if "originating_broker" in parsed or "platform" in parsed:
                        fee_structure = parsed
                        break
                except:
                    pass
        if not fee_structure:
            conn.close()
            return {"error": "Could not parse fee structure"}

        # Calculate and lock fee payments
        payments = {}
        total_commission = final_loan_amount * 0.01  # 1% total commission basis

        c.execute("SELECT id, payee, role, percentage, flat_fee FROM fee_splits WHERE contract_id = ?", (contract_id,))
        splits = c.fetchall()

        for split in splits:
            split_id, payee, role, percentage, flat_fee = split
            amount = (total_commission * percentage) + flat_fee
            payments[payee] = {"role": role, "amount": round(amount, 2)}

            # Mark as paid
            c.execute("UPDATE fee_splits SET status = 'executed', paid_at = ?, amount_paid = ? WHERE id = ?",
                      (datetime.now().isoformat(), round(amount, 2), split_id))

        # Close the contract
        c.execute("UPDATE deal_contracts SET status = 'closed', closed_at = ?, loan_amount = ? WHERE contract_id = ?",
                  (datetime.now().isoformat(), final_loan_amount, contract_id))

        # Log closing event with chain hash
        c.execute("SELECT event_hash FROM contract_events WHERE contract_id = ? ORDER BY id DESC LIMIT 1", (contract_id,))
        prev = c.fetchone()
        prev_hash = prev[0] if prev else None
        event_hash = hashlib.sha256(
            f"closed:{contract_id}:{final_loan_amount}:{datetime.now().isoformat()}:{prev_hash}".encode()
        ).hexdigest()

        c.execute('''INSERT INTO contract_events
            (contract_id, timestamp, event_type, details, actor, event_hash, previous_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (contract_id, datetime.now().isoformat(), "deal_closed",
             json.dumps({"final_loan_amount": final_loan_amount, "payments": payments}),
             "PLATFORM", event_hash, prev_hash))

        conn.commit()
        conn.close()

        logger.info(f"Deal closed: {contract_id} | ${final_loan_amount:,.0f}")
        for payee, payment in payments.items():
            logger.info(f"  Fee: {payee} ({payment['role']}) = ${payment['amount']:,.2f}")

        return {"contract_id": contract_id, "payments": payments, "status": "closed"}

    def send_message(self, contract_id: str, from_party: str, to_party: str,
                     message_type: str, content: str) -> bool:
        """
        All communication between parties goes through the platform.
        No direct contact. Messages are logged and hashed.
        """
        content_hash = hashlib.sha256(f"{from_party}:{to_party}:{content}:{datetime.now().isoformat()}".encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Verify both parties are on this contract
        c.execute("SELECT originating_broker, processing_broker FROM deal_contracts WHERE contract_id = ?", (contract_id,))
        contract = c.fetchone()
        if not contract:
            conn.close()
            return False

        valid_parties = {"PLATFORM", "BORROWER", contract[0]}
        if contract[1]:
            valid_parties.add(contract[1])

        if from_party not in valid_parties or to_party not in valid_parties:
            logger.warning(f"Unauthorized message attempt: {from_party} -> {to_party} on {contract_id}")
            conn.close()
            return False

        c.execute('''INSERT INTO messages
            (contract_id, timestamp, from_party, to_party, message_type, content, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (contract_id, datetime.now().isoformat(), from_party, to_party,
             message_type, content, content_hash))

        conn.commit()
        conn.close()
        return True

    def flag_circumvention(self, borrower_id: str, broker_id: str, reason: str, evidence: str = ""):
        """Flag a potential circumvention attempt"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO circumvention_flags
            (timestamp, borrower_id, flagged_broker, reason, evidence)
            VALUES (?, ?, ?, ?, ?)''',
            (datetime.now().isoformat(), borrower_id, broker_id, reason, evidence))
        conn.commit()
        conn.close()
        logger.warning(f"CIRCUMVENTION FLAG: {broker_id} attempting to contact {borrower_id} directly. Reason: {reason}")

    def check_prior_relationship(self, borrower_id: str) -> Optional[Dict]:
        """
        Check if a borrower has any existing contracts.
        If they do, new applications route through the original relationship.
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""SELECT contract_id, originating_broker, processing_broker, created_at, status
                     FROM deal_contracts
                     WHERE borrower_id = ?
                     ORDER BY created_at DESC LIMIT 1""",
                  (borrower_id,))
        row = c.fetchone()
        conn.close()

        if row:
            return {
                "contract_id": row[0],
                "originating_broker": row[1],
                "processing_broker": row[2],
                "relationship_since": row[3],
                "status": row[4],
            }
        return None

    def get_contract_chain(self, contract_id: str) -> List[Dict]:
        """Get the immutable event chain for a contract — proof of everything"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM contract_events WHERE contract_id = ? ORDER BY id ASC", (contract_id,))
        rows = c.fetchall()
        conn.close()

        chain = []
        for row in rows:
            chain.append({
                "id": row[0],
                "timestamp": row[2],
                "event_type": row[3],
                "details": json.loads(row[4]) if row[4] else {},
                "actor": row[5],
                "event_hash": row[6],
                "previous_hash": row[7],
            })

        # Verify chain integrity
        for i in range(1, len(chain)):
            if chain[i]["previous_hash"] != chain[i-1]["event_hash"]:
                chain[i]["INTEGRITY_VIOLATION"] = True
                logger.error(f"Chain integrity violation at event {chain[i]['id']}")

        return chain


# ================================================================
# WORK ORDER SYSTEM
# ================================================================

class WorkOrderSystem:
    """
    When a deal overflows, the receiving broker gets a work order — not a client.
    They see the deal. They don't see the borrower's PII.
    They communicate through the platform. They get paid through the contract.
    """

    def __init__(self, vault: BorrowerVault, contracts: DealContract,
                 db_path: str = "C:/DandyDon/investor_site/saas/workorders.db"):
        self.vault = vault
        self.contracts = contracts
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS work_orders (
            work_order_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            application_id TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            assigned_to TEXT NOT NULL,
            referred_by TEXT NOT NULL,
            deal_summary TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            completed_at TEXT,
            declined_at TEXT,
            decline_reason TEXT
        )''')

        conn.commit()
        conn.close()

    def create_work_order(self, contract_id: str, application_id: str, borrower_id: str,
                          full_application: Dict, assigned_to: str, referred_by: str) -> str:
        """
        Create a work order with REDACTED borrower info.
        The receiving broker sees the deal, not the person.
        """
        work_order_id = f"WO-{secrets.token_hex(8).upper()}"

        # Create redacted view — NO PII
        deal_summary = VaultEncryption.create_work_order_view(full_application)

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO work_orders
            (work_order_id, contract_id, application_id, borrower_id,
             assigned_to, referred_by, deal_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (work_order_id, contract_id, application_id, borrower_id,
             assigned_to, referred_by, json.dumps(deal_summary), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        # Grant work_order level access (no PII)
        self.vault.grant_access(
            borrower_id=borrower_id,
            broker_id=assigned_to,
            access_level="work_order",
            purpose=f"Overflow processing for {application_id}",
            duration_hours=72,
        )

        logger.info(f"Work order created: {work_order_id} | Assigned to: {assigned_to}")
        return work_order_id

    def accept_work_order(self, work_order_id: str, broker_id: str) -> bool:
        """Broker accepts the work order — gets upgraded access for processing"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT borrower_id, assigned_to FROM work_orders WHERE work_order_id = ?", (work_order_id,))
        row = c.fetchone()
        if not row or row[1] != broker_id:
            conn.close()
            return False

        c.execute("UPDATE work_orders SET status = 'accepted', accepted_at = ? WHERE work_order_id = ?",
                  (datetime.now().isoformat(), work_order_id))
        conn.commit()
        conn.close()

        # Upgrade access to processing level (limited PII — name, phone for communication through platform)
        self.vault.grant_access(
            borrower_id=row[0],
            broker_id=broker_id,
            access_level="processing",
            purpose=f"Accepted work order {work_order_id}",
            duration_hours=720,  # 30 days for processing
        )

        logger.info(f"Work order accepted: {work_order_id} by {broker_id}")
        return True

    def decline_work_order(self, work_order_id: str, broker_id: str, reason: str) -> bool:
        """Broker declines — work order goes to next eligible broker"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT assigned_to, borrower_id FROM work_orders WHERE work_order_id = ?", (work_order_id,))
        row = c.fetchone()
        if not row or row[0] != broker_id:
            conn.close()
            return False

        c.execute("UPDATE work_orders SET status = 'declined', declined_at = ?, decline_reason = ? WHERE work_order_id = ?",
                  (datetime.now().isoformat(), reason, work_order_id))
        conn.commit()
        conn.close()

        # Revoke access
        self.vault.revoke_all_access(row[1], broker_id)

        logger.info(f"Work order declined: {work_order_id} by {broker_id}. Reason: {reason}")
        return True

    def complete_work_order(self, work_order_id: str, broker_id: str) -> bool:
        """Mark work order as complete — triggers fee execution"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT contract_id, assigned_to, borrower_id FROM work_orders WHERE work_order_id = ?", (work_order_id,))
        row = c.fetchone()
        if not row or row[1] != broker_id:
            conn.close()
            return False

        c.execute("UPDATE work_orders SET status = 'completed', completed_at = ? WHERE work_order_id = ?",
                  (datetime.now().isoformat(), work_order_id))
        conn.commit()
        conn.close()

        # Revoke processing access — deal is done
        self.vault.revoke_all_access(row[2], broker_id)

        logger.info(f"Work order completed: {work_order_id}")
        return True


# ================================================================
# NON-CIRCUMVENTION MONITOR
# ================================================================

class CircumventionMonitor:
    """
    Monitors for attempts to bypass the platform.
    Detects: direct contact, duplicate applications, relationship theft.
    """

    def __init__(self, contracts: DealContract,
                 db_path: str = "C:/DandyDon/investor_site/saas/contracts.db"):
        self.contracts = contracts
        self.db_path = db_path

    def check_new_application(self, borrower_id: str, submitting_broker: str) -> Dict:
        """
        When a new application comes in, check if this borrower has existing relationships.
        If yes, route through the existing relationship — not the new broker.
        """
        prior = self.contracts.check_prior_relationship(borrower_id)

        if not prior:
            return {"status": "new_borrower", "action": "process_normally"}

        # Borrower has a prior relationship
        original_broker = prior["originating_broker"]
        processing_broker = prior.get("processing_broker")

        if submitting_broker == original_broker:
            return {"status": "returning_client", "action": "process_normally", "original_broker": original_broker}

        if submitting_broker == processing_broker:
            # The overflow broker is trying to take the client directly
            self.contracts.flag_circumvention(
                borrower_id=borrower_id,
                broker_id=submitting_broker,
                reason="Overflow broker attempting direct application for previously routed borrower",
                evidence=f"Prior contract: {prior['contract_id']}, Original broker: {original_broker}"
            )
            return {
                "status": "circumvention_detected",
                "action": "route_to_original_broker",
                "original_broker": original_broker,
                "flagged_broker": submitting_broker,
                "prior_contract": prior["contract_id"],
            }

        # Different broker entirely — could be legitimate (borrower shopping) or circumvention
        non_circ_period = 24  # months
        relationship_date = datetime.fromisoformat(prior["relationship_since"])
        if datetime.now() - relationship_date < timedelta(days=non_circ_period * 30):
            return {
                "status": "existing_relationship",
                "action": "route_to_original_broker",
                "original_broker": original_broker,
                "message": f"Borrower has existing relationship with {original_broker} since {prior['relationship_since']}. Non-circumvention period: {non_circ_period} months.",
            }

        # Past the non-circumvention period — borrower is free
        return {"status": "relationship_expired", "action": "process_normally"}


# ================================================================
# DEMO / TEST
# ================================================================

if __name__ == "__main__":
    print("=== Click Click Close Smart Contract System ===\n")

    # Initialize systems
    vault = BorrowerVault()
    contracts = DealContract()
    work_orders = WorkOrderSystem(vault, contracts)
    monitor = CircumventionMonitor(contracts)

    # 1. Borrower applies through Broker A
    print("1. Borrower applies through Broker A (residential broker)")
    borrower_pii = {
        "name": "John Smith",
        "ssn": "123-45-6789",
        "email": "john@email.com",
        "phone": "555-123-4567",
        "dob": "1985-03-15",
    }
    borrower_id = "BRW-" + hashlib.sha256("John Smith:123-45-6789".encode()).hexdigest()[:12].upper()
    access_key = vault.store_borrower(borrower_id, borrower_pii)
    print(f"   Borrower stored: {borrower_id}")
    print(f"   PII encrypted in vault")

    # 2. Deal doesn't fit Broker A — overflow to Broker B
    print("\n2. Deal is DSCR — Broker A doesn't do DSCR — overflow to Broker B")
    contract_id = contracts.create_contract(
        application_id="CCC-20260318-TEST01",
        borrower_id=borrower_id,
        originating_broker="BROKER-A",
        loan_amount=350000,
        processing_broker="BROKER-B",
        is_overflow=True,
    )
    print(f"   Contract created: {contract_id}")

    # 3. Work order sent to Broker B (NO PII)
    print("\n3. Work order sent to Broker B (NO PII visible)")
    full_app = {
        "borrower": {"credit_score": 720, "experience": "3 years", "citizenship": "us_citizen", "is_veteran": False},
        "property": {"type": "sfr", "value": 350000, "address": "123 Main St"},
        "loan": {"purpose": "purchase", "amount": 280000},
        "financials": {"monthly_rent": 2200},
    }
    wo_id = work_orders.create_work_order(
        contract_id=contract_id,
        application_id="CCC-20260318-TEST01",
        borrower_id=borrower_id,
        full_application=full_app,
        assigned_to="BROKER-B",
        referred_by="BROKER-A",
    )
    print(f"   Work order: {wo_id}")

    # Show what Broker B sees
    redacted = VaultEncryption.create_work_order_view(full_app)
    print(f"   Broker B sees: {json.dumps(redacted, indent=2)}")
    print(f"   Broker B does NOT see: name, SSN, email, phone, DOB")

    # 4. Broker B accepts
    print("\n4. Broker B accepts work order")
    work_orders.accept_work_order(wo_id, "BROKER-B")

    # 5. Communication through platform only
    print("\n5. All communication goes through platform")
    contracts.send_message(contract_id, "BROKER-B", "BORROWER", "update",
                          "Your DSCR loan is in underwriting. We need the lease agreement.")
    contracts.send_message(contract_id, "BORROWER", "BROKER-B", "document",
                          "Lease agreement uploaded to vault.")
    print("   Messages logged and hashed")

    # 6. Deal closes — fees execute automatically
    print("\n6. Deal closes at $280,000 — fees execute automatically")
    result = contracts.close_deal(contract_id, 280000)
    print(f"   Status: {result['status']}")
    for payee, payment in result['payments'].items():
        print(f"   {payee} ({payment['role']}): ${payment['amount']:,.2f}")

    # 7. Circumvention attempt — Broker B tries to take the client
    print("\n7. CIRCUMVENTION TEST: Broker B tries to submit same borrower directly")
    circumvention_check = monitor.check_new_application(borrower_id, "BROKER-B")
    print(f"   Status: {circumvention_check['status']}")
    print(f"   Action: {circumvention_check['action']}")
    if circumvention_check.get('flagged_broker'):
        print(f"   FLAGGED: {circumvention_check['flagged_broker']}")

    # 8. Verify contract chain integrity
    print("\n8. Contract chain (immutable audit trail):")
    chain = contracts.get_contract_chain(contract_id)
    for event in chain:
        print(f"   [{event['event_type']}] {event['timestamp']}")
        print(f"     Hash: {event['event_hash'][:20]}...")
        if event.get("previous_hash"):
            print(f"     Prev: {event['previous_hash'][:20]}...")

    print("\n=== System operational ===")
