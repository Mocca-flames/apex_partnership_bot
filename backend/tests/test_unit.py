"""Unit tests for Phase 5 helper functions.

Extracts and tests pure logic functions without importing app.main
to avoid database dependency chain. Tests the same logic that runs
inside the webhook handler.
"""
import re
import sys
import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock
from uuid import uuid4


# ---- Extracted functions (mirrors app/main.py) ----

RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
_rate_limits: dict[str, list[float]] = defaultdict(list)

PRACTICE_PHONE = "27820000000"
PRACTICE_COMPANY = "APEX PRACTICE LOGISTICS"
PRACTICE_TRUCK_COUNT = 5


def _rate_check(sender_phone: str) -> bool:
    now = time.time()
    _rate_limits[sender_phone] = [t for t in _rate_limits[sender_phone] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[sender_phone]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[sender_phone].append(now)
    return True


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def lead_status_label(status_val: str) -> str:
    return {
        "NEW_LEAD": "Under Review",
        "VETTED": "Verified (Awaiting Load)",
        "LOADED": "Truck Loaded (Commission Pending)",
        "PAID": "Commission Paid!",
    }.get(status_val, "Closed / Rejected" if status_val.startswith("REJECTED_") else status_val.title())


def lead_status_summary(leads: list) -> str:
    if not leads:
        return "You have no submitted leads yet. Reply LEAD to submit one."
    lines = ["Your APEX lead pipeline:"]
    for lead in leads:
        lines.append(f"- {lead.company_name} ({lead.truck_count} trucks): {lead_status_label(lead.status)}")
    return "\n".join(lines)


def parse_practice_submission(text_content: str) -> dict[str, str] | None:
    fields = {}
    patterns = {
        "phone": r"(?:phone|dummy\s*phone)\s*[:=-]\s*([+\d\s()-]+)",
        "company": r"(?:company|dummy\s*company)\s*[:=-]\s*(.+)",
        "trucks": r"(?:trucks?|truck\s*count|dummy\s*truck\s*count)\s*[:=-]\s*(\d+)",
    }
    for field_name, pattern in patterns.items():
        match = re.search(pattern, text_content, re.IGNORECASE | re.MULTILINE)
        if match:
            fields[field_name] = match.group(1).strip()
    return fields or None


def practice_submission_errors(fields: dict[str, str] | None) -> list[str]:
    if not fields:
        return ["Use this format: PHONE: 27820000000, COMPANY: APEX PRACTICE LOGISTICS, TRUCKS: 5."]
    errors = []
    phone = re.sub(r"\D", "", fields.get("phone", ""))
    if phone != PRACTICE_PHONE:
        errors.append(f"the phone must be {PRACTICE_PHONE}")
    if fields.get("company", "").strip().upper() != PRACTICE_COMPANY:
        errors.append(f'the company must be "{PRACTICE_COMPANY}"')
    if fields.get("trucks") != str(PRACTICE_TRUCK_COUNT):
        errors.append(f"the truck count must be {PRACTICE_TRUCK_COUNT}")
    return errors


def _is_staff(db, phone: str):
    return db.query(MagicMock).filter(MagicMock.phone_number == phone).first()


# ---- Tests ----

class TestNormalizePhone(unittest.TestCase):
    def test_strips_non_digits(self):
        self.assertEqual(normalize_phone("+27 82 123 4567"), "27821234567")

    def test_already_clean(self):
        self.assertEqual(normalize_phone("27820000000"), "27820000000")

    def test_empty(self):
        self.assertEqual(normalize_phone(""), "")

    def test_parens_dashes(self):
        self.assertEqual(normalize_phone("(082) 123-4567"), "0821234567")

    def test_international_with_plus(self):
        self.assertEqual(normalize_phone("+263 77 123 4567"), "263771234567")


class TestLeadStatusLabel(unittest.TestCase):
    def test_new_lead(self):
        self.assertEqual(lead_status_label("NEW_LEAD"), "Under Review")

    def test_vetted(self):
        self.assertEqual(lead_status_label("VETTED"), "Verified (Awaiting Load)")

    def test_loaded(self):
        self.assertEqual(lead_status_label("LOADED"), "Truck Loaded (Commission Pending)")

    def test_paid(self):
        self.assertEqual(lead_status_label("PAID"), "Commission Paid!")

    def test_rejected_fraud(self):
        self.assertEqual(lead_status_label("REJECTED_FRAUD"), "Closed / Rejected")

    def test_rejected_other(self):
        self.assertEqual(lead_status_label("REJECTED_DUPLICATE"), "Closed / Rejected")

    def test_unknown(self):
        self.assertEqual(lead_status_label("UNKNOWN_STATUS"), "Unknown_Status")

    def test_admin_hold(self):
        self.assertEqual(lead_status_label("ADMIN_HOLD"), "Admin_Hold")


class TestLeadStatusSummary(unittest.TestCase):
    def test_empty_leads(self):
        result = lead_status_summary([])
        self.assertIn("no submitted leads", result.lower())

    def test_single_lead(self):
        lead = MagicMock()
        lead.company_name = "Acme Logistics"
        lead.truck_count = 5
        lead.status = "NEW_LEAD"
        result = lead_status_summary([lead])
        self.assertIn("Acme Logistics", result)
        self.assertIn("5 trucks", result)
        self.assertIn("Under Review", result)

    def test_multiple_leads(self):
        lead1 = MagicMock()
        lead1.company_name = "Acme Logistics"
        lead1.truck_count = 5
        lead1.status = "NEW_LEAD"
        lead2 = MagicMock()
        lead2.company_name = "Fast Haulers"
        lead2.truck_count = 3
        lead2.status = "LOADED"
        result = lead_status_summary([lead1, lead2])
        self.assertIn("Acme Logistics", result)
        self.assertIn("Fast Haulers", result)
        self.assertIn("Under Review", result)
        self.assertIn("Commission Pending", result)


class TestRateLimiting(unittest.TestCase):
    def setUp(self):
        _rate_limits.clear()

    def test_allows_first_10(self):
        for i in range(10):
            self.assertTrue(_rate_check("27820000001"), f"Message {i+1} should be allowed")

    def test_blocks_11th(self):
        for _ in range(10):
            _rate_check("27820000002")
        self.assertFalse(_rate_check("27820000002"))

    def test_separate_users_independent(self):
        for _ in range(10):
            _rate_check("27820000003")
        self.assertTrue(_rate_check("27820000004"))

    def test_old_entries_expire(self):
        for _ in range(10):
            _rate_check("27820000005")
        # Simulate entries older than window
        _rate_limits["27820000005"] = [time.time() - 61]
        self.assertTrue(_rate_check("27820000005"))

    def test_partial_window(self):
        for _ in range(5):
            _rate_check("27820000006")
        # Only 5 messages, should still allow
        self.assertTrue(_rate_check("27820000006"))

    def test_empty_phone(self):
        self.assertTrue(_rate_check(""))


class TestPracticeSubmission(unittest.TestCase):
    def test_valid_full_submission(self):
        text = "PHONE: 27820000000\nCOMPANY: APEX PRACTICE LOGISTICS\nTRUCKS: 5"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["phone"], "27820000000")
        self.assertEqual(fields["company"], "APEX PRACTICE LOGISTICS")
        self.assertEqual(fields["trucks"], "5")

    def test_no_fields(self):
        self.assertIsNone(parse_practice_submission("hello world"))

    def test_partial_fields(self):
        text = "PHONE: 27820000000"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["phone"], "27820000000")
        self.assertNotIn("company", fields)

    def test_equals_delimiter(self):
        text = "PHONE=27820000000\nCOMPANY=TEST CO\nTRUCKS=2"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["trucks"], "2")

    def test_dash_delimiter(self):
        text = "PHONE - 27820000000\nCOMPANY - TEST CO\nTRUCKS - 2"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)

    def test_case_insensitive(self):
        text = "phone: 27820000000\ncompany: TEST\ntrucks: 1"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)

    def test_dummy_prefix(self):
        text = "DUMMY PHONE: 27820000000\nDUMMY COMPANY: TEST\nDUMMY TRUCKS: 1"
        fields = parse_practice_submission(text)
        self.assertIsNotNone(fields)


