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


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
