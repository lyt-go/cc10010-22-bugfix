"""数据比对接口：维护比对任务，覆盖提交比对审批、启动比对、完成比对、标记失败等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.comparator import ComparatorService

router = APIRouter(prefix="/api/comparator", tags=["数据比对"])

service = ComparatorService()

LIST_FIELDS = ["任务编号", "源表名", "目标表名", "比对字段", "比对方式", "差异阈值", "采样比例", "产出差异报告"]
STATUSES = ["草稿", "比对审批中", "执行中", "已完成", "已失败"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="草稿、比对审批中、执行中、已完成、已失败"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号与状态过滤数据比对列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据比对清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "comparator", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条比对任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"比对任务 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/report", response_model=dict)
def get_report(entry_id: int) -> dict[str, Any]:
    """读取任务的唯一终态差异报告；任务未终态时 report 为 null，不算错误。"""
    entry, report = service.get_report(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"比对任务 {entry_id} 不存在或已归档")
    return {"task": entry, "report": report}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条比对任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="比对任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条比对任务执行提交比对审批、启动比对、完成比对、标记失败；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
