"""分区检测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import diffreport
from app.store import store

MODULE = "partitioncheck"
REQUIRED_FIELDS = ["规则编号", "数据表名", "期望分区数"]
OPTIONAL_FIELDS = ["分区延迟容忍", "缺失分区告警", "检测间隔分钟", "自动补齐开关", "补齐优先级"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
STATUS_ORDER = ["草稿", "规则评审中", "已启用", "已暂停"]
ACTION_RULES = {"提交规则评审": "规则评审中", "启用规则": "已启用", "暂停规则": "已暂停"}
DETECT_ACTION = "检测缺失分区"
# 每个动作允许的起始状态；检测缺失分区不是状态流转，只读取差异报告并回写检测结果。
ALLOWED_FROM = {
    "提交规则评审": {"草稿"},
    "启用规则": {"规则评审中", "已暂停"},
    "暂停规则": {"已启用"},
    DETECT_ACTION: {"已启用"},
}


class PartitioncheckService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def list_reports(self, entry_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """读取规则及其关联的终态差异报告，与数据比对入口读到的是同一份记录。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, []
        return entry, diffreport.reports_for_table(entry.get("数据表名"))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with store.lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in ALL_FIELDS:
                value = values.get(field)
                entry[field] = value if value is not None else ""
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"检测规则 {entry_id} 不存在或已归档"
            if action not in ALLOWED_FROM:
                return None, f"动作「{action}」不属于分区检测可执行范围"
            status = str(entry.get("status") or "")
            if status not in ALLOWED_FROM[action]:
                return None, f"当前状态「{status}」不允许执行「{action}」"
            if action == DETECT_ACTION:
                message = self._detect_missing_partitions(entry)
            else:
                target = ACTION_RULES[action]
                if target not in STATUS_ORDER:
                    return None, f"目标状态「{target}」不在允许的状态序列里"
                entry["status"] = target
                entry["pending"] = target != STATUS_ORDER[-1]
                entry["abnormal"] = False
                message = f"检测规则已{action}"
            return dict(entry), message

    def _detect_missing_partitions(self, entry: dict[str, Any]) -> str:
        """读取终态差异报告，标记缺失分区并汇总未核对分区与差异数量。

        结果只回写固定的检测结果字段，重复检测覆盖同一组字段，
        不产生字段残留，也不会改动规则定义本身。
        """
        reports = diffreport.reports_for_table(entry.get("数据表名"))
        unchecked: set[str] = set()
        diff_total = 0
        for report in reports:
            unchecked.update(report.get("未核对分区") or [])
            count = report.get("差异数量")
            if isinstance(count, (int, float)):
                diff_total += int(count)
        missing = sorted(unchecked)
        entry["未核对分区"] = missing
        entry["缺失分区"] = list(missing)
        entry["差异数量"] = diff_total
        entry["关联报告数"] = len(reports)
        entry["最近检测时间"] = datetime.now().isoformat(timespec="seconds")
        if not reports:
            return "检测完成：未找到关联差异报告，未核对分区 0 个，差异数量 0"
        return (
            f"检测完成：关联差异报告 {len(reports)} 份，"
            f"未核对分区 {len(missing)} 个，差异数量 {diff_total}"
        )
