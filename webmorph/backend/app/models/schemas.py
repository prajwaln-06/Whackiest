from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, StringConstraints, field_validator


Language = Literal["en", "hi", "kn", "es", "fr"]
Value = str | bool | list[str] | None


class Status(StrEnum):
    IDLE = "IDLE"
    SCOUTING = "SCOUTING"
    AWAITING_USER_FORM = "AWAITING_USER_FORM"
    EXECUTING = "EXECUTING"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    HUMAN_TAKEOVER = "HUMAN_TAKEOVER"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Launch(BaseModel):
    url: AnyHttpUrl
    goal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=600)]
    language: Language = "en"

    @field_validator("url")
    @classmethod
    def no_credentials(cls, value: AnyHttpUrl):
        if value.username is not None or value.password is not None:
            raise ValueError("Enter a URL without embedded credentials.")
        return value


class Option(BaseModel):
    label: str
    value: str


class FieldSpec(BaseModel):
    key: str
    original: str
    label: str
    hint: str = ""
    kind: str
    required: bool
    confirm_explicitly: bool = False
    options: list[Option] = Field(default_factory=list)
    current: Value = None
    suggestion: Value = None
    confidence: float | None = None
    source: str | None = None
    error: str | None = None
    accept: str = ""
    multiple: bool = False
    minimum: str = ""
    maximum: str = ""
    pattern: str = ""
    max_length: int | None = None
    step: str = ""


class Brief(BaseModel):
    summary: str
    documents: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    eligibility: list[str] = Field(default_factory=list)
    source: Literal["llm", "heuristic"] = "heuristic"


class TaskSchema(BaseModel):
    title: str = ""
    url: str = ""
    step: str = ""
    fields: list[FieldSpec] = Field(default_factory=list)


class AuditEntry(BaseModel):
    at: str
    action: str
    label: str
    strategy: str = ""
    verified: bool | None = None
    duration_ms: int = 0
    detail: str = ""


class Change(BaseModel):
    key: str
    label: str
    before: Value
    after: Value
    step: str = ""
    url: str = ""
    verified: bool = True


class Approval(BaseModel):
    token: str
    button: str
    screenshot: str
    changes: list[Change]


class Receipt(BaseModel):
    reference: str | None = None
    summary: str
    url: str


class RunState(BaseModel):
    session_id: str
    revision: int = 0
    status: Status = Status.IDLE
    url: str
    goal: str
    form: TaskSchema = Field(default_factory=TaskSchema, serialization_alias="schema")
    brief: Brief | None = None
    timeline: list[AuditEntry] = Field(default_factory=list)
    approval: Approval | None = None
    receipt: Receipt | None = None
    message: str = ""
    provider_notice: str = ""
    transitions: int = 0


class Answers(BaseModel):
    values: dict[str, Value] = Field(max_length=180)

    @field_validator("values")
    @classmethod
    def bound_values(cls, values: dict[str, Value]):
        for value in values.values():
            items = value if isinstance(value, list) else [value]
            if len(items) > 30 or any(isinstance(item, str) and len(item) > 15000 for item in items):
                raise ValueError("An answer exceeds the supported size.")
        return values


class Consent(BaseModel):
    token: Annotated[str, StringConstraints(min_length=16, max_length=100)]


class Vault(BaseModel):
    facts: dict[str, str] = Field(default_factory=dict, max_length=180)

    @field_validator("facts")
    @classmethod
    def bound_facts(cls, facts: dict[str, str]):
        if any(not key.strip() or len(key) > 100 or len(value) > 5000 for key, value in facts.items()):
            raise ValueError("Vault keys must be 1–100 characters and values at most 5,000 characters.")
        return {key.strip(): value.strip() for key, value in facts.items() if value.strip()}


class InputEvent(BaseModel):
    type: Literal["mouse_click", "mouse_wheel", "key_press", "type_text"]
    x: float = Field(0, ge=0, le=1280)
    y: float = Field(0, ge=0, le=800)
    delta_x: float = Field(0, ge=-2500, le=2500)
    delta_y: float = Field(0, ge=-2500, le=2500)
    key: str = Field("", max_length=90)
    text: str = Field("", max_length=3000)


class WSEvent(BaseModel):
    type: Literal["state", "frame", "target", "error"]
    payload: dict
