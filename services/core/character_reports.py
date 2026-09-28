"""Per-pipeline result aggregation, independent of game tasks and delivery channels."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Callable

CharacterKey = tuple[str, str]


@dataclass
class CharacterReport:
    character: CharacterKey
    position: int | None = None
    outcomes: dict[str, tuple[str, str]] = field(default_factory=dict)

    def format_message(self, *, interrupted: bool = False) -> str:
        server, name = self.character
        success_count = sum(state == "success" for _, state in self.outcomes.values())
        failed_count = sum(state == "failed" for _, state in self.outcomes.values())
        interrupted = interrupted or any(state == "pending" for _, state in self.outcomes.values())
        status = "已中断" if interrupted else ("部分失败" if failed_count else "任务完成")
        prefix = f"{self.position}:" if self.position is not None else ""
        lines = [f"{prefix}({name}){status}-成功:{success_count},失败:{failed_count}"]
        labels = {"success": "完成", "failed": "失败", "pending": "未完成"}
        details = [f"{path.rsplit('/', 1)[-1]}{labels[state]}" for path, state in self.outcomes.values()]
        lines.append("、".join(details[:6]) + (f" 等{len(details)}项" if len(details) > 6 else ""))
        failed_tasks = [path for path, state in self.outcomes.values() if state == "failed"]
        if failed_tasks:
            lines.append("失败项: " + "、".join(failed_tasks[:5]))
        if server:
            lines.append(f"服务器: {server}")
        return "\n".join(lines)


class CharacterReports:
    def __init__(self, publish: Callable[[str], None], order: list[CharacterKey]):
        self._publish = publish
        self._positions = {character: position for position, character in enumerate(order, 1)}
        self._reports: dict[CharacterKey, CharacterReport] = {}

    def record(self, character: CharacterKey, run_id: str, task_path: str, state: str) -> None:
        if state not in ("success", "failed", "pending"):
            raise ValueError(f"Invalid task outcome: {state}")
        report = self._reports.setdefault(character, CharacterReport(character, self._positions.get(character)))
        # A successful retry replaces its failed attempt; it is not a second task.
        report.outcomes[run_id] = (task_path, state)

    def flush_ready(self, current: CharacterKey, pending_retries: set[CharacterKey]) -> None:
        for character in list(self._reports):
            if character != current and character not in pending_retries:
                self._publish(self._reports.pop(character).format_message())

    def finish(self, *, interrupted: bool = False) -> None:
        for report in self._reports.values():
            self._publish(report.format_message(interrupted=interrupted))
        self._reports.clear()


def create_character_reports(settings_payload: dict, order: list[CharacterKey]) -> CharacterReports:
    """Bind the optional QQ sink once; all execution hooks remain transport-neutral."""
    from services.core.qq_notify import QQSettings, qq_notifier

    try:
        settings = QQSettings.parse(settings_payload)
    except ValueError as error:
        logging.getLogger(__name__).error("QQ notification configuration invalid: %s", error)
        return CharacterReports(lambda message: None, order)
    return CharacterReports(lambda message: qq_notifier.submit(settings, message), order)
