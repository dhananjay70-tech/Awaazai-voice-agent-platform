import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VoiceConfig(BaseModel):
    """Provider-neutral voice settings.

    Unknown keys are rejected (extra="forbid"), so provider API keys or other secrets
    cannot be smuggled into an agent's configuration.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=50)
    voice_id: str | None = Field(default=None, max_length=100)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    system_prompt: str = Field(min_length=1, max_length=10_000)
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=35)
    voice_config: VoiceConfig = Field(default_factory=VoiceConfig)
    is_active: bool = True

    @field_validator("name", "system_prompt")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=10_000)
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=35)
    voice_config: VoiceConfig | None = None
    is_active: bool | None = None

    @field_validator("name", "system_prompt")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value

    @model_validator(mode="after")
    def required_fields_not_null(self) -> "AgentUpdate":
        # Omitting a field leaves it unchanged; sending an explicit null is only allowed for description.
        for field in self.model_fields_set - {"description"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    language: str
    voice_config: VoiceConfig
    is_active: bool
    created_at: datetime
    updated_at: datetime
