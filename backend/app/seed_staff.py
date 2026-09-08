import argparse
import re

from .database import SessionLocal
from .models import ApexStaff


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\D", "", value)
    if not 8 <= len(phone) <= 15:
        raise ValueError("phone must contain between 8 and 15 digits")
    return phone


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