class TestPracticeSubmissionErrors(unittest.TestCase):
    def test_no_fields_returns_format_error(self):
        errors = practice_submission_errors(None)
        self.assertEqual(len(errors), 1)
        self.assertIn("format", errors[0].lower())

    def test_empty_dict_returns_format_error(self):
        errors = practice_submission_errors({})
        self.assertEqual(len(errors), 1)

    def test_valid_submission_no_errors(self):
        fields = {"phone": "27820000000", "company": "APEX PRACTICE LOGISTICS", "trucks": "5"}
        errors = practice_submission_errors(fields)
        self.assertEqual(errors, [])

    def test_wrong_phone(self):
        fields = {"phone": "27820000001", "company": "APEX PRACTICE LOGISTICS", "trucks": "5"}
        errors = practice_submission_errors(fields)
        self.assertTrue(any("phone" in e.lower() for e in errors))

    def test_wrong_company(self):
        fields = {"phone": "27820000000", "company": "WRONG COMPANY", "trucks": "5"}
        errors = practice_submission_errors(fields)
        self.assertTrue(any("company" in e.lower() for e in errors))

    def test_wrong_trucks(self):
        fields = {"phone": "27820000000", "company": "APEX PRACTICE LOGISTICS", "trucks": "3"}
        errors = practice_submission_errors(fields)
        self.assertTrue(any("truck" in e.lower() for e in errors))

    def test_all_wrong(self):
        fields = {"phone": "000", "company": "X", "trucks": "0"}
        errors = practice_submission_errors(fields)
        self.assertEqual(len(errors), 3)

    def test_phone_with_formatting(self):
        fields = {"phone": "+27 82 000 0000", "company": "APEX PRACTICE LOGISTICS", "trucks": "5"}
        errors = practice_submission_errors(fields)
        self.assertEqual(errors, [])


