import httpx
import re
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from uuid import uuid4

from .config import settings
from .database import get_db
from .models import ApexStaff, AuditLog, Student
from .routers import students
from .schemas import InboundMessage, OutboundMessage, WebhookResponse

app = FastAPI(title="APEX Partnership API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(students.router)

PRACTICE_PHONE = "27820000000"
PRACTICE_COMPANY = "APEX PRACTICE LOGISTICS"
PRACTICE_TRUCK_COUNT = 5


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def send_whatsapp_message(
    recipient_phone: str,
    text_content: str,
    media_url: str | None = None,
    media_filename: str | None = None,
) -> None:
    async with httpx.AsyncClient(base_url=settings.baileys_gateway_url, timeout=10) as client:
        response = await client.post("/messages", json={
            "recipient_phone": recipient_phone,
            "text_content": text_content,
            "media_url": media_url,
            "media_filename": media_filename,
        })
    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail="Baileys gateway rejected message")


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


async def notify_staff_of_hold(db: Session, student: Student, sender_phone: str) -> None:
    chat_phone = re.sub(r"\D", "", sender_phone)
    message = (
        "⚠️ Tutorial escalation\n\n"
        f"{student.first_name} {student.surname} ({student.email}) reached 3 failed attempts.\n"
        f"WhatsApp: {sender_phone}\n"
        f"Chat link: https://wa.me/{chat_phone}\n"
        "Please review and contact the student before reactivation."
    )
    recipients = [settings.apex_staff_group_phone] if settings.apex_staff_group_phone else [
        staff.phone_number for staff in db.query(ApexStaff).filter(ApexStaff.role.in_(["ADMIN", "STAFF"])).all()
    ]
    for recipient in recipients:
        if recipient:
            await send_whatsapp_message(recipient, message)


@app.post("/webhook/whatsapp", response_model=WebhookResponse, status_code=status.HTTP_202_ACCEPTED)
async def whatsapp_webhook(
    message: InboundMessage,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
) -> WebhookResponse:
    if x_webhook_secret != settings.webhook_shared_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    inbound_id = uuid4()
    db.add(AuditLog(
        id=inbound_id,
        event_type="WHATSAPP_INBOUND",
        actor_phone=message.sender_phone,
        payload=message.model_dump(mode="json"),
    ))
    db.commit()

    if message.text_content.startswith("AUTH-"):
        student = db.query(Student).filter(Student.auth_passcode == message.text_content.strip()).first()
        if student:
            existing = db.query(Student).filter(
                Student.whatsapp_number == message.sender_phone,
                Student.id != student.id
            ).first()
            if existing:
                db.add(AuditLog(
                    event_type="OTP_NUMBER_HIJACK_ATTEMPT",
                    actor_phone=message.sender_phone,
                    payload={"passcode": message.text_content, "student_id": str(student.id), "bound_to": str(existing.id)},
                ))
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    "❌ This WhatsApp number is already linked to another account.",
                )
                return WebhookResponse(accepted=True, message_id=inbound_id)
            if student.whatsapp_number == message.sender_phone:
                await send_whatsapp_message(
                    message.sender_phone,
                    "ℹ️ This number is already linked to your account.",
                )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            student.whatsapp_number = message.sender_phone
            student.auth_passcode = None
            student.status = "TUTORIAL"
            db.add(AuditLog(
                event_type="STUDENT_PHONE_LINKED",
                actor_phone=message.sender_phone,
                payload={"student_id": str(student.id)},
            ))
            db.commit()

            await send_whatsapp_message(
                message.sender_phone,
                "🎉 Welcome to APEX Partnership!\n\n"
                "You're now verified. Type *TUTORIAL* to start the onboarding guide.",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        db.add(AuditLog(
            event_type="INVALID_OTP_ATTEMPT",
            actor_phone=message.sender_phone,
            payload={"passcode": message.text_content},
        ))
        db.commit()
        await send_whatsapp_message(
            message.sender_phone,
            "❌ Invalid passcode. Please check and try again.",
        )

    if message.text_content.strip().upper() == "TUTORIAL":
        student = db.query(Student).filter(
            Student.whatsapp_number == message.sender_phone,
            Student.status == "TUTORIAL",
        ).first()
        if student:
            await send_whatsapp_message(
                message.sender_phone,
                "Here is your APEX onboarding guide. Read it before the practice test.\n\n"
                "When you are ready, reply *READY*.",
                media_url=settings.tutorial_pdf_path,
                media_filename="APEX-Partnership-Tutorial.pdf",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

    tutorial_student = db.query(Student).filter(
        Student.whatsapp_number == message.sender_phone,
        Student.status == "TUTORIAL",
    ).first()
    if tutorial_student and message.text_content.strip().upper() == "READY":
        await send_whatsapp_message(
            message.sender_phone,
            "Practice test: reply in one message using exactly:\n\n"
            "PHONE: 27820000000\n"
            "COMPANY: APEX PRACTICE LOGISTICS\n"
            "TRUCKS: 5",
        )
        return WebhookResponse(accepted=True, message_id=inbound_id)

    if tutorial_student:
        errors = practice_submission_errors(parse_practice_submission(message.text_content))
        if not errors:
            tutorial_student.status = "ACTIVE"
            db.add(AuditLog(
                event_type="TUTORIAL_PASSED",
                actor_phone=message.sender_phone,
                payload={"student_id": str(tutorial_student.id), "attempts": tutorial_student.tutorial_attempts + 1},
            ))
            db.commit()
            await send_whatsapp_message(
                message.sender_phone,
                "✅ Tutorial passed! Your account is now ACTIVE. You may submit transporter leads.",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        tutorial_student.tutorial_attempts += 1
        attempt = tutorial_student.tutorial_attempts
        if attempt >= 3:
            tutorial_student.status = "ADMIN_HOLD"
            event_type = "TUTORIAL_ESCALATED"
            reply = "❌ That was attempt 3. Your account is now on ADMIN_HOLD. APEX staff will contact you."
        else:
            event_type = "TUTORIAL_FAILED"
            remaining = 3 - attempt
            reply = (
                f"❌ Attempt {attempt} failed: {'; '.join(errors)}.\n"
                f"You have {remaining} attempt{'s' if remaining != 1 else ''} remaining. Reply READY for the format."
            )
        db.add(AuditLog(
            event_type=event_type,
            actor_phone=message.sender_phone,
            payload={"student_id": str(tutorial_student.id), "attempt": attempt, "errors": errors},
        ))
        db.commit()
        await send_whatsapp_message(message.sender_phone, reply)
        if attempt >= 3:
            await notify_staff_of_hold(db, tutorial_student, message.sender_phone)
        return WebhookResponse(accepted=True, message_id=inbound_id)

    held_student = db.query(Student).filter(
        Student.whatsapp_number == message.sender_phone,
        Student.status == "ADMIN_HOLD",
    ).first()
    if held_student:
        await send_whatsapp_message(
            message.sender_phone,
            "Your account is currently on ADMIN_HOLD. Please wait for APEX staff to review it.",
        )
        return WebhookResponse(accepted=True, message_id=inbound_id)

    return WebhookResponse(accepted=True, message_id=inbound_id)


@app.post("/api/v1/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(message: OutboundMessage) -> dict[str, str | bool]:
    async with httpx.AsyncClient(base_url=settings.baileys_gateway_url, timeout=10) as client:
        response = await client.post("/messages", json=message.model_dump())
    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail="Baileys gateway rejected message")
    return {"accepted": True, "gateway_message_id": response.json().get("message_id", "")}
