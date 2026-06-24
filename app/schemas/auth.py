from pydantic import BaseModel



#로그인 성공시 응답할 양식
class Token(BaseModel):
    """로그인 성공 응답"""

    access_token: str
    token_type: str = "bearer"


#토큰의 주인을 나타내는 것
class TokenPayLoad(BaseModel):
    """JWT >> PAYLOAD 결과"""

    sub: str | None = None

