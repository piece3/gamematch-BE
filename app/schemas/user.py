import re
from unittest.util import _MAX_LENGTH
from app.config import settings
from pydantic import BaseModel,ConfigDict,EmailStr,Field,field_validator
from datetime import datetime


#회원가입 양식
class UserCreate(BaseModel):
    """회원가입 요청 형식"""
    
    #회원 가입 조건들
    email: EmailStr
    nickname: str = Field(min_length=2,max_length=50)
    password: str = Field(min_length=8,max_length=128)

    #email 도메인 조건 설정
    @field_validator("email")
    @classmethod
    def email_domain(cls, v:str) -> str:
        email = v.lower()
        domain = settings.allowed_email_domain.lower()
        if not email.endswith(f"@{domain}"):
            raise ValueError(f"이메일은 @{domain} 만 사용할 수 있습니다.")
        return email

    #password 조건 설정
    @field_validator("password")
    @classmethod
    def password_option(cls, v:str) -> str :
        if not re.search(r"[a-z]",v):
            raise ValueError("비밀번호에 소문자가 필요합니다.")
        if not re.search(r"\d",v):
            raise ValueError("비밀번호에 숫자가 필요합니다.")
        if not re.search(r"[!@#$%^&*(),./?]",v):
            raise ValueError("비밀번호에 특수문자 (! @ # $ % ^ & * ( ) , . / ? ) 가 필요합니다")
        return v
            




#로그인요청에 대한 양식
class UserLogin(BaseModel):
    """로그인 요청 방식"""

    email: EmailStr
    password: str


#로그인 성공시 작성할 양식
class UserResponse(BaseModel):
    """회원 정보 응답"""
    
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    nickname: str
    is_verified: bool
    created_at: datetime