from typing import Any, Callable
from src.infrastructure.datadog.client import DatadogClientBase


class DatadogManagerBase(DatadogClientBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def execute(self, func: Callable[..., Any], *args, **kwargs):
        return self.execute_with_retry(func, *args, **kwargs)