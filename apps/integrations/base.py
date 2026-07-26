from dataclasses import dataclass, field
from typing import Any

@dataclass
class IntegrationResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

class IntegrationNotConfigured(RuntimeError):
    pass

class IntegrationError(RuntimeError):
    pass
