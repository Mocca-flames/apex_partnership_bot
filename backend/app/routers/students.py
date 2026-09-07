import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Student
from ..schemas import StudentSignupRequest, StudentSignupResponse

router = APIRouter(prefix="/api/v1/students", tags=["students"])


class GenerateOtpRequest(BaseModel):
    email: EmailStr


class GenerateOtpResponse(BaseModel):
    message: str
    auth_passcode: str
    bot_phone: str
    click_to_chat_url: str


class BulkStudentRequest(BaseModel):
    students: list[dict]


def generate_passcode() -> str:
    return f"AUTH-{secrets.randbelow(900000) + 100000}"


@router.post("/signup", response_model=StudentSignupResponse, status_code=status.HTTP_201_CREATED)
def signupStudent(
    payload: StudentSignupRequest,
    db: Session = Depends(get_db),
) -> StudentSignupResponse:
    existing = db.query(Student).filter(
        (Student.email == payload.email) | (Student.phone == payload.phone)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A student with this email or phone already exists",
        )

    passcode = generate_passcode()
    while db.query(Student).filter(Student.auth_passcode == passcode).first():
        passcode = generate_passcode()

    student = Student(
        id=uuid4(),
        first_name=payload.first_name,
        surname=payload.surname,
        email=payload.email,
        phone=payload.phone,
        university=payload.university,
        field=payload.field,
        study_year=payload.study_year,
        auth_passcode=passcode,
        status="UNVERIFIED",
    )
    db.add(student)
    db.commit()

    bot_phone = settings.apex_bot_phone.lstrip("+").replace(" ", "")
    click_to_chat_url = f"https://wa.me/{bot_phone}?text={passcode}"

    return StudentSignupResponse(
        auth_passcode=passcode,
        bot_phone=settings.apex_bot_phone,
        click_to_chat_url=click_to_chat_url,
    )


@router.post("/generate-otp", response_model=GenerateOtpResponse)
def generate_otp_for_existing_student(
    payload: GenerateOtpRequest,
    db: Session = Depends(get_db),
) -> GenerateOtpResponse:
    student = db.query(Student).filter(Student.email == payload.email).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No student found with this email address",
        )

    if student.status != "UNVERIFIED" and student.whatsapp_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This student is already verified",
        )

    passcode = generate_passcode()
    while db.query(Student).filter(Student.auth_passcode == passcode).first():
        passcode = generate_passcode()

    student.auth_passcode = passcode
    student.status = "UNVERIFIED"
    db.commit()

    bot_phone = settings.apex_bot_phone.lstrip("+").replace(" ", "")
    click_to_chat_url = f"https://wa.me/{bot_phone}?text={passcode}"

    return GenerateOtpResponse(
        message=f"OTP generated for {student.first_name} {student.surname}",
        auth_passcode=passcode,
        bot_phone=settings.apex_bot_phone,
        click_to_chat_url=click_to_chat_url,
    )


@router.post("/bulk-import")
def bulk_import_students(
    payload: BulkStudentRequest,
    db: Session = Depends(get_db),
) -> dict:
    results = {"imported": [], "skipped": [], "errors": []}

    for s in payload.students:
        try:
            email = s.get("email", "").strip().lower()
            name = s.get("name", s.get("firstName", "Unknown"))
            name_parts = name.split(" ", 1)
            first_name = name_parts[0]
            surname = name_parts[1] if len(name_parts) > 1 else ""

            existing = db.query(Student).filter(Student.email == email).first()
            if existing:
                results["skipped"].append({"email": email, "reason": "already exists"})
                continue

            passcode = generate_passcode()
            while db.query(Student).filter(Student.auth_passcode == passcode).first():
                passcode = generate_passcode()

            student = Student(
                id=uuid4(),
                first_name=first_name,
                surname=surname,
                email=email,
                phone=s.get("phone", s.get("contact", "")),
                university=s.get("university", ""),
                field=None,
                study_year=None,
                auth_passcode=passcode,
                status="UNVERIFIED",
            )
            db.add(student)
            results["imported"].append({
                "email": email,
                "passcode": passcode,
                "name": f"{first_name} {surname}",
            })
        except Exception as e:
            results["errors"].append({"data": s, "error": str(e)})

    db.commit()
    return results