"""Course IR (intermediate representation) — validated before sync to Stepik."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChoiceOption(BaseModel):
    text: str
    is_correct: bool = False
    feedback: str = ""


class TextStep(BaseModel):
    type: Literal["text"] = "text"
    html: str = ""


class ChoiceStep(BaseModel):
    type: Literal["choice"] = "choice"
    question: str
    options: list[ChoiceOption]
    is_multiple_choice: bool | None = None

    @field_validator("options")
    @classmethod
    def _need_options(cls, v: list[ChoiceOption]) -> list[ChoiceOption]:
        if not v:
            raise ValueError("choice step needs at least one option")
        return v


class CodeStep(BaseModel):
    type: Literal["code"] = "code"
    text: str = ""
    language: str = "python3"
    templates_data: str = ""
    test_cases: list[dict[str, Any]] = Field(default_factory=list)


class VideoStep(BaseModel):
    type: Literal["video"] = "video"
    text: str = ""
    video_id: int | None = None
    path: str | None = None  # local file under workspace; upload task resolves to video_id


class StringStep(BaseModel):
    type: Literal["string"] = "string"
    text: str = ""
    pattern: str = ""
    case_sensitive: bool = False


class NumberStep(BaseModel):
    type: Literal["number"] = "number"
    text: str = ""
    answer: float
    max_error: float = 0.0


class MatchingPair(BaseModel):
    first: str
    second: str


class MatchingStep(BaseModel):
    type: Literal["matching"] = "matching"
    text: str = ""
    pairs: list[MatchingPair]


class SortingStep(BaseModel):
    type: Literal["sorting"] = "sorting"
    text: str = ""
    items: list[str]


class FreeAnswerStep(BaseModel):
    type: Literal["free-answer"] = "free-answer"
    text: str = ""


class ReviewStep(BaseModel):
    type: Literal["review"] = "review"
    text: str = ""
    instructions_to_reviewer: str = ""


Step = (
    TextStep
    | ChoiceStep
    | CodeStep
    | VideoStep
    | StringStep
    | NumberStep
    | MatchingStep
    | SortingStep
    | FreeAnswerStep
    | ReviewStep
)


class LessonIR(BaseModel):
    title: str
    is_public: bool = False
    steps: list[Any] = Field(default_factory=list)  # discriminated manually


class SectionIR(BaseModel):
    title: str
    lessons: list[LessonIR] = Field(default_factory=list)


class CourseMeta(BaseModel):
    title: str
    summary: str = ""
    description: str = ""
    language: str = "ru"
    course_id: int | None = None  # set after create / bind


class CourseIR(BaseModel):
    course: CourseMeta
    sections: list[SectionIR] = Field(default_factory=list)


def parse_step(raw: dict[str, Any]) -> Step:
    t = raw.get("type")
    mapping: dict[str, type[BaseModel]] = {
        "text": TextStep,
        "choice": ChoiceStep,
        "code": CodeStep,
        "video": VideoStep,
        "string": StringStep,
        "number": NumberStep,
        "matching": MatchingStep,
        "sorting": SortingStep,
        "free-answer": FreeAnswerStep,
        "review": ReviewStep,
    }
    cls = mapping.get(str(t))
    if cls is None:
        raise ValueError(f"unsupported step type: {t!r}")
    return cls.model_validate(raw)  # type: ignore[return-value]


def validate_ir_obj(obj: Any) -> CourseIR:
    if isinstance(obj, str):
        obj = json.loads(obj)
    ir = CourseIR.model_validate(obj)
    # validate steps deeply
    for sec in ir.sections:
        for les in sec.lessons:
            parsed: list[Any] = []
            for step in les.steps:
                if isinstance(step, BaseModel):
                    parsed.append(step)
                else:
                    parsed.append(parse_step(dict(step)))
            les.steps = parsed
    return ir


def validate_ir_json(ir_json: str) -> CourseIR:
    return validate_ir_obj(json.loads(ir_json))


def step_to_block(step: Step) -> dict[str, Any]:
    if isinstance(step, TextStep):
        return {"name": "text", "text": step.html}
    if isinstance(step, ChoiceStep):
        multi = step.is_multiple_choice
        if multi is None:
            multi = sum(1 for o in step.options if o.is_correct) > 1
        return {
            "name": "choice",
            "text": step.question,
            "source": {
                "options": [
                    {"text": o.text, "is_correct": o.is_correct, "feedback": o.feedback}
                    for o in step.options
                ],
                "is_always_correct": False,
                "is_html_enabled": True,
                "preserve_order": False,
                "is_multiple_choice": multi,
                "sample_size": len(step.options),
            },
        }
    if isinstance(step, CodeStep):
        return {
            "name": "code",
            "text": step.text,
            "source": {
                "language": step.language,
                "templates_data": step.templates_data,
                "test_cases": step.test_cases,
                "is_time_limit": False,
                "is_memory_limit": False,
            },
        }
    if isinstance(step, VideoStep):
        if step.video_id is None:
            raise ValueError("video step needs video_id (upload first or set id)")
        return {"name": "video", "text": step.text, "video": step.video_id}
    if isinstance(step, StringStep):
        return {
            "name": "string",
            "text": step.text,
            "source": {"pattern": step.pattern, "case_sensitive": step.case_sensitive},
        }
    if isinstance(step, NumberStep):
        return {
            "name": "number",
            "text": step.text,
            "source": {"options": [{"answer": str(step.answer), "max_error": str(step.max_error)}]},
        }
    if isinstance(step, MatchingStep):
        return {
            "name": "matching",
            "text": step.text,
            "source": {"pairs": [{"first": p.first, "second": p.second} for p in step.pairs]},
        }
    if isinstance(step, SortingStep):
        return {
            "name": "sorting",
            "text": step.text,
            "source": {"options": [{"text": i} for i in step.items]},
        }
    if isinstance(step, FreeAnswerStep):
        return {"name": "free-answer", "text": step.text, "source": {}}
    if isinstance(step, ReviewStep):
        return {
            "name": "review",
            "text": step.text,
            "source": {"instructions_to_reviewer": step.instructions_to_reviewer},
        }
    raise ValueError(f"unhandled step: {type(step)}")
