import argparse
import json
import re
import secrets
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from database import SessionLocal
from models import Student
from uuid import uuid4
from utils import normalize_phone


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\D", "", value)
    if not 8 <= len(phone) <= 15:
        raise ValueError(f"phone must contain between 8 and 15 digits, got {phone}")
    return phone


def generate_passcode() -> str:
    return f"AUTH-{secrets.randbelow(900000) + 100000}"


def seed_students(db, students: list[dict]) -> list[dict]:
    results = []
    for s in students:
        email = s.get("email", "").strip().lower()
        first_name = s.get("first_name", s.get("firstName", "")).strip()
        surname = s.get("surname", s.get("lastName", "")).strip()
        phone = normalize_phone(s.get("phone", s.get("contact", "")))
        university = s.get("university", "").strip() or None
        field = s.get("field", "").strip() or None
        study_year = s.get("study_year", s.get("year", None))

        existing = db.query(Student).filter(Student.email == email).first()
        if existing:
            results.append({"email": email, "status": "skipped", "reason": "already exists"})
            continue

        passcode = generate_passcode()
        while db.query(Student).filter(Student.auth_passcode == passcode).first():
            passcode = generate_passcode()

        student = Student(
            id=uuid4(),
            first_name=first_name,
            surname=surname,
            email=email,
            phone=phone,
            university=university,
            field=field,
            study_year=study_year,
            auth_passcode=passcode,
            status="UNVERIFIED",
        )
        db.add(student)
        results.append({
            "email": email,
            "status": "created",
            "auth_passcode": passcode,
            "name": f"{first_name} {surname}".strip(),
        })
    db.commit()
    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Seed existing students into the APEX database")
    parser.add_argument("--file", help="Path to JSON file with student array")
    parser.add_argument("--phone", action="append", help="Phone number (can be repeated)")
    parser.add_argument("--name", action="append", help="Full name (can be repeated)")
    parser.add_argument("--email", action="append", help="Email address (can be repeated)")
    parser.add_argument("--university", action="append", help="University (can be repeated)")
    parser.add_argument("--field", action="append", help="Field of study (can be repeated)")
    parser.add_argument("--year", type=int, action="append", help="Study year (can be repeated)")
    return parser.parse_args()


def main():
    args = parse_args()

    students: list[dict] = []

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
        if not isinstance(data, list):
            print("Error: JSON file must contain an array of student objects", file=sys.stderr)
            sys.exit(1)
        students.extend(data)

    if args.phone:
        count = len(args.phone)
        for i in range(count):
            student: dict = {"phone": args.phone[i]}
            if i < len(args.name):
                name_parts = args.name[i].split(" ", 1)
                student["first_name"] = name_parts[0]
                student["surname"] = name_parts[1] if len(name_parts) > 1 else ""
            if i < len(args.email):
                student["email"] = args.email[i]
            if i < len(args.university):
                student["university"] = args.university[i]
            if i < len(args.field):
                student["field"] = args.field[i]
            if args.year and i < len(args.year):
                student["study_year"] = args.year[i]
            students.append(student)

    if not students:
        print("Error: provide --file or at least --phone", file=sys.stderr)
        sys.exit(1)

    with SessionLocal.begin() as db:
        results = seed_students(db, students)

    created = [r for r in results if r["status"] == "created"]
    skipped = [r for r in results if r["status"] == "skipped"]

    print(f"\nSeeded {len(created)} student(s), skipped {len(skipped)} already-existing.\n")
    if created:
        print("Auth passcodes (send these to students via WhatsApp):")
        print("-" * 60)
        for r in created:
            print(f"  {r['auth_passcode']}  →  {r['name']} ({r['email']})")
    if skipped:
        print("\nSkipped (already in DB):")
        for r in skipped:
            print(f"  {r['email']} — {r['reason']}")
    print()


if __name__ == "__main__":
    main()