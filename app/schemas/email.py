from pydantic import BaseModel, EmailStr


class MessageResponse(BaseModel):
    message: str


class VerifyEmailResponse(BaseModel):
    message: str
    is_verified: bool


class ResendVerificationRequest(BaseModel):
    email: EmailStr