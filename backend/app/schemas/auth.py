from pydantic import BaseModel, EmailStr, Field


class VerificationSendResponse(BaseModel):
    status: str


class VerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=10)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetSubmit(BaseModel):
    token: str = Field(min_length=10)
    password: str = Field(min_length=8, max_length=256)
