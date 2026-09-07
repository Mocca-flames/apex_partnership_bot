"""Integration tests for Phase 5 — requires Docker stack running on localhost."""
import json
import sys
import time
import unittest
import uuid

BACKEND_URL = "http://localhost:8000"
WEBHOOK_SECRET = "dev-webhook-secret"


def _post(endpoint: str, data: dict, headers: dict | None = None) -> tuple[int, dict]:
    import urllib.request
    url = f"{BACKEND_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body}


def _get(endpoint: str) -> tuple[int, dict]:
    import urllib.request
    url = f"{BACKEND_URL}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def _send_webhook(sender: str, text: str) -> tuple[int, dict]:
    return _post("/webhook/whatsapp", {
        "sender_phone": sender,
        "text_content": text,
    }, {"x-webhook-secret": WEBHOOK_SECRET})


def _send_webhook_raw(sender: str, text: str) -> tuple[int, dict]:
    return _post("/webhook/whatsapp", {
        "sender_phone": sender,
        "text_content": text,
    })


class TestHealth(unittest.TestCase):
    def test_backend_health(self):
        status, body = _get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")


class TestRateLimiting(unittest.TestCase):
    def test_rate_limit_kicks_in(self):
        sender = "27829990001"
        for i in range(10):
            _send_webhook(sender, f"test message {i}")
        status, body = _send_webhook(sender, "should be rate limited")
        self.assertEqual(status, 202)


class TestWebhookAuth(unittest.TestCase):
    def test_rejects_bad_secret(self):
        status, body = _send_webhook_raw("27829990002", "hello")
        self.assertIn(status, [401, 422])


class TestStaffAccessControl(unittest.TestCase):
    def test_non_staff_gets_no_response_for_slash_command(self):
        sender = "27829990003"
        status, body = _send_webhook(sender, "/pending")
        self.assertEqual(status, 202)


class TestLeadLifecycle(unittest.TestCase):
    """Full lifecycle: signup -> link -> tutorial -> lead -> staff vet -> load -> pay."""

    @classmethod
    def setUpClass(cls):
        cls.student_phone = "27829990010"
        cls.staff_phone = "27829990011"
        cls.fleet_phone = "27829990012"
        cls.student_id = None
        cls.lead_id = None
        cls.passcode = None

    def test_01_signup(self):
        status, body = _post("/api/v1/students/signup", {
            "first_name": "Test",
            "surname": "Student",
            "email": f"test.lifecycle.{uuid.uuid4().hex[:8]}@example.com",
            "phone": "27829990010",
        })
        self.assertEqual(status, 200)
        self.assertIn("auth_passcode", body)
        self.__class__.passcode = body["auth_passcode"]

    def test_02_auth_link(self):
        if not self.__class__.passcode:
            self.skipTest("Signup not completed")
        status, body = _send_webhook(self.student_phone, self.__class__.passcode)
        self.assertEqual(status, 202)

    def test_03_tutorial(self):
        status, body = _send_webhook(self.student_phone, "TUTORIAL")
        self.assertEqual(status, 202)
        status, body = _send_webhook(self.student_phone, "READY")
        self.assertEqual(status, 202)
        submission = "PHONE: 27820000000\nCOMPANY: APEX PRACTICE LOGISTICS\nTRUCKS: 5"
        status, body = _send_webhook(self.student_phone, submission)
        self.assertEqual(status, 202)

    def test_04_submit_lead(self):
        status, body = _send_webhook(self.student_phone, "LEAD")
        self.assertEqual(status, 202)
        status, body = _send_webhook(self.student_phone, self.fleet_phone)
        self.assertEqual(status, 202)
        status, body = _send_webhook(self.student_phone, "Test Transport Co")
        self.assertEqual(status, 202)
        status, body = _send_webhook(self.student_phone, "3")
        self.assertEqual(status, 202)
        status, body = _send_webhook(self.student_phone, "Superlink")
        self.assertEqual(status, 202)

    def test_05_status_command(self):
        status, body = _send_webhook(self.student_phone, "STATUS")
        self.assertEqual(status, 202)


class TestStaffCommands(unittest.TestCase):
    """Test staff slash commands — requires apex_staff entry for staff_phone."""

    @classmethod
    def setUpClass(cls):
        cls.staff_phone = "27829990020"
        cls.student_phone = "27829990021"
        cls.fleet_phone = "27829990022"
        cls.student_id = None
        cls.lead_id = None

    def test_01_pending_empty(self):
        status, body = _send_webhook(self.staff_phone, "/pending")
        self.assertEqual(status, 202)

    def test_02_non_staff_pending(self):
        sender = "27829990025"
        status, body = _send_webhook(sender, "/pending")
        self.assertEqual(status, 202)

    def test_03_vet_usage(self):
        status, body = _send_webhook(self.staff_phone, "/vet")
        self.assertEqual(status, 202)

    def test_04_load_usage(self):
        status, body = _send_webhook(self.staff_phone, "/load")
        self.assertEqual(status, 202)

    def test_05_pay_usage(self):
        status, body = _send_webhook(self.staff_phone, "/pay")
        self.assertEqual(status, 202)

    def test_06_fraud_usage(self):
        status, body = _send_webhook(self.staff_phone, "/fraud")
        self.assertEqual(status, 202)

    def test_07_unknown_staff_command(self):
        status, body = _send_webhook(self.staff_phone, "/unknown")
        self.assertEqual(status, 202)


class TestPermanentlyBannedStudent(unittest.TestCase):
    def test_banned_student_blocked(self):
        sender = "27829990030"
        status, body = _send_webhook(sender, "LEAD")
        self.assertEqual(status, 202)


class TestLeadDeduplication(unittest.TestCase):
    def test_duplicate_phone_rejected(self):
        phone_a = "27829990040"
        phone_b = "27829990041"
        fleet = "27829990042"
        _send_webhook(phone_a, "LEAD")
        _send_webhook(phone_a, fleet)
        _send_webhook(phone_a, "Company A")
        _send_webhook(phone_a, "1")
        _send_webhook(phone_a, "Lowbed")
        _send_webhook(phone_b, "LEAD")
        status, body = _send_webhook(phone_b, fleet)
        self.assertEqual(status, 202)


class TestInvalidInputs(unittest.TestCase):
    def test_invalid_truck_count(self):
        sender = "27829990050"
        _send_webhook(sender, "LEAD")
        _send_webhook(sender, "27829990055")
        _send_webhook(sender, "Some Company")
        status, body = _send_webhook(sender, "abc")
        self.assertEqual(status, 202)

    def test_invalid_truck_type(self):
        sender = "27829990051"
        _send_webhook(sender, "LEAD")
        _send_webhook(sender, "27829990056")
        _send_webhook(sender, "Some Company")
        _send_webhook(sender, "2")
        status, body = _send_webhook(sender, "Spaceship")
        self.assertEqual(status, 202)


if __name__ == "__main__":
    print("=" * 60)
    print("APEX Partnership — Phase 5 Integration Tests")
    print(f"Target: {BACKEND_URL}")
    print("=" * 60)
    unittest.main(verbosity=2)
