from fastapi import APIRouter, Header, status
from fastapi.responses import JSONResponse

from auth.auth_service import auth_service
from auth.dependencies import bearer_token
from models.schemas import LoginRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest):
    user = auth_service.login(body.id, body.password)
    if not user:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"success": False, "message": "아이디 또는 비밀번호가 올바르지 않습니다."},
        )
    return {"success": True, "role": user.role, "token": user.token}


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    auth_service.logout(bearer_token(authorization))
    return {"success": True}
