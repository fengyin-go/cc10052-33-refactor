"""统一资源接口：查询、导出、登记和动作按模块 key 分派到领域服务。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services import service_for

router = APIRouter(prefix="/api", tags=["业务资源"])


def require_service(module: str):
    service = service_for(module)
    if service is None:
        raise HTTPException(status_code=404, detail=f"未知业务模块：{module}")
    return service


@router.get("/{module}", response_model=PageResult[dict])
def list_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, total = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{module}/export")
def export_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, _ = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=1, size=1_000_000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *service.LIST_FIELDS, "status"])
    for item in items:
        values = [item.get("id"), *(item.get(field, "") for field in service.LIST_FIELDS),
                  item.get("status", "")]
        writer.writerow([
            "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
            for value in values
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{module}.csv"'},
    )


@router.get("/{module}/{entry_id}", response_model=dict)
def get_entry(module: str, entry_id: int) -> dict[str, Any]:
    service = require_service(module)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    return entry


@router.delete("/{module}/{entry_id}", response_model=ActionResult)
def delete_entry(module: str, entry_id: int) -> ActionResult:
    service = require_service(module)
    ok = service.delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已删除")
    return ActionResult(ok=True, message=f"{service.ENTITY} {entry_id} 已删除")


@router.post("/{module}", response_model=ActionResult)
def create_entry(module: str, payload: EntryPayload) -> ActionResult:
    service = require_service(module)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"{service.ENTITY}已登记", entry=entry)


@router.post("/{module}/{entry_id}/actions", response_model=ActionResult)
def run_action(module: str, entry_id: int, payload: ActionPayload) -> ActionResult:
    service = require_service(module)
    result = service.execute_action(entry_id, payload.action.strip(), payload)
    return ActionResult.model_validate(result)


@router.get("/report_gen/{entry_id}/compose_summary")
def report_compose_summary(entry_id: int) -> dict[str, Any]:
    service = require_service("report_gen")
    return service.compose_summary(entry_id)


@router.get("/report_gen/{entry_id}/summary")
def report_summary(entry_id: int) -> dict[str, Any]:
    service = require_service("report_gen")
    return service.compose_summary(entry_id)


@router.get("/report_gen/{entry_id}/materials")
def report_materials(entry_id: int) -> dict[str, Any]:
    service = require_service("report_gen")
    return service.report_materials(entry_id)


@router.get("/report_gen/{entry_id}/evidence")
def report_evidence(entry_id: int) -> dict[str, Any]:
    service = require_service("report_gen")
    return service.report_materials(entry_id)


@router.post("/report_gen/{entry_id}/generate", response_model=ActionResult)
def generate_report(entry_id: int) -> ActionResult:
    service = require_service("report_gen")
    result = service.generate_report(entry_id)
    result.setdefault("entry", service.get_entry(entry_id))
    return ActionResult.model_validate(result)


@router.post("/report_gen/{entry_id}/confirm", response_model=ActionResult)
def confirm_report(entry_id: int) -> ActionResult:
    service = require_service("report_gen")
    result = service.confirm_report(entry_id)
    return ActionResult.model_validate(result)


@router.post("/report_gen/{entry_id}/archive_finished", response_model=ActionResult)
def archive_finished_report(entry_id: int) -> ActionResult:
    service = require_service("report_gen")
    result = service.archive_finished(entry_id)
    result.setdefault("entry", service.get_entry(entry_id))
    return ActionResult.model_validate(result)


@router.get("/exp_archive/{entry_id}/basis")
def archive_basis(entry_id: int) -> dict[str, Any]:
    service = require_service("exp_archive")
    return service.basis_detail(entry_id)


@router.get("/exp_archive/{entry_id}/evidence")
def archive_evidence(entry_id: int) -> dict[str, Any]:
    service = require_service("exp_archive")
    return service.basis_detail(entry_id)


@router.post("/exp_archive/{entry_id}/claim", response_model=ActionResult)
def claim_archive(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.claim_conclusion_basis(entry_id)
    return ActionResult.model_validate(result)


@router.post("/exp_archive/{entry_id}/claim_basis", response_model=ActionResult)
def claim_archive_basis(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.claim_conclusion_basis(entry_id)
    return ActionResult.model_validate(result)


@router.get("/exp_archive/{entry_id}/missing")
def archive_missing(entry_id: int) -> dict[str, Any]:
    service = require_service("exp_archive")
    return service.basis_detail(entry_id)


@router.get("/exp_archive/{entry_id}/missing_materials")
def archive_missing_materials(entry_id: int) -> dict[str, Any]:
    service = require_service("exp_archive")
    return service.basis_detail(entry_id)


@router.get("/exp_archive/{entry_id}/recompute")
def recompute_archive(entry_id: int) -> dict[str, Any]:
    service = require_service("exp_archive")
    return service.recompute(entry_id)


@router.post("/exp_archive/{entry_id}/claim_conclusion_basis", response_model=ActionResult)
def claim_archive_conclusion_basis(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.claim_conclusion_basis(entry_id)
    return ActionResult.model_validate(result)


@router.post("/exp_archive/{entry_id}/claim_archive_basis", response_model=ActionResult)
def claim_archive_named_basis(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.claim_archive_basis(entry_id)
    return ActionResult.model_validate(result)


@router.post("/exp_archive/{entry_id}/restore", response_model=ActionResult)
def restore_archive(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.restore(entry_id)
    return ActionResult.model_validate(result)


@router.post("/exp_archive/{entry_id}/resume", response_model=ActionResult)
def resume_archive(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.restore(entry_id)
    return ActionResult.model_validate(result)


@router.post("/exp_archive/{entry_id}/reclaim", response_model=ActionResult)
def reclaim_archive(entry_id: int) -> ActionResult:
    service = require_service("exp_archive")
    result = service.claim_conclusion_basis(entry_id)
    return ActionResult.model_validate(result)
