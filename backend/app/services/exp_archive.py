"""实验归档库领域服务：管理已结束实验的结论归档、保留等级与恢复流转。

数据链路位置：归档存储层，是实验评估数据沉淀的终点，消费实验设计与报告生成
的结论数据，按保留等级归档，支持恢复供切片分析复用历史明细。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.conclusion_materials import (
    TEST_MODULE,
    collect_conclusion_evidence,
    count_from_refs,
    count_value,
    entry_reference_basis,
    freeze_conclusion_evidence,
    next_row_id,
    verify_references,
)
from app.store import store


class ExpArchiveService(BaseModuleService):
    MODULE = "exp_archive"
    ENTITY = "归档实验"
    OPERATION_TERM = "归档"
    LIST_FIELDS = ["实验编码", "结束时间", "结论摘要", "归档位置", "保留等级"]
    REQUIRED_FIELDS = ["实验编码", "结束时间", "结论摘要"]
    STATUS_ORDER = ["待归档", "已归档", "恢复中"]
    ACTION_RULES = {"执行归档": "已归档", "恢复实验": "恢复中"}
    ACTION_METHODS = {
        "执行归档": "archive",
        "archive": "archive",
        "恢复实验": "restore",
        "restore": "restore",
        "领取依据": "claim_conclusion_basis",
        "claim": "claim_conclusion_basis",
        "claim_basis": "claim_conclusion_basis",
        "claim_conclusion_basis": "claim_conclusion_basis",
        "领取结论依据": "claim_conclusion_basis",
        "领取归档依据": "claim_conclusion_basis",
        "领取归档结论依据": "claim_conclusion_basis",
        "归档领取": "claim_conclusion_basis",
        "重新领取": "claim_conclusion_basis",
        "重新领取依据": "claim_conclusion_basis",
        "继续办理": "restore",
        "继续恢复": "restore",
        "recompute": "recompute",
        "recheck_basis": "basis_detail",
        "查看依据": "basis_detail",
        "归档明细": "basis_detail",
        "basis": "basis_detail",
        "detail": "basis_detail",
        "get_basis": "basis_detail",
    }
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：结论归档与恢复复用 ----

    def archive(self, entry_id: int) -> dict[str, Any]:
        """执行归档：锁定结论摘要并标注归档位置与保留等级。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待归档":
            return {"ok": False, "message": "仅待归档实验可执行归档"}
        exp_code = str(entry.get("实验编码", ""))
        ended = any(
            r.get("实验编码") == exp_code and r.get("status") == "已结束"
            for r in store.rows("exp_design")
        )
        if not ended:
            return {"ok": False, "message": "实验尚未结束，禁止归档"}
        entry["status"] = "已归档"
        entry["pending"] = False
        entry["归档位置"] = f"archive/{exp_code}/{datetime.now(timezone.utc).strftime('%Y%m')}"
        entry["归档时间"] = datetime.now(timezone.utc).isoformat()
        entry.setdefault("依据状态", "待领取")
        entry.setdefault("缺项", [])
        entry.setdefault("恢复历史", [])
        entry.setdefault("领取历史", [])
        entry.setdefault("历史记录", [])
        entry.setdefault("办理历史", [])
        return {"ok": True, "message": f"实验 {exp_code} 已归档到 {entry['归档位置']}"}

    def restore(self, entry_id: int) -> dict[str, Any]:
        """恢复已归档实验，重建切片分析批次复用历史明细。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已归档":
            return {"ok": False, "message": "仅已归档实验可恢复"}

        basis_result: dict[str, Any] | None = None
        if self._has_basis_source(entry):
            basis_result = self.claim_conclusion_basis(entry_id)
            if not basis_result.get("ok"):
                # 缺项已经在 claim 中登记；保持“已归档”，补齐后可继续原记录。
                basis_result["entry"] = entry
                return basis_result

        refs, _ = entry_reference_basis(entry)
        history_record = (basis_result or {}).get("history") if basis_result else None

        entry["status"] = "恢复中"
        entry["pending"] = True
        entry["恢复时间"] = datetime.now(timezone.utc).isoformat()
        slice_rows = store.rows("segment_slice")
        slice_batch = f"SG-AR-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}"
        slice_row = {
            "id": max((int(r.get("id", 0)) for r in slice_rows), default=0) + 1,
            "切片批次": slice_batch,
            "实验编码": entry.get("实验编码", ""),
            "切片维度": "归档恢复",
            "切片值": entry.get("结论摘要", "")[:20],
            "分组差异": "",
            "status": "待计算",
            "pending": True,
            "abnormal": False,
            "归档ID": entry_id,
            "报告编码": entry.get("报告编码", ""),
            "结论条数": entry.get("结论条数", len(refs)),
            "结论依据": copy.deepcopy(refs),
            "恢复依据编号": entry.get("依据编号", ""),
            "恢复历史编号": (history_record or {}).get("历史编号", ""),
        }
        slice_rows.append(slice_row)
        self._append_process_event(entry, {
            "时间": datetime.now().isoformat(),
            "动作": "恢复实验",
            "ok": True,
            "切片批次": slice_batch,
            "历史编号": (history_record or {}).get("历史编号", ""),
        })
        if history_record:
            history_record["status"] = "已用于恢复"
            history_record["使用时间"] = datetime.now(timezone.utc).isoformat()
            history_record["切片批次"] = slice_batch
        return {
            "ok": True,
            "message": "实验恢复中，历史切片批次已重建",
            "slice_batch": slice_batch,
            "slice": slice_row,
            "history": history_record,
            "结论依据": refs,
            "entry": entry,
        }

    def batch_archive_pending(self) -> dict[str, Any]:
        """批量归档全部待归档实验。"""
        pending = [r for r in store.rows(self.MODULE) if r.get("status") == "待归档"]
        done, skipped = 0, 0
        for row in pending:
            if self.archive(int(row.get("id", 0))).get("ok"):
                done += 1
            else:
                skipped += 1
        return {"ok": True, "message": f"批量归档完成 {done} 条，跳过 {skipped} 条"}

    def read_conclusion_materials(self, exp_code: str) -> dict[str, Any]:
        """归档侧复用报告的统一结论材料读取口径。"""
        return collect_conclusion_evidence(exp_code)

    def read_report_evidence(self, exp_code: str) -> dict[str, Any]:
        return self.read_conclusion_materials(exp_code)

    def get_conclusion_count(self, exp_code: str) -> int:
        return int(collect_conclusion_evidence(exp_code)["结论条数"])

    def consume_from_report_gen(self, exp_code: str) -> list[dict[str, Any]]:
        """读取报告生成器中该实验的完成报告，作为归档结论来源。"""
        return [
            {"报告编码": r.get("报告编码", ""), "结论条数": r.get("结论条数", "0"), "数据窗口": r.get("数据窗口", "")}
            for r in store.rows("report_gen")
            if r.get("实验编码") == exp_code and r.get("status") == "已完成"
        ]

    # ---- 结论依据领取、缺项登记与恢复历史 ----

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记档案时允许同时带入报告链接和已固化结论引用。"""
        entry, missing = super().create_entry(values)
        if missing or entry is None:
            return entry, missing
        for key in (
            "报告ID", "report_id", "报告编码", "依据编号", "conclusion_set_id",
            "结论依据", "结论引用", "references", "materials", "sources",
            "结论条数", "归档结论条数", "实际发布结论条数", "conclusion_count",
            "恢复历史", "办理历史", "缺项", "依据状态", "恢复准备状态",
        ):
            if key in values:
                entry[key] = values[key]
        return entry, []

    def claim_conclusion_basis(self, entry_id: int) -> dict[str, Any]:
        """领取归档结论引用，核验完整证据并生成恢复用历史记录。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"归档实验 {entry_id} 不存在"}
        if entry.get("status") == "已清理":
            return {"ok": False, "message": "已清理归档不能领取依据"}

        exp_code = str(entry.get("实验编码", "") or "")
        refs, basis_id = self._load_or_link_basis(entry)
        if not refs:
            # 没有从报告复制到引用时，按当前实验范围领取一次依据。
            snapshot = freeze_conclusion_evidence(
                exp_code, basis_code=f"archive-basis-{entry_id}-{next_row_id('exp_archive_history')}"
            )
            refs = snapshot["结论依据"]
            basis_id = snapshot["依据编号"]
            entry["结论依据"] = refs
            entry["结论引用"] = refs
            entry["依据编号"] = basis_id

        verification = verify_references(refs, exp_code)
        missing = verification["缺项"]
        if verification["检验条数"] == 0 and not any(
            item.get("module") == TEST_MODULE for item in missing
        ):
            missing.append({
                "序号": len(missing) + 1,
                "类型": "检验",
                "module": TEST_MODULE,
                "material_type": TEST_MODULE,
                "row_id": None,
                "编号": "",
                "材料编号": "",
                "实验编码": exp_code,
                "reason": f"实验 {exp_code} 没有可引用的已检验材料",
                "原因": f"实验 {exp_code} 没有可引用的已检验材料",
                "补证要求": f"请在 significance_test 中补齐实验 {exp_code} 的已检验记录",
                "link_path": "/significance_test",
                "link_query": {"new": "1", "实验编码": exp_code},
            })
            verification["complete"] = False
            verification["ok"] = False

        for item in missing:
            query = item.setdefault("link_query", {})
            if isinstance(query, dict):
                query["return_archive_id"] = entry_id
                query["return_to"] = f"/exp_archive?focus={entry_id}"
            item["return_archive_id"] = entry_id

        published_count = self._published_count(entry, refs)
        entry["结论条数"] = published_count
        entry["归档结论条数"] = published_count
        entry["实际发布结论条数"] = published_count
        entry["conclusion_count"] = int(count_value(published_count))
        entry["检验条数"] = verification["检验条数"]
        entry["归因条数"] = verification["归因条数"]
        entry["复核条数"] = verification["复核条数"]
        entry["依据编号"] = basis_id or entry.get("依据编号", f"archive-{entry_id}")

        if missing:
            reasons = "；".join(item.get("reason", "") for item in missing if item.get("reason"))
            message = f"归档结论依据不完整：{reasons}"
            entry["依据状态"] = "证据缺失"
            entry["恢复准备状态"] = "缺项"
            entry["缺项"] = missing
            entry["abnormal"] = True
            entry["pending"] = True
            event = self._append_process_event(entry, {
                "时间": datetime.now(timezone.utc).isoformat(),
                "动作": "领取归档结论依据",
                "ok": False,
                "依据编号": entry["依据编号"],
                "缺项": copy.deepcopy(missing),
                "message": message,
            })
            history_row = self._write_history_row(
                entry, refs, published_count, missing, status="缺项登记"
            )
            event["历史编号"] = history_row["历史编号"]
            return {
                "ok": False,
                "message": message,
                "archive_id": entry_id,
                "依据编号": entry["依据编号"],
                "结论条数": published_count,
                "检验条数": verification["检验条数"],
                "归因条数": verification["归因条数"],
                "复核条数": verification["复核条数"],
                "结论依据": refs,
                "materials": refs,
                "references": refs,
                "sources": refs,
                "missing": missing,
                "缺项": missing,
                "missing_references": missing,
                "missing_items": missing,
                "缺项材料": missing,
                "verification": verification,
                "history": history_row,
                "history_record": history_row,
                "历史记录": history_row,
                "event": event,
                "entry": entry,
            }

        entry["缺项"] = []
        entry["依据状态"] = "已领取"
        entry["恢复准备状态"] = "准备完成"
        entry["依据领取时间"] = datetime.now(timezone.utc).isoformat()
        entry["abnormal"] = False
        history_row = self._ensure_ready_history(entry, refs, published_count)
        self._append_process_event(entry, {
            "时间": datetime.now(timezone.utc).isoformat(),
            "动作": "领取归档结论依据",
            "ok": True,
            "依据编号": entry["依据编号"],
            "历史编号": history_row["历史编号"],
            "结论条数": published_count,
        })
        return {
            "ok": True,
            "message": f"归档 {exp_code or entry_id} 已领取完整结论依据，可进入恢复准备",
            "archive_id": entry_id,
            "依据编号": entry["依据编号"],
            "结论条数": published_count,
            "检验条数": verification["检验条数"],
            "归因条数": verification["归因条数"],
            "复核条数": verification["复核条数"],
            "结论依据": refs,
            "结论引用": refs,
            "出处": refs,
            "sources": refs,
            "materials": refs,
            "references": refs,
            "missing": [],
            "缺项": [],
            "verification": verification,
            "history": history_row,
            "历史记录": history_row,
            "entry": entry,
        }

    def basis_detail(self, entry_id: int) -> dict[str, Any]:
        """归档明细/查档接口：返回复核状态、原结论条数和缺项。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"归档实验 {entry_id} 不存在或已归档"}
        refs, basis_id = self._load_or_link_basis(entry)
        has_source = self._has_basis_source(entry)
        if refs:
            verification = verify_references(refs, str(entry.get("实验编码", "")))
        else:
            verification = {
                "complete": not has_source,
                "ok": not has_source,
                "missing": [],
                "缺项": [],
                "resolved_refs": [],
                "检验条数": 0,
                "归因条数": 0,
                "结论条数": 0,
                "复核条数": 0,
            }
        published_count = self._published_count(entry, refs)
        # 每次查档都按原引用/原编号实时复核，补齐后页面可立即看到缺项消失。
        missing = verification["缺项"]
        for item in missing:
            query = item.setdefault("link_query", {})
            if isinstance(query, dict):
                query["return_archive_id"] = entry_id
                query["return_to"] = f"/exp_archive?focus={entry_id}"
            item["return_archive_id"] = entry_id
        if refs:
            entry["缺项"] = missing
            if not missing and entry.get("依据状态") == "证据缺失":
                entry["依据状态"] = "待重新领取"
        return {
            "ok": True,
            "archive_id": entry_id,
            "id": entry_id,
            "实验编码": entry.get("实验编码", ""),
            "报告编码": entry.get("报告编码", ""),
            "status": entry.get("status", ""),
            "依据状态": entry.get("依据状态", "无引用" if not has_source else "待领取"),
            "恢复准备状态": entry.get("恢复准备状态", ""),
            "依据编号": basis_id or entry.get("依据编号", ""),
            "结论条数": published_count,
            "归档结论条数": entry.get("归档结论条数", published_count),
            "实际发布结论条数": entry.get("实际发布结论条数", published_count),
            "conclusion_count": int(count_value(published_count)),
            "materials": verification["resolved_refs"],
            "resolved_materials": verification["resolved_refs"],
            "复核材料": verification["resolved_refs"],
            "结论依据": refs,
            "结论引用": refs,
            "出处": refs,
            "结论出处": refs,
            "来源材料": verification["resolved_refs"],
            "sources": verification["resolved_refs"],
            "references": refs,
            "missing": missing,
            "缺项": missing,
            "missing_references": missing,
            "missing_items": missing,
            "缺项材料": missing,
            "verification": verification,
            "恢复历史": entry.get("恢复历史", []),
            "历史记录": entry.get("历史记录", entry.get("领取历史", [])),
            "history": entry.get("恢复历史", []),
            "restore_history": entry.get("恢复历史", []),
            "history_records": entry.get("历史记录", entry.get("领取历史", [])),
            "办理历史": entry.get("办理历史", []),
            "process_history": entry.get("办理历史", []),
            "entry": entry,
        }

    def claim(self, entry_id: int) -> dict[str, Any]:
        return self.claim_conclusion_basis(entry_id)

    def claim_basis(self, entry_id: int) -> dict[str, Any]:
        """兼容不同命名的归档依据领取调用。"""
        return self.claim_conclusion_basis(entry_id)

    def claim_archive_basis(self, entry_id: int) -> dict[str, Any]:
        return self.claim_conclusion_basis(entry_id)

    def claim_archive_conclusion(self, entry_id: int) -> dict[str, Any]:
        return self.claim_conclusion_basis(entry_id)

    def claim_archive_conclusion_basis(self, entry_id: int) -> dict[str, Any]:
        return self.claim_conclusion_basis(entry_id)

    def receive_conclusion_basis(self, entry_id: int) -> dict[str, Any]:
        return self.claim_conclusion_basis(entry_id)

    def get_basis(self, entry_id: int) -> dict[str, Any]:
        return self.basis_detail(entry_id)

    def recheck_basis(self, entry_id: int) -> dict[str, Any]:
        """按原引用编号重新核验，但不生成领取历史。"""
        return self.basis_detail(entry_id)

    def recompute(self, entry_id: int) -> dict[str, Any]:
        """按原归档编号和引用复算；不会用其他实验同编号材料补证。"""
        detail = self.basis_detail(entry_id)
        if not detail.get("ok"):
            return detail
        verification = detail.get("verification", {})
        detail.update({
            "ok": not detail.get("缺项"),
            "复算条数": verification.get("复核条数", 0),
            "recomputed_count": verification.get("recomputed_count", 0),
        })
        return detail

    def archive_basis_detail(self, entry_id: int) -> dict[str, Any]:
        return self.basis_detail(entry_id)

    # ---- 内部辅助 ----

    def _has_basis_source(self, entry: dict[str, Any]) -> bool:
        refs, _ = entry_reference_basis(entry)
        if refs:
            return True
        return any(entry.get(key) not in (None, "", []) for key in (
            "报告ID", "report_id", "报告编码", "依据编号", "conclusion_set_id",
            "归档结论条数", "实际发布结论条数",
        ))

    def _find_report(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        report_id = entry.get("报告ID", entry.get("report_id"))
        if report_id not in (None, ""):
            try:
                report = store.find("report_gen", int(report_id))
                if report is not None:
                    return report
            except (TypeError, ValueError):
                pass
        report_code = str(entry.get("报告编码", "") or "")
        if report_code:
            report = next(
                (r for r in store.rows("report_gen") if str(r.get("报告编码", "")) == report_code),
                None,
            )
            if report is not None:
                return report
        exp_code = str(entry.get("实验编码", "") or "")
        completed = [
            r for r in store.rows("report_gen")
            if str(r.get("实验编码", "") or "") == exp_code and r.get("status") == "已完成"
        ]
        return max(completed, key=lambda r: int(r.get("id", 0) or 0), default=None)

    def _load_or_link_basis(self, entry: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        refs, basis_id = entry_reference_basis(entry)
        if refs:
            return copy.deepcopy(refs), basis_id
        report = self._find_report(entry)
        if report is None:
            return [], basis_id
        refs, report_basis = entry_reference_basis(report)
        if not refs and report.get("status") == "已完成":
            snapshot = freeze_conclusion_evidence(
                str(report.get("实验编码", "")),
                basis_code=str(report.get("依据编号") or f"report-conclusions-{report.get('id')}"),
            )
            refs = snapshot["结论依据"]
            report_basis = snapshot["依据编号"]
        if not refs:
            return [], report_basis
        basis_id = report_basis or basis_id
        entry.setdefault("报告ID", report.get("id"))
        entry.setdefault("report_id", report.get("id"))
        entry.setdefault("报告编码", report.get("报告编码", ""))
        entry.setdefault("依据编号", basis_id)
        entry["结论依据"] = copy.deepcopy(refs)
        entry["结论引用"] = entry["结论依据"]
        if entry.get("归档结论条数") in (None, ""):
            count = report.get("结论条数", len(refs))
            entry["归档结论条数"] = count
            entry["实际发布结论条数"] = count
            entry["结论条数"] = count
        return copy.deepcopy(refs), basis_id

    def _published_count(self, entry: dict[str, Any], refs: list[dict[str, Any]]) -> Any:
        for key in ("实际发布结论条数", "归档结论条数", "结论条数"):
            value = entry.get(key)
            if value not in (None, ""):
                return value
        counts = count_from_refs(refs)
        return counts["结论条数"]

    def _append_process_event(self, entry: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        history = entry.setdefault("办理历史", [])
        event.setdefault("id", len(history) + 1)
        history.append(event)
        return event

    def _write_history_row(
        self,
        entry: dict[str, Any],
        refs: list[dict[str, Any]],
        count: Any,
        missing: list[dict[str, Any]],
        *,
        status: str,
    ) -> dict[str, Any]:
        rows = store.rows("exp_archive_history")
        archive_id = int(entry.get("id", 0) or 0)
        sequence = sum(1 for row in rows if int(row.get("归档ID", 0) or 0) == archive_id) + 1
        row = {
            "id": next_row_id("exp_archive_history"),
            "历史编号": f"ARH-{archive_id}-{sequence}",
            "归档ID": archive_id,
            "archive_id": archive_id,
            "实验编码": entry.get("实验编码", ""),
            "报告编码": entry.get("报告编码", ""),
            "依据编号": entry.get("依据编号", ""),
            "结论条数": count,
            "结论依据": copy.deepcopy(refs),
            "缺项": copy.deepcopy(missing),
            "status": status,
            "生成时间": datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)
        claim_history = entry.setdefault("领取历史", [])
        claim_history.append(row)
        entry["历史记录"] = claim_history
        return row

    def _ensure_ready_history(
        self,
        entry: dict[str, Any],
        refs: list[dict[str, Any]],
        count: Any,
    ) -> dict[str, Any]:
        basis_id = str(entry.get("依据编号", ""))
        archive_id = int(entry.get("id", 0) or 0)
        existing = next(
            (
                row for row in store.rows("exp_archive_history")
                if int(row.get("归档ID", 0) or 0) == archive_id
                and row.get("依据编号") == basis_id
                and row.get("status") in ("可恢复", "已用于恢复")
            ),
            None,
        )
        if existing is not None:
            entry["恢复历史"] = [
                item for item in entry.get("恢复历史", [])
                if item.get("历史编号") != existing.get("历史编号")
            ]
            entry["恢复历史"].append(existing)
            entry["restore_history"] = entry["恢复历史"]
            return existing
        row = self._write_history_row(entry, refs, count, [], status="可恢复")
        entry.setdefault("恢复历史", []).append(row)
        entry["restore_history"] = entry["恢复历史"]
        return row

    def set_retention_level(self, entry_id: int, level: str) -> dict[str, Any]:
        """设置归档保留等级并联动清理策略。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or level not in ("永久", "标准", "临时"):
            return {"ok": False, "message": "归档记录不存在或保留等级非法"}
        entry["保留等级"] = level
        entry["pending"] = level != "标准"
        entry["保留更新时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "message": f"保留等级已设置为 {level}"}

    def purge_expired_temp(self) -> dict[str, Any]:
        """清理超过保留期的临时等级归档记录。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("保留等级") == "临时" and r.get("status") == "已归档"]
        purged = 0
        for row in rows:
            kept = str(row.get("归档时间", ""))
            if kept and kept < datetime.now(timezone.utc).isoformat()[:10]:
                row["status"] = "已清理"
                row["pending"] = False
                row["abnormal"] = True
                purged += 1
        return {"ok": True, "message": f"清理临时归档 {purged} 条"}

    def export_archive_index(self) -> list[dict[str, Any]]:
        """导出归档索引，供指标查询服务提供历史数据说明。"""
        return [
            {
                "实验编码": r.get("实验编码", ""),
                "结束时间": r.get("结束时间", ""),
                "归档位置": r.get("归档位置", ""),
                "保留等级": r.get("保留等级", ""),
            }
            for r in store.rows(self.MODULE) if r.get("status") in ("已归档", "恢复中")
        ]
