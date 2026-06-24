from collections.abc import Generator 

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False,autoflush=False, bind=engine)


#데이터 베이스를 사용하겠다 선언
class Base(DeclarativeBase):
    pass

#db를 사용할때 방을 파겠다 즉 섹션 선언
def get_db() -> Generator[Session,None,None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()