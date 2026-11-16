"""分区检测接口：维护检测规则，覆盖提交规则评审、启用规则、暂停规则、检测缺失分区等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.partitioncheck import PartitioncheckService

router = APIRouter(prefix="/api/partitioncheck", tags=["分区检测"])

service = PartitioncheckService()

LIST_FIELDS = ["规则编号", "数据表名", "期望分区数", "分区延迟容忍", "缺失分区告警", "检测间隔分钟", "自动补齐开关", "补齐优先级"]
STATUSES = ["草稿", "规则评审中", "已启用", "已暂停"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、规则评审中、已启用、已暂停"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤分区检测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出分区检测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "partitioncheck", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检测规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检测规则 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/diffreports", response_model=dict)
def list_diffreports(entry_id: int) -> dict[str, Any]:
    """读取规则关联的终态差异报告，与数据比对入口读到的是同一份数据记录。"""
    entry, reports = service.list_reports(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检测规则 {entry_id} 不存在或已归档")
    return {"rule": entry, "reports": reports, "total": len(reports)}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检测规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检测规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检测规则执行提交规则评审、启用规则、暂停规则、检测缺失分区；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
