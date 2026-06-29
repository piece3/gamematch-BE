from fastapi import FastAPI


from contextlib import asynccontextmanager
from app.database import Base, engine
import app.models
from app.api.auth import router as auth_router





@asynccontextmanager            #비동기를 쓰겠다

#앱을 실행할때 시작되는 명령어와 종료 직전에 명령어 = lifespan

async def lifespan(_: FastAPI):
    
    yield

app = FastAPI(lifespan=lifespan)      #lifespan == 위에 말한것

app.include_router(auth_router)


#서버 상태가 온라인인지 확인
@app.get("/health")
def health_check():
    return {"status": "ok"}
