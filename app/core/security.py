from datetime import UTC,datetime,timedelta
from jose import JWTError, jwt                  #토큰 발행과 해독
from passlib.context import CryptContext        #비밀번호 해쉬화
from app.config import settings
from app.schemas.auth import TokenPayLoad


#암호화 방식 (bcrypt를 사용) (만약 암호화방식이 업데이트되면 모두 최신화)
pwd_context = CryptContext(schemes=["bcrypt"],deprecated="auto")

#비밀번호 암호화
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

#비밀번호가 맞는지 확인
def verify_password(plain_password: str,hashed_password: str) -> bool:
    return pwd_context.verify(plain_password,hashed_password)

#sub에 맞는 토큰 및 유효기간 생성
def create_access_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject ,"exp": expire }
    return jwt.encode(payload,settings.secret_key,algorithm=settings.algorithm)


#token을 디코딩 및 대조 만약 불일치면 에러
def decode_access_token(token: str) -> TokenPayLoad:
    try:
        payload = jwt.decode(token,settings.secret_key,algorithms=[settings.algorithm])
        return TokenPayLoad(sub=payload.get("sub"))
    except JWTError as exc:
        raise ValueError("Invalid token") from exc