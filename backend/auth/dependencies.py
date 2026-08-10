from fastapi import Depends, Header, HTTPException, status

from auth.auth_service import AuthenticatedUser, auth_service


def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    return token.strip()


def current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    user = auth_service.session(bearer_token(authorization))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인 세션이 유효하지 않습니다.")
    return user


def require_developer(user: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUser:
    if user.role != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Code Assistant는 개발자 계정만 사용할 수 있습니다.")
    return user
