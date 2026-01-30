"""Process definitions and discovery."""

from wiggy.processes.base import ProcessRun, ProcessSpec, ProcessStep, StepResult
from wiggy.processes.loader import (
    copy_default_processes_to_user,
    get_all_processes,
    get_process_by_name,
)
from wiggy.processes.orchestrator import build_process_status_prompt, run_process

__all__ = [
    "ProcessRun",
    "ProcessSpec",
    "ProcessStep",
    "StepResult",
    "build_process_status_prompt",
    "copy_default_processes_to_user",
    "get_all_processes",
    "get_process_by_name",
    "run_process",
]