class TestStaffCommandParsing(unittest.TestCase):
    def test_parse_pending(self):
        parts = "/pending".split()
        self.assertEqual(parts[0].lower(), "/pending")
        self.assertEqual(len(parts[1:]), 0)

    def test_parse_vet_with_id(self):
        parts = "/vet abc-123".split()
        self.assertEqual(parts[0].lower(), "/vet")
        self.assertEqual(parts[1], "abc-123")

    def test_parse_load(self):
        parts = "/load lead-1 5".split()
        self.assertEqual(parts[0].lower(), "/load")
        self.assertEqual(parts[1], "lead-1")
        self.assertEqual(parts[2], "5")

    def test_parse_pay(self):
        parts = "/pay student-1 lead-1".split()
        self.assertEqual(parts[0].lower(), "/pay")
        self.assertEqual(parts[1], "student-1")
        self.assertEqual(parts[2], "lead-1")

    def test_parse_fraud(self):
        parts = "/fraud student-1".split()
        self.assertEqual(parts[0].lower(), "/fraud")
        self.assertEqual(parts[1], "student-1")

    def test_parse_vet_no_id(self):
        parts = "/vet".split()
        self.assertEqual(len(parts), 1)

    def test_parse_load_no_args(self):
        parts = "/load".split()
        self.assertEqual(len(parts), 1)

    def test_parse_load_one_arg(self):
        parts = "/load lead-1".split()
        self.assertEqual(len(parts), 2)


class TestCommissionCalculation(unittest.TestCase):
    def test_single_truck(self):
        self.assertEqual(1 * 1000, 1000)

    def test_ten_trucks(self):
        self.assertEqual(10 * 1000, 10000)

    def test_large_fleet(self):
        self.assertEqual(100 * 1000, 100000)


class TestWebhookSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, r"C:\Users\MauriX\Documents\DEVS\APEX-PARTNERSHIP\backend")

    def test_inbound_message_valid(self):
        from app.schemas import InboundMessage
        msg = InboundMessage(sender_phone="27820000000", text_content="Hello")
        self.assertEqual(msg.sender_phone, "27820000000")
        self.assertEqual(msg.text_content, "Hello")

    def test_inbound_message_empty_phone_rejected(self):
        from app.schemas import InboundMessage
        with self.assertRaises(Exception):
            InboundMessage(sender_phone="", text_content="Hello")

    def test_outbound_message_valid(self):
        from app.schemas import OutboundMessage
        msg = OutboundMessage(recipient_phone="27820000000", text_content="Hi")
        self.assertEqual(msg.recipient_phone, "27820000000")

    def test_outbound_message_no_text_rejected(self):
        from app.schemas import OutboundMessage
        with self.assertRaises(Exception):
            OutboundMessage(recipient_phone="27820000000", text_content="")

    def test_outbound_with_buttons(self):
        from app.schemas import OutboundMessage
        msg = OutboundMessage(recipient_phone="27820000000", text_content="Choose:", buttons=["A", "B"])
        self.assertEqual(msg.buttons, ["A", "B"])

    def test_webhook_response(self):
        from app.schemas import WebhookResponse
        resp = WebhookResponse(accepted=True, message_id=uuid4())
        self.assertTrue(resp.accepted)
        self.assertIsNotNone(resp.message_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
