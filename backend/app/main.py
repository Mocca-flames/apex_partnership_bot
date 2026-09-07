import httpx
import re
import time
from collections import defaultdict
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from uuid import uuid4

from .config import settings
from .database import get_db
from .models import ApexStaff, AuditLog, LeadSubmissionSession, Student, Transporter
from .routers import students
from .schemas import InboundMessage, OutboundMessage, WebhookResponse

app = FastAPI(title="APEX Partnership API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(students.router)

PRACTICE_PHONE = "27820000000"
PRACTICE_COMPANY = "APEX PRACTICE LOGISTICS"
PRACTICE_TRUCK_COUNT = 5

RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
_rate_limits: dict[str, list[float]] = defaultdict(list)


def _rate_check(sender_phone: str) -> bool:
    now = time.time()
    _rate_limits[sender_phone] = [t for t in _rate_limits[sender_phone] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[sender_phone]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[sender_phone].append(now)
    return True


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


def lead_status_label(status_val: str) -> str:
    return {
        "NEW_LEAD": "Under Review",
        "VETTED": "Verified (Awaiting Load)",
        "LOADED": "Truck Loaded (Commission Pending)",
        "PAID": "Commission Paid!",
    }.get(status_val, "Closed / Rejected" if status_val.startswith("REJECTED_") else status_val.title())


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


def _is_staff(db: Session, phone: str) -> ApexStaff | None:
    return db.query(ApexStaff).filter(ApexStaff.phone_number == phone).first()


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

    if not _rate_check(message.sender_phone):
        await send_whatsapp_message(message.sender_phone, "⏳ You're sending messages too fast. Please wait a moment.")
        return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── IDENTITY GATE ──────────────────────────────────────────────────────
    # Resolve who is sending: staff, linked student, unlinked student, or unknown.
    staff_member = _is_staff(db, message.sender_phone)
    linked_student = db.query(Student).filter(
        Student.whatsapp_number == message.sender_phone,
    ).first()

    unlinked_student = None
    if not staff_member and not linked_student:
        unlinked_student = db.query(Student).filter(
            Student.phone == message.sender_phone,
            Student.whatsapp_number.is_(None),
        ).first()
    # ────────────────────────────────────────────────────────────────────────

    # ── STAFF ──────────────────────────────────────────────────────────────
    if staff_member:
        text = message.text_content.strip()
        command = text.upper()

        # AUTH- from staff = still allowed (they may need to link too)
        if message.text_content.startswith("AUTH-"):
            pass  # fall through to AUTH handler below

        elif command.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd == "/pending":
                leads = (
                    db.query(Transporter)
                    .filter(Transporter.status == "NEW_LEAD")
                    .order_by(Transporter.created_at.asc())
                    .limit(5)
                    .all()
                )
                if not leads:
                    await send_whatsapp_message(message.sender_phone, "✅ No pending leads in the queue.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lines = ["📋 Pending leads (newest first):"]
                for lead in leads:
                    student = db.query(Student).filter(Student.id == lead.student_id).first()
                    sname = f"{student.first_name} {student.surname}" if student else "Unknown"
                    lines.append(
                        f"\nID: {lead.id}\n"
                        f"Company: {lead.company_name}\n"
                        f"Fleet phone: {lead.fleet_owner_phone}\n"
                        f"Trucks: {lead.truck_count} ({lead.truck_type})\n"
                        f"Submitted by: {sname}\n"
                        f"Status: {lead.status}"
                    )
                await send_whatsapp_message(message.sender_phone, "\n".join(lines))
                db.add(AuditLog(
                    event_type="STAFF_VIEWED_PENDING",
                    actor_phone=message.sender_phone,
                    payload={"staff_name": staff_member.staff_name, "count": len(leads)},
                ))
                db.commit()
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if cmd == "/vet":
                if len(args) != 1:
                    await send_whatsapp_message(message.sender_phone, "Usage: /vet [lead_id]")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lead = db.query(Transporter).filter(Transporter.id == args[0]).first()
                if not lead:
                    await send_whatsapp_message(message.sender_phone, "❌ Lead not found.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if lead.status != "NEW_LEAD":
                    await send_whatsapp_message(message.sender_phone, f"❌ Lead is already {lead.status}.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lead.status = "VETTED"
                db.add(AuditLog(
                    event_type="STAFF_VETTED_LEAD",
                    actor_phone=message.sender_phone,
                    payload={"staff_name": staff_member.staff_name, "lead_id": str(lead.id)},
                ))
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    f"✅ Lead {lead.id} marked as VETTED.\nCompany: {lead.company_name}\nFleet phone: {lead.fleet_owner_phone}",
                )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if cmd == "/load":
                if len(args) < 2:
                    await send_whatsapp_message(message.sender_phone, "Usage: /load [lead_id] [truck_count]")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lead = db.query(Transporter).filter(Transporter.id == args[0]).first()
                if not lead:
                    await send_whatsapp_message(message.sender_phone, "❌ Lead not found.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if lead.status not in ("NEW_LEAD", "VETTED"):
                    await send_whatsapp_message(message.sender_phone, f"❌ Lead is already {lead.status}.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if not args[1].isdigit() or int(args[1]) < 1:
                    await send_whatsapp_message(message.sender_phone, "❌ Truck count must be a positive number.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                loaded_count = int(args[1])
                commission = loaded_count * 1000
                lead.truck_count = loaded_count
                lead.status = "LOADED"
                db.add(AuditLog(
                    event_type="STAFF_LOADED_LEAD",
                    actor_phone=message.sender_phone,
                    payload={"staff_name": staff_member.staff_name, "lead_id": str(lead.id), "loaded_count": loaded_count, "commission": commission},
                ))
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    f"✅ Lead {lead.id} marked as LOADED.\n"
                    f"Company: {lead.company_name}\n"
                    f"Trucks loaded: {loaded_count}\n"
                    f"Commission: R{commission:,}",
                )
                student = db.query(Student).filter(Student.id == lead.student_id).first()
                if student and student.whatsapp_number:
                    await send_whatsapp_message(
                        student.whatsapp_number,
                        f"🚚 Great news! {lead.company_name} truck loaded.\n"
                        f"Commission flagged: R{commission:,}\n"
                        "Use *STATUS* to track your pipeline.",
                    )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if cmd == "/payouts":
                leads = db.query(Transporter).filter(Transporter.status == "LOADED").order_by(Transporter.created_at.desc()).all()
                if not leads:
                    await send_whatsapp_message(message.sender_phone, "✅ No loaded leads awaiting payout.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lines = ["💰 Payouts pending:"]
                for lead in leads:
                    student = db.query(Student).filter(Student.id == lead.student_id).first()
                    sname = f"{student.first_name} {student.surname}" if student else "Unknown"
                    sid = str(student.id) if student else "N/A"
                    commission = (lead.truck_count or 0) * 1000
                    lines.append(
                        f"\nLead: {lead.id}\n"
                        f"Company: {lead.company_name}\n"
                        f"Student: {sname} (ID: {sid})\n"
                        f"Trucks: {lead.truck_count}\n"
                        f"Commission: R{commission:,}"
                    )
                await send_whatsapp_message(message.sender_phone, "\n".join(lines))
                db.add(AuditLog(
                    event_type="STAFF_VIEWED_PAYOUTS",
                    actor_phone=message.sender_phone,
                    payload={"staff_name": staff_member.staff_name, "count": len(leads)},
                ))
                db.commit()
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if cmd == "/pay":
                if len(args) != 2:
                    await send_whatsapp_message(message.sender_phone, "Usage: /pay [student_id] [lead_id]")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                student = db.query(Student).filter(Student.id == args[0]).first()
                if not student:
                    await send_whatsapp_message(message.sender_phone, "❌ Student not found.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                lead = db.query(Transporter).filter(Transporter.id == args[1]).first()
                if not lead:
                    await send_whatsapp_message(message.sender_phone, "❌ Lead not found.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if lead.status != "LOADED":
                    await send_whatsapp_message(message.sender_phone, f"❌ Lead is {lead.status}, not LOADED.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                if str(lead.student_id) != args[0]:
                    await send_whatsapp_message(message.sender_phone, "❌ Lead does not belong to this student.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                commission = (lead.truck_count or 0) * 1000
                lead.status = "PAID"
                db.add(AuditLog(
                    event_type="STAFF_PAID_LEAD",
                    actor_phone=message.sender_phone,
                    payload={"staff_name": staff_member.staff_name, "lead_id": str(lead.id), "student_id": args[0], "commission": commission},
                ))
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    f"✅ Lead {lead.id} marked as PAID.\n"
                    f"Company: {lead.company_name}\n"
                    f"Commission: R{commission:,}",
                )
                if student.whatsapp_number:
                    await send_whatsapp_message(
                        student.whatsapp_number,
                        f"💰 R{commission:,} payout processed to your bank account!\n"
                        f"Lead: {lead.company_name} ({lead.truck_count} trucks)",
                    )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            if cmd == "/fraud":
                if len(args) != 1:
                    await send_whatsapp_message(message.sender_phone, "Usage: /fraud [student_id]")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                student = db.query(Student).filter(Student.id == args[0]).first()
                if not student:
                    await send_whatsapp_message(message.sender_phone, "❌ Student not found.")
                    return WebhookResponse(accepted=True, message_id=inbound_id)
                student.status = "PERMANENT_BAN"
                pending_leads = db.query(Transporter).filter(
                    Transporter.student_id == student.id,
                    Transporter.status.in_(["NEW_LEAD", "VETTED"]),
                ).all()
                banned_count = 0
                for lead in pending_leads:
                    lead.status = "REJECTED_FRAUD"
                    banned_count += 1
                db.add(AuditLog(
                    event_type="STAFF_FRAUD_BAN",
                    actor_phone=message.sender_phone,
                    payload={
                        "staff_name": staff_member.staff_name,
                        "student_id": args[0],
                        "leads_banned": banned_count,
                    },
                ))
                db.commit()
                await send_whatsapp_message(
                    message.sender_phone,
                    f"🚫 Student {student.first_name} {student.surname} ({student.email}) has been PERMANENTLY BANNED.\n"
                    f"Leads rejected: {banned_count}",
                )
                if student.whatsapp_number:
                    await send_whatsapp_message(
                        student.whatsapp_number,
                        "🚫 Your APEX Partnership account has been terminated due to policy violations.\n"
                        "You are no longer permitted to submit leads or interact with this service.",
                    )
                return WebhookResponse(accepted=True, message_id=inbound_id)

            await send_whatsapp_message(
                message.sender_phone,
                "❓ Unknown command.\n\n"
                "Staff commands:\n"
                "/pending - View unvetted leads\n"
                "/vet [id] - Mark lead as vetted\n"
                "/load [id] [trucks] - Mark lead as loaded\n"
                "/payouts - View pending payouts\n"
                "/pay [student_id] [lead_id] - Process payout\n"
                "/fraud [student_id] - Ban student",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        # Staff sent a non-command non-AUTH message — ignore
        return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── UNKNOWN SENDER (not in staff table, not a linked student) ───────────
    if not linked_student and not unlinked_student:
        db.add(AuditLog(
            event_type="UNKNOWN_SENDER_IGNORED",
            actor_phone=message.sender_phone,
            payload={"text_preview": message.text_content[:100]},
        ))
        db.commit()
        return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── UNLINKED STUDENT (signed up, phone not bound yet) ──────────────────
    if unlinked_student:
        # Allow AUTH- passcode to link their phone
        if message.text_content.startswith("AUTH-"):
            pass  # fall through to AUTH handler below
        else:
            # Prompt them with their OTP so they can link
            if unlinked_student.auth_passcode:
                await send_whatsapp_message(
                    message.sender_phone,
                    f"👋 Welcome {unlinked_student.first_name}!\n\n"
                    f"Your verification code is: *{unlinked_student.auth_passcode}*\n\n"
                    "Send this code back to link your WhatsApp to your APEX account.",
                )
            else:
                await send_whatsapp_message(
                    message.sender_phone,
                    f"👋 Welcome {unlinked_student.first_name}!\n\n"
                    "Your account is pending verification.\n"
                    "Please contact APEX staff to receive your verification code.",
                )
            return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── AUTH PASSCODE HANDLER (staff + linked + unlinked all converge here) ─
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
        return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── LINKED STUDENT ONLY BELOW ──────────────────────────────────────────
    # From here on, only linked students (whatsapp_number matches) proceed.

    if linked_student.status == "PERMANENT_BAN":
        await send_whatsapp_message(
            message.sender_phone,
            "🚫 Your account has been permanently terminated. You cannot use this service.",
        )
        return WebhookResponse(accepted=True, message_id=inbound_id)

    if linked_student.status == "ADMIN_HOLD":
        await send_whatsapp_message(
            message.sender_phone,
            "Your account is currently on ADMIN_HOLD. Please wait for APEX staff to review it.",
        )
        return WebhookResponse(accepted=True, message_id=inbound_id)

    text = message.text_content.strip()
    command = text.upper()

    # ── TUTORIAL STATE ─────────────────────────────────────────────────────
    if linked_student.status == "TUTORIAL":
        if command == "TUTORIAL":
            await send_whatsapp_message(
                message.sender_phone,
                "Here is your APEX onboarding guide. Read it before the practice test.\n\n"
                "When you are ready, reply *READY*.",
                media_url=settings.tutorial_pdf_path,
                media_filename="APEX-Partnership-Tutorial.pdf",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        if command == "READY":
            await send_whatsapp_message(
                message.sender_phone,
                "Practice test: reply in one message using exactly:\n\n"
                "PHONE: 27820000000\n"
                "COMPANY: APEX PRACTICE LOGISTICS\n"
                "TRUCKS: 5",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        # Practice test submission
        errors = practice_submission_errors(parse_practice_submission(message.text_content))
        if not errors:
            linked_student.status = "ACTIVE"
            db.add(AuditLog(
                event_type="TUTORIAL_PASSED",
                actor_phone=message.sender_phone,
                payload={"student_id": str(linked_student.id), "attempts": linked_student.tutorial_attempts + 1},
            ))
            db.commit()
            await send_whatsapp_message(
                message.sender_phone,
                "✅ Tutorial passed! Your account is now ACTIVE. You may submit transporter leads.",
            )
            return WebhookResponse(accepted=True, message_id=inbound_id)

        linked_student.tutorial_attempts += 1
        attempt = linked_student.tutorial_attempts
        if attempt >= 3:
            linked_student.status = "ADMIN_HOLD"
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
            payload={"student_id": str(linked_student.id), "attempt": attempt, "errors": errors},
        ))
        db.commit()
        await send_whatsapp_message(message.sender_phone, reply)
        if attempt >= 3:
            await notify_staff_of_hold(db, linked_student, message.sender_phone)
        return WebhookResponse(accepted=True, message_id=inbound_id)

    # ── ACTIVE STATE ───────────────────────────────────────────────────────
    if linked_student.status == "ACTIVE":
        if command in {"/STATUS", "STATUS"}:
            leads = db.query(Transporter).filter(Transporter.student_id == linked_student.id).order_by(Transporter.created_at.desc()).all()
            await send_whatsapp_message(message.sender_phone, lead_status_summary(leads))
            return WebhookResponse(accepted=True, message_id=inbound_id)

        session = db.query(LeadSubmissionSession).filter(
            LeadSubmissionSession.student_id == linked_student.id,
        ).first()
        if not session and command in {"LEAD", "SUBMIT LEAD", "/LEAD", "NEW LEAD"}:
            session = LeadSubmissionSession(student_id=linked_student.id, step="PHONE")
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
                        payload={"fleet_owner_phone": phone, "student_id": str(linked_student.id)},
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
                    student_id=linked_student.id,
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
                    payload={"student_id": str(linked_student.id), "company_name": lead.company_name},
                ))
                db.commit()
                await send_whatsapp_message(message.sender_phone, "✅ Lead received and queued for APEX review. Reply *STATUS* to track it.")
                await notify_staff_of_lead(db, lead, linked_student)
                return WebhookResponse(accepted=True, message_id=inbound_id)

        await send_whatsapp_message(message.sender_phone, "Reply *LEAD* to submit a transporter or *STATUS* to view your pipeline.")
        return WebhookResponse(accepted=True, message_id=inbound_id)

    return WebhookResponse(accepted=True, message_id=inbound_id)


@app.post("/api/v1/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(message: OutboundMessage) -> dict[str, str | bool]:
    async with httpx.AsyncClient(base_url=settings.baileys_gateway_url, timeout=10) as client:
        response = await client.post("/messages", json=message.model_dump())
    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail="Baileys gateway rejected message")
    return {"accepted": True, "gateway_message_id": response.json().get("message_id", "")}
