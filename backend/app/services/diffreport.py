"""差异报告数据记录：比对任务终态落库时的唯一事实来源。

数据比对在终态（已完成/已失败）时原子写入报告；分区检测只读这里的记录，
两个模块的各入口读到的都是同一份终态版本，避免跨模块对不上。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "diffreport"
TERMINAL_STATES = ("已完成", "已失败")

_FIELD_SPLIT = re.compile(r"[,，、;；\s]+")


def parse_fields(raw: Any) -> list[str]:
    """把「比对字段」「分区字段」这类清单文本解析成字段列表；空值返回空列表。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [part for part in _FIELD_SPLIT.split(str(raw).strip()) if part]


def parse_number(raw: Any) -> float | None:
    """宽松解析数值；解析不了返回 None，由调用方决定兜底口径。"""
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _rows() -> list[dict[str, Any]]:
    return store.rows(MODULE)


def next_id() -> int:
    return max((int(row.get("id", 0)) for row in _rows()), default=0) + 1


def terminal_reports() -> list[dict[str, Any]]:
    """每个比对任务只保留一份终态报告。

    并发终态或历史重复落库导致同一任务出现多份报告时，保留最后写入的
    终态版本，保证比对与分区检测读到一致、且不重复显示。
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in _rows():
        if row.get("终态") not in TERMINAL_STATES:
            continue
        task_no = str(row.get("任务编号", ""))
        current = latest.get(task_no)
        if current is None or int(row.get("id", 0)) > int(current.get("id", 0)):
            latest[task_no] = row
    return sorted(latest.values(), key=lambda row: int(row.get("id", 0)))


def report_for_task(task_no: Any) -> dict[str, Any] | None:
    """按任务编号取唯一终态报告；任务尚未终态时返回 None。"""
    task_no = str(task_no or "")
    for row in terminal_reports():
        if str(row.get("任务编号", "")) == task_no:
            return row
    return None


def reports_for_table(table: Any) -> list[dict[str, Any]]:
    """按数据表名取关联的终态报告（源表或目标表命中都算）。"""
    table = str(table or "").strip()
    if not table:
        return []
    return [
        row
        for row in terminal_reports()
        if table in (str(row.get("源表名", "")).strip(), str(row.get("目标表名", "")).strip())
    ]


def write_report(report: dict[str, Any]) -> dict[str, Any]:
    """追加一份差异报告。

    调用方必须已持有 store.lock：报告要与比对任务的终态在同一把锁内落库，
    保证「终态 + 报告」要么同时可见、要么都不落库。
    """
    _rows().append(report)
    return report
