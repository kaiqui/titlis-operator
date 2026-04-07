from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class SiteHealthCheckConfig(BaseModel):
    type: Literal["site_health"] = "site_health"
    name: str
    url: str
    interval_seconds: int = 60
    timeout_seconds: float = 10.0
    tags: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class JsonValueCheckConfig(BaseModel):
    type: Literal["json_value"] = "json_value"
    name: str
    url: str
    json_path: str
    metric_name: str
    interval_seconds: int = 60
    timeout_seconds: float = 10.0
    tags: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


CheckConfig = Annotated[
    Union[SiteHealthCheckConfig, JsonValueCheckConfig],
    Field(discriminator="type"),
]


class SyntheticChecksConfig(BaseModel):
    checks: list[CheckConfig] = Field(default_factory=list)
