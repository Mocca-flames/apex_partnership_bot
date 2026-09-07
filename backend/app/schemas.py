from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class InboundMessage(BaseModel):
    sender_phone: str = Field(min_length=1, max_length=30)
    text_content: str = ""
    media_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class OutboundMessage(BaseModel):
    recipient_phone: str = Field(min_length=1, max_length=30)
    text_content: str = Field(min_length=1)
    media_url: str | None = None
    media_filename: str | None = None
    buttons: list[str] | None = None


class WebhookResponse(BaseModel):
    accepted: bool
    message_id: UUID


class StudentSignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=30)
    university: str | None = Field(default=None, max_length=255)
    field: str | None = Field(default=None, max_length=255)
    study_year: int | None = Field(default=None, ge=1, le=10)


class StudentSignupResponse(BaseModel):
    auth_passcode: str
    bot_phone: str
    click_to_chat_url: str
