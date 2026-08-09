from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OpenProjectRequest(BaseModel):
    path: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    model: str = Field(min_length=1)

    @field_validator("message", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class Change(BaseModel):
    old: str
    new: str


class ProposedFile(BaseModel):
    path: str = Field(min_length=1)
    changes: list[Change] = Field(min_length=1)


class ApplyRequest(BaseModel):
    paths: list[str] | None = None
    confirm_unverified: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class CommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("커밋 메시지를 입력해 주세요.")
        return value


class PushRequest(BaseModel):
    confirmed: bool

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Push는 사용자 확인이 필요합니다.")
        return value


class BranchCheckoutRequest(BaseModel):
    branch: str = Field(min_length=1, max_length=255)

    @field_validator("branch")
    @classmethod
    def strip_branch(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("전환할 Git 브랜치를 선택해 주세요.")
        return value


class TerminalRequest(BaseModel):
    shell: Literal["cmd", "powershell", "git-bash"]
    command: str = Field(min_length=1, max_length=20_000)
    cwd: str | None = Field(default=None, max_length=4_096)

    @field_validator("command")
    @classmethod
    def strip_command(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("실행할 명령어를 입력해 주세요.")
        return value
