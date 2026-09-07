import httpx
import re
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from uuid import uuid4

from .config import settings
from .database import get_db
from .models import ApexStaff, AuditLog, LeadSubmissionSession, Student, Transporter
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
    buttons: list[str] | None = None,
) -> None:
    async with httpx.AsyncClient(base_url=settings.baileys_gateway_url, timeout=10) as client:
        response = await client.post("/messages", json={
            "recipient_phone": recipient_phone,
            "text_content": text_content,
            "media_url": media_url,
            "media_filename": media_filename,
            "buttons": buttons,
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


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def lead_status_label(status: str) -> str:
    return {
        "NEW_LEAD": "Under Review",
        "VETTED": "Verified (Awaiting Load)",
        "LOADED": "Truck Loaded (Commission Pending)",
        "PAID": "Commission Paid!",
    }.get(status, "Closed / Rejected" if status.startswith("REJECTED_") else status.title())


def lead_status_summary(leads: list[Transporter]) -> str:
    if not leads:
        return "📋 You have no submitted leads yet. Reply *LEAD* to submit one."
    lines = ["📋 Your APEX lead pipeline:"]
    for lead in leads:
        lines.append(f"• {lead.company_name} ({lead.truck_count} trucks): {lead_status_label(lead.status)}")
    return "\n".join(lines)


async def notify_staff_of_lead(db: Session, lead: Transporter, student: Student) -> None:
    message = (
        "📥 New transporter lead\n\n"
        f"Company: {lead.company_name}\n"
        f"Fleet manager: {lead.fleet_owner_phone}\n"
        f"Trucks: {lead.truck_count}\n"
        f"Type: {lead.truck_type}\n"
        f"Student: {student.first_name} {student.surname}\n"
        f"Student ID: {student.id}\n"
        "Use /pending to review the queue."
    )
    recipients = [settings.apex_staff_group_phone] if settings.apex_staff_group_phone else [
        staff.phone_number for staff in db.query(ApexStaff).filter(ApexStaff.role.in_(["ADMIN", "STAFF"])).all()
    ]
    for recipient in recipients:
        if recipient:
            await send_whatsapp_message(recipient, message)


def lead_phone_is_registered(db: Session, phone: str) -> bool:
    normalized = normalize_phone(phone)
    return any(normalize_phone(lead.fleet_owner_phone) == normalized for lead in db.query(Transporter).all())


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

    active_student = db.query(Student).filter(
        Student.whatsapp_number == message.sender_phone,
        Student.status == "ACTIVE",
    ).first()
    if active_student:
        text = message.text_content.strip()
        command = text.upper()
        if command in {"/STATUS", "STATUS"}:
            leads = db.query(Transporter).filter(Transporter.student_id == active_student.id).order_by(Transporter.created_at.desc()).all()
            await send_whatsapp_message(message.sender_phone, lead_status_summary(leads))
            return WebhookResponse(accepted=True, message_id=inbound_id)

        session = db.query(LeadSubmissionSession).filter(
            LeadSubmissionSession.student_id == active_student.id,
        ).first()
        if not session and command in {"LEAD", "SUBMIT LEAD", "/LEAD", "NEW LEAD"}:
            session = LeadSubmissionSession(student_id=active_student.id, step="PHONE")
            db.add(session)
            db.commit()
            await send_whatsapp_message(
                message.sender_phone,
                "Let's capture a transporter lead. Send the fleet owner / manager cellphone number.",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        if session:
            if session.step == "PHONE":
                phone = normalize_phone(text)
                if not 10 <= len(phone) <= 15:
                    await send_whatsapp_message(message.sender_phone, "Please send a valid cellphone number, including the country code if needed.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if lead_phone_is_registered(db, phone):
                    db.delete(session)
                    db.add(AuditLog(
                        event_type="DUPLICATE_TRANSPORTER_REJECTED",
                        actor_phone=message.sender_phone,
                        payload={"fleet_owner_phone": phone, "student_id": str(active_student.id)},
                    ))
                    db.commit()
                    await send_whatsapp_message(message.sender_phone, "❌ Transporter phone number already registered in APEX network.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                session.fleet_owner_phone = phone
                session.step = "COMPANY"
                db.commit()
                await send_whatsapp_message(message.sender_phone, "What is the transporter company name?")
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if session.step == "COMPANY":
                if not text or len(text) > 255:
                    await send_whatsapp_message(message.sender_phone, "Please send a company name up to 255 characters.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                session.company_name = text
                session.step = "TRUCK_COUNT"
                db.commit()
                await send_whatsapp_message(message.sender_phone, "How many trucks does the transporter operate? Send a whole number.")
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if session.step == "TRUCK_COUNT":
                if not text.isdigit() or int(text) < 1 or int(text) > 10000:
                    await send_whatsapp_message(message.sender_phone, "Please send a valid truck count as a whole number.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                session.truck_count = int(text)
                session.step = "TRUCK_TYPE"
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    "Select the truck type:",
                    buttons=["Superlink", "Lowbed", "Mixed"],
                )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if session.step == "TRUCK_TYPE":
                truck_type = text.upper().replace("-", "")
                truck_types = {"SUPERLINK": "SUPERLINK", "LOWBED": "LOWBED", "MIXED": "MIXED", "1": "SUPERLINK", "2": "LOWBED", "3": "MIXED"}
                if truck_type not in truck_types:
                    await send_whatsapp_message(message.sender_phone, "Please choose Superlink, Lowbed, or Mixed.", buttons=["Superlink", "Lowbed", "Mixed"])
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lead = Transporter(
                    student_id=active_student.id,
                    company_name=session.company_name or "",
                    fleet_owner_phone=session.fleet_owner_phone or "",
                    truck_count=session.truck_count,
                    truck_type=truck_types[truck_type],
                    status="NEW_LEAD",
                )
                db.add(lead)
                db.delete(session)
                db.add(AuditLog(
                    event_type="LEAD_SUBMITTED",
                    actor_phone=message.sender_phone,
                    payload={"student_id": str(active_student.id), "company_name": lead.company_name},
                ))
                db.commit()
                await send_whatsapp_message(message.sender_phone, "✅ Lead received and queued for APEX review. Reply *STATUS* to track it.")
                await notify_staff_of_lead(db, lead, active_student)
                return WebhookResponse(accepted=True, message_id=inbound_id)

        await send_whatsapp_message(message.sender_phone, "Reply *LEAD* to submit a transporter or *STATUS* to view your pipeline.")
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
