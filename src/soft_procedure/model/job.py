from dataclasses import dataclass, field

@dataclass
class Job:
    job_id: int
    batch_id: int
    product: str
    arrival_time: float
    operation_index: int = 0

    # 每次进入新工位的缓冲区时更新
    queue_entered_at: float | None = None
    completion_time: float | None = None
    admitted_at: float | None = None
    location: str = "external"
    operations: list[dict] = field(default_factory=list)
