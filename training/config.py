from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal["metric_patch_v1"] = "metric_patch_v1"
    crop_mode: Literal["fixed_160", "fixed_256", "fixed_320", "adaptive"] = "fixed_160"
    context_ratio: float = Field(default=1.5, ge=.5, le=4)
    min_crop: int = Field(default=192, ge=32, le=1024)
    max_crop: int = Field(default=384, ge=32, le=1024)
    output_size: int = Field(default=320, ge=32, le=512)
    near_black_mean: float = Field(default=15, ge=0, le=255)
    low_std: float = Field(default=5, ge=0, le=128)
    low_edge_density: float = Field(default=.01, ge=0, le=1)
    folds: int = Field(default=5, ge=2, le=10)
    fold: int = Field(default=0, ge=0, le=9)
    epochs: int = Field(default=100, ge=1, le=1000)
    batch_size: int = Field(default=8, ge=1, le=64)
    lr: float = Field(default=.0001, gt=0, le=.1)
    weight_decay: float = Field(default=.0001, ge=0, le=1)
    margin: float = Field(default=.5, gt=0, le=2)
    negative_min_distance: float = Field(default=64, gt=0, le=2048)
    seed: int = Field(default=42, ge=0, le=2**31-1)
    device: Literal["cuda", "cpu"] = "cuda"
    embedding_dim: int = Field(default=256, ge=16, le=512)

    @model_validator(mode="after")
    def consistent(self):
        if self.min_crop > self.max_crop or self.fold >= self.folds or self.output_size % 4:
            raise ValueError("min/max crop, fold 범위, input size(4의 배수)를 확인하세요.")
        return self
