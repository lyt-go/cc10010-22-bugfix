"""数据比对业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import diffreport
from app.store import store

MODULE = "comparator"
REQUIRED_FIELDS = ["任务编号", "源表名", "目标表名"]
OPTIONAL_FIELDS = ["比对字段", "比对方式", "差异阈值", "采样比例", "产出差异报告"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
STATUS_ORDER = ["草稿", "比对审批中", "执行中", "已完成", "已失败"]
TERMINAL_STATES = ("已完成", "已失败")
# 每个动作允许的起始状态：终态任务一律拒绝，保证同一任务只有一个成功或失败终态。
ALLOWED_FROM = {
    "提交比对审批": {"草稿"},
    "启动比对": {"比对审批中"},
    "完成比对": {"执行中"},
    "标记失败": {"比对审批中", "执行中"},
}


class ComparatorService:
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
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_report(self, entry_id: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """读取任务及其唯一终态差异报告；任务未终态时报告为 None。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, None
        return entry, diffreport.report_for_task(entry.get("任务编号"))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with store.lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            # 登记即完整保存比对定义：比对字段、方式、阈值等不再丢失。
            for field in ALL_FIELDS:
                value = values.get(field)
                entry[field] = value if value is not None else ""
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        # 整段状态流转 + 报告落库都在同一把锁里：并发启动、重复标记失败、
        # 并发终态只会有一个生效，终态与差异报告要么同时落库要么都不落。
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"比对任务 {entry_id} 不存在或已归档"
            if action not in ALLOWED_FROM:
                return None, f"动作「{action}」不属于数据比对可执行范围"
            status = str(entry.get("status") or "")
            if status in TERMINAL_STATES:
                return None, f"比对任务已是终态「{status}」，不允许再执行「{action}」"
            if status not in ALLOWED_FROM[action]:
                return None, f"当前状态「{status}」不允许执行「{action}」"
            if action == "完成比对":
                target, report = self._execute_comparison(entry)
                message = f"比对任务{target}"
                if report.get("错误信息"):
                    message += f"：{report['错误信息']}"
            elif action == "标记失败":
                target, report = self._mark_failed(entry)
                message = "比对任务已标记失败"
            else:
                target = {"提交比对审批": "比对审批中", "启动比对": "执行中"}[action]
                report = None
                message = f"比对任务已{action}"
            entry["status"] = target
            entry["pending"] = target not in TERMINAL_STATES
            entry["abnormal"] = target == "已失败"
            if report is not None:
                diffreport.write_report(report)
            return dict(entry), message

    def _find_table(self, table_name: Any) -> dict[str, Any] | None:
        """按表名查元数据存储里的源/目标表字段数据。"""
        name = str(table_name or "").strip()
        if not name:
            return None
        for row in store.rows("metastore"):
            if str(row.get("表名", "")).strip() == name:
                return row
        return None

    def _execute_comparison(self, entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """从比对任务与源/目标表字段数据校验并生成差异报告，返回终态与报告。"""
        fields = diffreport.parse_fields(entry.get("比对字段"))
        errors: list[str] = []
        notes: list[str] = []
        if not fields:
            errors.append("比对字段为空或无法解析")
        threshold = diffreport.parse_number(entry.get("差异阈值"))
        if threshold is None:
            threshold = 0.0
            if str(entry.get("差异阈值") or "").strip():
                notes.append("差异阈值无法解析，按 0 处理")
        sample_raw = str(entry.get("采样比例") or "").strip()
        if sample_raw:
            ratio = diffreport.parse_number(sample_raw)
            if ratio is None:
                notes.append("采样比例无法解析，按全量处理")
            elif not 0 < ratio <= 100:
                errors.append("采样比例需在 1-100 之间")
        src_meta = self._find_table(entry.get("源表名"))
        tgt_meta = self._find_table(entry.get("目标表名"))
        diff_count: int | None = 0
        unchecked: list[str] = []
        if src_meta is not None and tgt_meta is not None:
            src_size = diffreport.parse_number(src_meta.get("字段数量")) or 0
            tgt_size = diffreport.parse_number(tgt_meta.get("字段数量")) or 0
            diff_count = abs(int(src_size) - int(tgt_size))
            partitions = set(diffreport.parse_fields(src_meta.get("分区字段")))
            partitions |= set(diffreport.parse_fields(tgt_meta.get("分区字段")))
            # 未被比对字段覆盖的分区即为未核对分区，交给分区检测继续定位。
            unchecked = sorted(partitions - set(fields))
        else:
            missing = [
                str(name)
                for name, meta in ((entry.get("源表名"), src_meta), (entry.get("目标表名"), tgt_meta))
                if meta is None
            ]
            notes.append("元数据未登记：" + "、".join(missing))
        if errors:
            target = "已失败"
        elif diff_count is not None and diff_count > threshold:
            target = "已失败"
            notes.append(f"差异数量 {diff_count} 超过差异阈值 {threshold:g}")
        else:
            target = "已完成"
        report = self._build_report(
            entry,
            terminal=target,
            fields=fields,
            diff_count=diff_count,
            unchecked=unchecked,
            errors=errors,
            notes=notes,
        )
        return target, report

    def _mark_failed(self, entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """人工标记失败：比对未跑完，差异数量未知，全部分区记为未核对。"""
        fields = diffreport.parse_fields(entry.get("比对字段"))
        unchecked: set[str] = set()
        for name in (entry.get("源表名"), entry.get("目标表名")):
            meta = self._find_table(name)
            if meta is not None:
                unchecked.update(diffreport.parse_fields(meta.get("分区字段")))
        report = self._build_report(
            entry,
            terminal="已失败",
            fields=fields,
            diff_count=None,
            unchecked=sorted(unchecked),
            errors=["任务被人工标记失败"],
            notes=[],
        )
        return "已失败", report

    def _build_report(
        self,
        entry: dict[str, Any],
        *,
        terminal: str,
        fields: list[str],
        diff_count: int | None,
        unchecked: list[str],
        errors: list[str],
        notes: list[str],
    ) -> dict[str, Any]:
        """生成差异报告数据记录；比对字段做快照，不回写任务的原字段定义。"""
        report_id = diffreport.next_id()
        return {
            "id": report_id,
            "报告编号": f"DIFF-{report_id:04d}",
            "任务编号": entry.get("任务编号"),
            "比对任务id": entry.get("id"),
            "源表名": entry.get("源表名"),
            "目标表名": entry.get("目标表名"),
            "比对字段": list(fields),
            "比对方式": entry.get("比对方式") or "",
            "差异阈值": entry.get("差异阈值") or "",
            "采样比例": entry.get("采样比例") or "",
            "差异数量": diff_count,
            "未核对分区": list(unchecked),
            "终态": terminal,
            "错误信息": "；".join(errors),
            "备注": "；".join(notes),
            "生成时间": datetime.now().isoformat(timespec="seconds"),
        }
