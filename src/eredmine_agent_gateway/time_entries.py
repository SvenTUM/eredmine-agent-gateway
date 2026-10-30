from dataclasses import dataclass, field


@dataclass
class TimeEntryParams:
    issue_id: int
    hours: float
    activity_id: int
    comments: str = ""
    spent_on: str | None = None
    custom_field_values: dict[str, str] = field(default_factory=dict)
