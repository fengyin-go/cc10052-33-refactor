"""报告生成器领域服务：管理实验分析报告的模板编排、数据窗口聚合与生成重试。

数据链路位置：报告生产层，消费归因分析与显著性检验的结论数据，按模板聚合成
分析报告，并把成品交给报告分发推送给业务接收方。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.conclusion_materials import (
    collect_conclusion_evidence,
    count_from_refs,
    count_value,
    entry_reference_basis,
    freeze_conclusion_evidence,
    read_attribution_factors,
    read_test_materials,
)
from app.store import store


class ReportGenService(BaseModuleService):
    MODULE = "report_gen"
    ENTITY = "分析报告"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["报告编码", "实验编码", "报告模板", "数据窗口", "生成状态"]
    REQUIRED_FIELDS = ["报告编码", "实验编码", "报告模板"]
    STATUS_ORDER = ["排队中", "生成中", "已完成", "生成失败"]
    ACTION_RULES = {"开始生成": "生成中", "重试生成": "生成失败"}
    ACTION_METHODS = {
        "开始生成": "generate_report",
        "生成报告": "generate_report",
        "generate_report": "generate_report",
        "重试生成": "retry_failed",
        "retry_failed": "retry_failed",
        "归档结论": "archive_finished",
        "写入归档": "archive_finished",
        "archive_finished": "archive_finished",
        "确认报告": "confirm_report",
        "确认结论": "confirm_report",
        "confirm_report": "confirm_report",
        "查看摘要": "compose_summary",
        "compose_summary": "compose_summary",
        "summary": "compose_summary",
        "查看材料": "report_materials",
        "report_materials": "report_materials",
        "materials": "report_materials",
    }
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：报告编排与成品分发 ----

    def generate_report(self, entry_id: int) -> dict[str, Any]:
        """聚合检验与归因结论生成报告，完成后登记分发批次。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "排队中":
            return {"ok": False, "message": "仅排队中报告可生成"}
        exp_code = str(entry.get("实验编码", ""))
        evidence = freeze_conclusion_evidence(
            exp_code, basis_code=f"report-conclusions-{entry_id}"
        )
        significant = evidence["检验材料"]
        attributed = evidence["归因材料"]
        if not significant:
            entry["status"] = "生成失败"
            entry["生成状态"] = "生成失败"
            entry["abnormal"] = True
            entry["失败原因"] = "无已检验结论"
            return {"ok": False, "message": "实验无已检验结论，报告生成失败"}
        conclusion_count = evidence["结论条数"]
        entry["status"] = "已完成"
        entry["生成状态"] = "已完成"
        entry["pending"] = False
        entry["abnormal"] = False
        entry["结论条数"] = count_value(conclusion_count)
        entry["检验条数"] = count_value(evidence["检验条数"])
        entry["归因条数"] = count_value(evidence["归因条数"])
        entry["conclusion_count"] = conclusion_count
        entry["依据编号"] = evidence["依据编号"]
        entry["conclusion_set_id"] = evidence["依据编号"]
        entry["结论依据"] = evidence["结论依据"]
        # 与“结论依据”指向同一次快照；摘要和归档都从这里取引用。
        entry["结论引用"] = entry["结论依据"]
        entry["材料快照时间"] = evidence["frozen_at"]
        dist_rows = store.rows("report_dist")
        dist_rows.append({
            "id": max((int(r.get("id", 0)) for r in dist_rows), default=0) + 1,
            "分发批次": f"RD-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}",
            "报告编码": entry.get("报告编码", ""),
            "接收方": "实验负责人",
            "分发渠道": "站内信",
            "送达状态": "排队中",
            "status": "排队中",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": f"报告已生成（结论 {entry['结论条数']} 条）并排队分发"}

    def retry_failed(self, entry_id: int) -> dict[str, Any]:
        """重试生成失败报告，重新校验数据依赖后回到排队。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "生成失败":
            return {"ok": False, "message": "仅生成失败报告可重试"}
        exp_code = str(entry.get("实验编码", ""))
        has_result = bool(read_test_materials(exp_code))
        if not has_result:
            return {"ok": False, "message": "依赖的检验结论仍未就绪，暂不能重试"}
        entry["status"] = "排队中"
        entry["生成状态"] = "排队中"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["重试次数"] = str(int(entry.get("重试次数", "0") or 0) + 1)
        return {"ok": True, "message": f"报告已回到排队（第 {entry['重试次数']} 次重试）"}

    def batch_generate(self) -> dict[str, Any]:
        """批量生成全部排队中报告。"""
        queued = [r for r in store.rows(self.MODULE) if r.get("status") == "排队中"]
        done, failed = 0, 0
        for row in queued:
            if self.generate_report(int(row.get("id", 0))).get("ok"):
                done += 1
            else:
                failed += 1
        return {"ok": True, "message": f"批量生成完成：成功 {done}，失败 {failed}"}

    def read_conclusion_materials(self, exp_code: str) -> dict[str, Any]:
        """生成与摘要共用的结论聚合入口。"""
        return collect_conclusion_evidence(exp_code)

    def get_conclusion_count(self, exp_code: str) -> int:
        return int(collect_conclusion_evidence(exp_code)["结论条数"])

    def calculate_conclusion_count(self, exp_code: str) -> int:
        return self.get_conclusion_count(exp_code)

    def consume_from_attr_analysis(self, exp_code: str) -> list[dict[str, Any]]:
        """读取归因分析层的因子权重，编排报告归因章节。"""
        return read_attribution_factors(exp_code)

    def consume_from_exp_design(self, exp_code: str) -> dict[str, Any]:
        """读取实验设计层方案信息，写入报告背景章节。"""
        exp = next((r for r in store.rows("exp_design") if r.get("实验编码") == exp_code), None)
        if exp is None:
            return {"ok": False, "message": f"实验方案 {exp_code} 不存在"}
        return {
            "ok": True,
            "实验名称": exp.get("实验名称", ""),
            "分组策略": exp.get("分组策略", ""),
            "状态": exp.get("status", ""),
        }

    def compose_summary(self, entry_id: int) -> dict[str, Any]:
        """合成报告摘要文本，包含显著结论与归因因子数量。

        已生成/已确认报告优先使用生成时固化的同一次结论引用；尚未生成的报告
        仍按当前符合资格的材料实时聚合，保持原有“只有归因也能看摘要”的行为。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "报告不存在"}
        exp_code = str(entry.get("实验编码", ""))
        refs, basis_id = entry_reference_basis(entry)
        snapshot = bool(refs)
        if refs:
            counts = count_from_refs(refs)
            materials = refs
        else:
            evidence = collect_conclusion_evidence(exp_code)
            counts = {
                "检验条数": evidence["检验条数"],
                "归因条数": evidence["归因条数"],
                "结论条数": evidence["结论条数"],
            }
            materials = evidence["结论依据"]
            basis_id = evidence["依据编号"] if "依据编号" in evidence else ""
        sig_count = counts["检验条数"]
        attr_count = counts["归因条数"]
        total = counts["结论条数"]
        archive_links = self._archive_links(entry_id, str(entry.get("报告编码", "")))
        return {
            "ok": True,
            "摘要": f"实验 {exp_code} 共 {sig_count} 条显著结论、{attr_count} 个归因因子",
            "数据窗口": entry.get("数据窗口", ""),
            "实验编码": exp_code,
            "报告编码": entry.get("报告编码", ""),
            "archives": archive_links,
            "关联归档": archive_links,
            "结论条数": total,
            "conclusion_count": total,
            "检验条数": sig_count,
            "归因条数": attr_count,
            "结论依据": materials,
            "结论引用": materials,
            "出处": materials,
            "结论出处": materials,
            "来源材料": materials,
            "sources": materials,
            "materials": materials,
            "references": materials,
            "依据编号": basis_id or entry.get("依据编号", ""),
            "snapshot": snapshot,
            "is_snapshot": snapshot,
        }

    def report_materials(self, entry_id: int) -> dict[str, Any]:
        """返回报告实际采用的材料引用，以及可办理的关联归档。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "报告不存在"}
        exp_code = str(entry.get("实验编码", ""))
        refs, basis_id = entry_reference_basis(entry)
        adopted = bool(refs)
        if not refs:
            evidence = collect_conclusion_evidence(exp_code)
            refs = evidence["结论依据"]
            basis_id = evidence["依据编号"]
        counts = count_from_refs(refs) if adopted else {
            "检验条数": sum(1 for r in refs if r.get("material_type") == "significance_test"),
            "归因条数": sum(1 for r in refs if r.get("material_type") == "attr_analysis"),
            "结论条数": len(refs),
        }
        archive_links = self._archive_links(entry_id, str(entry.get("报告编码", "")))
        return {
            "ok": True,
            "report_id": entry_id,
            "id": entry_id,
            "报告编码": entry.get("报告编码", ""),
            "实验编码": exp_code,
            "status": entry.get("status", ""),
            "adopted": adopted,
            "snapshot": adopted,
            "依据编号": basis_id or entry.get("依据编号", ""),
            "结论条数": entry.get("结论条数", counts["结论条数"]),
            "conclusion_count": counts["结论条数"],
            **counts,
            "materials": refs,
            "结论依据": refs,
            "结论引用": refs,
            "出处": refs,
            "结论出处": refs,
            "来源材料": refs,
            "sources": refs,
            "references": refs,
            "archives": archive_links,
            "关联归档": archive_links,
        }

    def _archive_links(self, entry_id: int, report_code: str) -> list[dict[str, Any]]:
        return [
            {
                "archive_id": int(row.get("id", 0) or 0),
                "id": int(row.get("id", 0) or 0),
                "实验编码": row.get("实验编码", ""),
                "status": row.get("status", ""),
                "依据状态": row.get("依据状态", ""),
                "结论条数": row.get("结论条数", row.get("归档结论条数", "")),
            }
            for row in store.rows("exp_archive")
            if int(row.get("报告ID", 0) or 0) == entry_id
            or (report_code and str(row.get("报告编码", "") or "") == report_code)
        ]

    def get_materials(self, entry_id: int) -> dict[str, Any]:
        return self.report_materials(entry_id)

    def get_evidence(self, entry_id: int) -> dict[str, Any]:
        return self.report_materials(entry_id)

    def get_used_materials(self, entry_id: int) -> dict[str, Any]:
        return self.report_materials(entry_id)

    def used_materials(self, entry_id: int) -> dict[str, Any]:
        return self.report_materials(entry_id)

    def summary(self, entry_id: int) -> dict[str, Any]:
        return self.compose_summary(entry_id)

    def confirm_report(self, entry_id: int) -> dict[str, Any]:
        """确认报告结论引用；确认后摘要和归档共用同一次快照。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "报告不存在"}
        refs, basis_id = entry_reference_basis(entry)
        if not refs:
            evidence = freeze_conclusion_evidence(
                str(entry.get("实验编码", "")),
                basis_code=str(entry.get("依据编号") or f"report-conclusions-{entry_id}"),
            )
            if evidence["检验条数"] == 0:
                return {"ok": False, "message": "实验无已检验结论，报告不能确认"}
            refs = evidence["结论依据"]
            basis_id = evidence["依据编号"]
            entry["结论依据"] = refs
            entry["结论引用"] = refs
            entry["依据编号"] = basis_id
            entry["conclusion_set_id"] = basis_id
            entry["结论条数"] = count_value(evidence["结论条数"])
        entry["确认状态"] = "已确认"
        entry["confirmed"] = True
        entry["确认时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "message": "报告结论引用已确认", "entry": entry}

    def confirm(self, entry_id: int) -> dict[str, Any]:
        return self.confirm_report(entry_id)

    def archive_finished(self, entry_id: int) -> dict[str, Any]:
        """把完成报告的结论引用写入实验归档库。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") not in ("已完成", "已确认"):
            return {"ok": False, "message": "仅已完成报告可归档"}
        refs, basis_id = entry_reference_basis(entry)
        if not refs:
            evidence = collect_conclusion_evidence(str(entry.get("实验编码", "")))
            refs = evidence["结论依据"]
            basis_id = evidence["依据编号"]
        count = entry.get("结论条数", len(refs))
        archive_rows = store.rows("exp_archive")
        archive_id = max((int(r.get("id", 0)) for r in archive_rows), default=0) + 1
        archive_row = {
            "id": archive_id,
            "报告ID": entry_id,
            "report_id": entry_id,
            "报告编码": entry.get("报告编码", ""),
            "实验编码": entry.get("实验编码", ""),
            "结束时间": datetime.now(timezone.utc).isoformat(),
            "结论摘要": f"报告 {entry.get('报告编码', '')} 结论 {count} 条",
            "归档位置": f"report/{entry.get('报告编码', '')}",
            "保留等级": "标准",
            "status": "待归档",
            "pending": True,
            "abnormal": False,
            "结论条数": count_value(count),
            "归档结论条数": count_value(count),
            "实际发布结论条数": count_value(count),
            "conclusion_count": int(count) if str(count).isdigit() else count,
            "依据编号": basis_id or entry.get("依据编号", f"report-conclusions-{entry_id}"),
            "conclusion_set_id": entry.get("conclusion_set_id", basis_id),
            "结论依据": refs,
            "结论引用": refs,
            "依据状态": "待领取",
            "缺项": [],
            "恢复历史": [],
            "领取历史": [],
            "历史记录": [],
            "办理历史": [],
        }
        archive_rows.append(archive_row)
        entry["归档记录ID"] = archive_id
        entry["关联归档ID"] = archive_id
        return {
            "ok": True,
            "message": "报告结论已写入归档库",
            "archive_id": archive_id,
            "entry": archive_row,
        }
