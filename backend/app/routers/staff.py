from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import ApexStaff, AuditLog, Student, Transporter
from ..schemas import OutboundMessage

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


from ..utils import normalize_phone


def _require_staff(db: Session, staff_phone: str) -> ApexStaff:
    normalized = normalize_phone(staff_phone)
    staff = db.query(ApexStaff).filter(ApexStaff.phone_number == normalized).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized staff member")
    return staff


class VetRequest(BaseModel):
    lead_id: str


class LoadRequest(BaseModel):
    lead_id: str
    truck_count: int


class PayRequest(BaseModel):
    student_id: str
    lead_id: str


class FraudRequest(BaseModel):
    student_id: str


class StudentFilter(BaseModel):
    status: str | None = None


def _audit(db: Session, actor_phone: str, event_type: str, payload: dict) -> None:
    db.add(AuditLog(
        id=uuid4(),
        event_type=event_type,
        actor_phone=actor_phone,
        payload=payload,
    ))
    db.commit()


@router.get("/pending")
def staff_pending(
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    _require_staff(db, x_staff_phone)
    leads = (
        db.query(Transporter)
        .filter(Transporter.status == "NEW_LEAD")
        .order_by(Transporter.created_at.asc())
        .limit(5)
        .all()
    )
    result = []
    for lead in leads:
        student = db.query(Student).filter(Student.id == lead.student_id).first()
        result.append({
            "lead_id": str(lead.id),
            "company_name": lead.company_name,
            "fleet_owner_phone": lead.fleet_owner_phone,
            "truck_count": lead.truck_count,
            "truck_type": lead.truck_type,
            "student_id": str(lead.student_id),
            "student_name": f"{student.first_name} {student.surname}" if student else "Unknown",
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        })
    return {"pending_leads": result}


@router.post("/vet")
def staff_vet(
    body: VetRequest,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    staff = _require_staff(db, x_staff_phone)
    lead = db.query(Transporter).filter(Transporter.id == body.lead_id).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.status != "NEW_LEAD":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Lead is already {lead.status}")
    lead.status = "VETTED"
    _audit(db, x_staff_phone, "STAFF_VETTED_LEAD", {"staff_name": staff.staff_name, "lead_id": str(lead.id)})
    return {"message": f"Lead {lead.id} marked as VETTED", "lead_id": str(lead.id), "company_name": lead.company_name}


@router.post("/load")
def staff_load(
    body: LoadRequest,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    staff = _require_staff(db, x_staff_phone)
    if body.truck_count < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Truck count must be a positive number")
    lead = db.query(Transporter).filter(Transporter.id == body.lead_id).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.status not in ("NEW_LEAD", "VETTED"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Lead is already {lead.status}")
    commission = body.truck_count * 1000
    lead.truck_count = body.truck_count
    lead.status = "LOADED"
    _audit(db, x_staff_phone, "STAFF_LOADED_LEAD", {
        "staff_name": staff.staff_name, "lead_id": str(lead.id),
        "loaded_count": body.truck_count, "commission": commission,
    })
    student = db.query(Student).filter(Student.id == lead.student_id).first()
    if student and student.whatsapp_number:
        from ..main import send_whatsapp_message
        import asyncio
        asyncio.create_task(send_whatsapp_message(
            student.whatsapp_number,
            f"🚚 Great news! {lead.company_name} truck loaded.\nCommission flagged: R{commission:,}\nUse *STATUS* to track your pipeline.",
        ))
    return {
        "message": f"Lead {lead.id} marked as LOADED",
        "lead_id": str(lead.id),
        "company_name": lead.company_name,
        "truck_count": body.truck_count,
        "commission": commission,
    }


@router.get("/payouts")
def staff_payouts(
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    _require_staff(db, x_staff_phone)
    leads = db.query(Transporter).filter(Transporter.status == "LOADED").order_by(Transporter.created_at.desc()).all()
    result = []
    for lead in leads:
        student = db.query(Student).filter(Student.id == lead.student_id).first()
        commission = (lead.truck_count or 0) * 1000
        result.append({
            "lead_id": str(lead.id),
            "company_name": lead.company_name,
            "student_id": str(lead.student_id),
            "student_name": f"{student.first_name} {student.surname}" if student else "Unknown",
            "student_phone": student.whatsapp_number if student else None,
            "truck_count": lead.truck_count,
            "commission": commission,
            "banking_details": student.auth_passcode if student else None,
        })
    return {"payouts": result}


@router.post("/pay")
def staff_pay(
    body: PayRequest,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    staff = _require_staff(db, x_staff_phone)
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    lead = db.query(Transporter).filter(Transporter.id == body.lead_id).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.status != "LOADED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Lead is {lead.status}, not LOADED")
    if str(lead.student_id) != body.student_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lead does not belong to this student")
    commission = (lead.truck_count or 0) * 1000
    lead.status = "PAID"
    _audit(db, x_staff_phone, "STAFF_PAID_LEAD", {
        "staff_name": staff.staff_name, "lead_id": str(lead.id),
        "student_id": body.student_id, "commission": commission,
    })
    if student.whatsapp_number:
        from ..main import send_whatsapp_message
        import asyncio
        asyncio.create_task(send_whatsapp_message(
            student.whatsapp_number,
            f"💰 R{commission:,} payout processed to your bank account!\nLead: {lead.company_name} ({lead.truck_count} trucks)",
        ))
    return {
        "message": f"Lead {lead.id} marked as PAID",
        "lead_id": str(lead.id),
        "company_name": lead.company_name,
        "commission": commission,
    }


@router.post("/fraud")
def staff_fraud(
    body: FraudRequest,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    staff = _require_staff(db, x_staff_phone)
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student.status = "PERMANENT_BAN"
    pending_leads = db.query(Transporter).filter(
        Transporter.student_id == student.id,
        Transporter.status.in_(["NEW_LEAD", "VETTED"]),
    ).all()
    banned_count = 0
    for lead in pending_leads:
        lead.status = "REJECTED_FRAUD"
        banned_count += 1
    _audit(db, x_staff_phone, "STAFF_FRAUD_BAN", {
        "staff_name": staff.staff_name,
        "student_id": body.student_id,
        "leads_banned": banned_count,
    })
    if student.whatsapp_number:
        from ..main import send_whatsapp_message
        import asyncio
        asyncio.create_task(send_whatsapp_message(
            student.whatsapp_number,
            "🚫 Your APEX Partnership account has been terminated due to policy violations.\nYou are no longer permitted to submit leads or interact with this service.",
        ))
    return {
        "message": f"Student {student.first_name} {student.surname} ({student.email}) has been PERMANENTLY BANNED",
        "student_id": body.student_id,
        "leads_banned": banned_count,
    }


@router.get("/students/{student_id}")
def staff_get_student(
    student_id: str,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    _require_staff(db, x_staff_phone)
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    leads = db.query(Transporter).filter(Transporter.student_id == student.id).order_by(Transporter.created_at.desc()).all()
    lead_list = []
    for lead in leads:
        lead_list.append({
            "lead_id": str(lead.id),
            "company_name": lead.company_name,
            "fleet_owner_phone": lead.fleet_owner_phone,
            "truck_count": lead.truck_count,
            "truck_type": lead.truck_type,
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        })
    return {
        "student_id": str(student.id),
        "first_name": student.first_name,
        "surname": student.surname,
        "email": student.email,
        "phone": student.phone,
        "whatsapp_number": student.whatsapp_number,
        "status": student.status,
        "tutorial_attempts": student.tutorial_attempts,
        "created_at": student.created_at.isoformat() if student.created_at else None,
        "leads": lead_list,
    }


@router.get("/students")
def staff_list_students(
    status: str | None = None,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    _require_staff(db, x_staff_phone)
    query = db.query(Student)
    if status:
        query = query.filter(Student.status == status)
    students = query.order_by(Student.created_at.desc()).all()
    result = []
    for s in students:
        lead_count = db.query(Transporter).filter(Transporter.student_id == s.id).count()
        result.append({
            "student_id": str(s.id),
            "first_name": s.first_name,
            "surname": s.surname,
            "email": s.email,
            "whatsapp_number": s.whatsapp_number,
            "status": s.status,
            "lead_count": lead_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"students": result}


@router.get("/students/{student_id}/leads")
def staff_student_leads(
    student_id: str,
    x_staff_phone: str = Header(..., alias="X-Staff-Phone"),
    db: Session = Depends(get_db),
) -> dict:
    _require_staff(db, x_staff_phone)
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    leads = db.query(Transporter).filter(Transporter.student_id == student.id).order_by(Transporter.created_at.desc()).all()
    result = []
    for lead in leads:
        result.append({
            "lead_id": str(lead.id),
            "company_name": lead.company_name,
            "fleet_owner_phone": lead.fleet_owner_phone,
            "truck_count": lead.truck_count,
            "truck_type": lead.truck_type,
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        })
    return {"student_id": str(student.id), "leads": result}