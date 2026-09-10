import argparse
import re
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from database import SessionLocal
from models import ApexStaff

SA_PREFIX = "27"
SA_HUMAN_PREFIX = "0"
SA_HUMAN_LENGTH = 10
SA_INTERNATIONAL_LENGTH = 11


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if not digits:
        return digits
    if digits.startswith(SA_HUMAN_PREFIX) and len(digits) == SA_HUMAN_LENGTH:
        return SA_PREFIX + digits[1:]
    if digits.startswith(SA_PREFIX) and len(digits) == SA_INTERNATIONAL_LENGTH:
        return digits
    return digits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update an APEX staff account")
    parser.add_argument("--phone", required=True, help="WhatsApp number in international format")
    parser.add_argument("--name", required=True, help="Staff member's display name")
    parser.add_argument("--role", choices=("ADMIN", "STAFF"), default="STAFF")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phone = normalize_phone(args.phone)

    with SessionLocal.begin() as db:
        staff = db.get(ApexStaff, phone)
        if staff is None:
            staff = ApexStaff(phone_number=phone)
            db.add(staff)
        staff.staff_name = args.name.strip()
        staff.role = args.role

    print(f"Seeded {phone} as {args.role} ({args.name.strip()})")


if __name__ == "__main__":
    main()