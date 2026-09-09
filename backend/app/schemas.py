from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def strip_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("프로젝트 이름을 입력하세요.")
        return self


class ImportInput(StrictModel):
    root_directory: str = Field(min_length=1, max_length=4000)


class PairInput(StrictModel):
    revision: int = Field(ge=1)
    gt_x: float | None = None
    gt_y: float | None = None
    group_key: str = Field(default="", max_length=200)
    tier: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=10000)
    enabled: bool = True
    exclude_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_pair(self):
        if (self.gt_x is None) != (self.gt_y is None):
            raise ValueError("GT X와 Y를 함께 지정하세요.")
        if not self.enabled and not self.exclude_reason.strip():
            raise ValueError("제외 사유를 입력하세요.")
        self.group_key = self.group_key.strip()
        self.tier = self.tier.strip()
        return self


class VersionInput(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
