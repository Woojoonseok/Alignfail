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
    class_label: str = Field(default="", max_length=200)
    pattern_type: str = Field(default="unknown", pattern="^(A|B|unknown)$")
    modality: str | None = Field(default=None, pattern="^(OM|SEM|)$")  # None keeps the stored value
    tier: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=10000)
    enabled: bool = True
    exclude_reason: str = Field(default="", max_length=2000)
    # True promotes an automatic (white-cross) GT to a reviewed manual GT without moving it.
    confirm_gt: bool = False

    @model_validator(mode="after")
    def validate_pair(self):
        if (self.gt_x is None) != (self.gt_y is None):
            raise ValueError("GT X와 Y를 함께 지정하세요.")
        if not self.enabled and not self.exclude_reason.strip():
            raise ValueError("제외 사유를 입력하세요.")
        self.group_key = self.group_key.strip()
        self.class_label = self.class_label.strip()
        self.tier = self.tier.strip()
        return self


class VersionInput(StrictModel):
    description: str = Field(min_length=1, max_length=4000)


class PixelRect(StrictModel):
    x0: int = Field(ge=0)
    y0: int = Field(ge=0)
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("시작 좌표는 끝 좌표보다 작거나 같아야 합니다.")
        return self


class CleanupSource(StrictModel):
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CleanupInput(CleanupSource):
    box: PixelRect | None = None
    cross: PixelRect | None = None
    padding: int = Field(default=1, ge=0, le=5)
    radius: float = Field(default=3, ge=1, le=10)
    cross_noise: bool = True


class AutoCleanupInput(CleanupSource):
    box: bool = True
    cross: bool = True
    replace_existing: bool = False


class PairRevision(StrictModel):
    id: str
    revision: int = Field(ge=1)


class GroupAssignment(PairRevision):
    group_key: str | None = Field(default=None, max_length=200)
    class_label: str | None = Field(default=None, max_length=200)


class BulkGroupsInput(StrictModel):
    assignments: list[GroupAssignment] = Field(min_length=1, max_length=10000)


class ClassTemplateInput(StrictModel):
    image_id: str


class AttachInput(StrictModel):
    pairs: list[PairRevision] = Field(min_length=1, max_length=10000)
    class_label: str = Field(min_length=1, max_length=200)


class MatchInput(StrictModel):
    pairs: list[PairRevision] = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)


class MarkingsInput(StrictModel):
    pairs: list[PairRevision] = Field(min_length=1, max_length=2000)
    roi: bool = True
    gt: bool = True
    replace_existing: bool = False


class ClusterInput(StrictModel):
    pairs: list[PairRevision] = Field(min_length=2, max_length=2000)
    clusters: int = Field(ge=2, le=50)
    role: str = Field(default="reference", pattern="^(reference|query)$")
