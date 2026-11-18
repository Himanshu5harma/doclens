"""Answer-generation port: configuration, completion record and the Generator interface."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class GenerationError(ValueError):
    """Provider/format failures are errors, never evidence-insufficiency decisions."""

    def __init__(self, kind: str, message: str, *, metadata: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.metadata = metadata


@dataclass(frozen=True)
class GenerationConfig:
    model_id: str = "nvidia/nemotron-3.5-super-vl:free"
    temperature: float = 0
    max_output_tokens: int = 1600
    max_prompt_bytes: int = 24000
    timeout_seconds: float = 45

    def __post_init__(self):
        if not isinstance(self.model_id, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+:free", self.model_id):
            raise ValueError("Generation requires one explicit provider/model:free ID; routers and paid IDs are rejected.")
        for field, low, high in (("max_output_tokens", 128, 4096), ("max_prompt_bytes", 4000, 48000)):
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field} must be an integer between {low} and {high}.")
        for field, low, high in (("temperature", 0, 1), ("timeout_seconds", 1, 60)):
            value = getattr(self, field)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} must be between {low} and {high}.")


def load_generation_config(path: Path) -> GenerationConfig:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != set(GenerationConfig.__dataclass_fields__):
        raise ValueError("Generation configuration must contain exactly the documented settings.")
    return GenerationConfig(**data)


@dataclass(frozen=True)
class Completion:
    content: str
    metadata: dict


class Generator(Protocol):
    def complete(self, messages: tuple[dict, ...], config: GenerationConfig) -> Completion: ...
