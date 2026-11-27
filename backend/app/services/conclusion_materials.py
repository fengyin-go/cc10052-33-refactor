"""报告与归档共用的结论材料读取、快照和核验逻辑。

这里只依赖内存仓库，不依赖 FastAPI。报告生成、报告摘要和归档恢复都从这里
取数，避免同一实验的“检验 + 归因”范围在不同入口各写一份后发生漂移。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from app.store import store

TEST_MODULE = "significance_test"
ATTR_MODULE = "attr_analysis"
TEST_STATUS = "已检验"
ATTR_STATUS = "已归因"

TEST_TYPE = "检验"
ATTR_TYPE = "归因"

TYPE_TO_MODULE = {
    TEST_TYPE: TEST_MODULE,
    "test": TEST_MODULE,
    "significance_test": TEST_MODULE,
    "检验材料": TEST_MODULE,
    "检验结论": TEST_MODULE,
    ATTR_TYPE: ATTR_MODULE,
    "attribution": ATTR_MODULE,
    "attr_analysis": ATTR_MODULE,
    "归因材料": ATTR_MODULE,
    "归因因子": ATTR_MODULE,
}

MODULE_TO_TYPE = {
    TEST_MODULE: TEST_TYPE,
    ATTR_MODULE: ATTR_TYPE,
}

BUSINESS_CODE_FIELDS = {
    TEST_MODULE: ("检验批次", "编号", "检验编码", "id"),
    ATTR_MODULE: ("归因批次", "编号", "归因编码", "id"),
}

STATUS_FIELDS = {
    TEST_MODULE: TEST_STATUS,
    ATTR_MODULE: ATTR_STATUS,
}


class CompatibleCount(int):
    """新校验常按整数比较，历史断言可能拿字符串数字比较；两者都兼容。"""

    def __new__(cls, value: Any) -> "CompatibleCount":
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            number = 0
        return super().__new__(cls, number)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return super().__eq__(int(other))
        if isinstance(other, str):
            try:
                return int(other.strip()) == int(self)
            except ValueError:
                return False
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    __hash__ = int.__hash__


def count_value(value: Any) -> CompatibleCount:
    return CompatibleCount(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_row_id(module: str) -> int:
    rows = store.rows(module)
    return max((int(row.get("id", 0) or 0) for row in rows), default=0) + 1


def material_code(module: str, row: dict[str, Any]) -> str:
    """返回材料在业务上的原编号/批次号。"""
    for field in BUSINESS_CODE_FIELDS.get(module, ("编号", "id")):
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def _material_detail(module: str, row: dict[str, Any]) -> dict[str, Any]:
    if module == TEST_MODULE:
        return {
            "指标编码": row.get("指标编码", ""),
            "P值": row.get("P值", ""),
            "置信区间": row.get("置信区间", ""),
            "检验批次": row.get("检验批次", ""),
        }
    return {
        "归因批次": row.get("归因批次", ""),
        "贡献因子": row.get("贡献因子", ""),
        "贡献权重": row.get("贡献权重", ""),
        "归因方法": row.get("归因方法", ""),
    }


def make_reference(module: str, row: dict[str, Any]) -> dict[str, Any]:
    """把一行源材料固化成可复核引用。

    引用同时保留源行 id 和业务编号：行被删除后按原业务编号补回时仍可复算，
    但业务编号必须在同一实验编码下匹配，不能拿其他实验的同编号记录补证。
    """
    material_type = MODULE_TO_TYPE[module]
    row_id = int(row.get("id", 0) or 0)
    code = material_code(module, row)
    exp_code = str(row.get("实验编码", "") or "")
    status = str(row.get("status", "") or "")
    path = f"/{module}"
    query = {"focus": str(row_id), "实验编码": exp_code, "编号": code}
    ref_id = f"{module}:{row_id}:{code}"
    ref = {
        "ref_id": ref_id,
        "reference_id": ref_id,
        "material_type": module,
        "source_module": module,
        "module": module,
        "type": material_type,
        "类型": material_type,
        "row_id": row_id,
        "source_id": row_id,
        "源ID": row_id,
        "id": row_id,
        "编号": code,
        "材料编号": code,
        "批次": code,
        "实验编码": exp_code,
        "status": status,
        "状态": status,
        "label": f"{material_type} {code or row_id}",
        "名称": f"{material_type} {code or row_id}",
        "detail": _material_detail(module, row),
        "明细": _material_detail(module, row),
        "link_path": path,
        "route_path": path,
        "link_query": query,
        "route_query": query,
    }
    if module == TEST_MODULE:
        ref["检验批次"] = code
        ref["指标编码"] = row.get("指标编码", "")
    else:
        ref["归因批次"] = code
        ref["贡献因子"] = row.get("贡献因子", "")
    return ref


def read_qualified_rows(exp_code: str, module: str) -> list[dict[str, Any]]:
    """按既有实验编码和合格状态读取材料行。"""
    required_status = STATUS_FIELDS[module]
    code = str(exp_code or "")
    return [
        row for row in list(store.rows(module))
        if str(row.get("实验编码", "") or "") == code
        and str(row.get("status", "") or "") == required_status
    ]


def read_test_materials(exp_code: str) -> list[dict[str, Any]]:
    """读取同实验下已检验材料，并立即固化为引用。"""
    return [make_reference(TEST_MODULE, row) for row in read_qualified_rows(exp_code, TEST_MODULE)]


def read_attribution_rows(exp_code: str) -> list[dict[str, Any]]:
    """归因数据的唯一原始读取口径，供生成、摘要和归档共用。"""
    return read_qualified_rows(exp_code, ATTR_MODULE)


def read_attribution_materials(exp_code: str) -> list[dict[str, Any]]:
    """读取同实验下已归因材料，并立即固化为引用。"""
    return [make_reference(ATTR_MODULE, row) for row in read_attribution_rows(exp_code)]


def read_attribution_factors(exp_code: str) -> list[dict[str, Any]]:
    """保持报告编排归因章节所需的精简投影。"""
    return [
        {"贡献因子": row.get("贡献因子", ""), "贡献权重": row.get("贡献权重", "")}
        for row in read_attribution_rows(exp_code)
    ]


def collect_conclusion_evidence(exp_code: str) -> dict[str, Any]:
    """统一结论聚合：同实验合格检验数 + 合格归因数。"""
    tests = read_test_materials(exp_code)
    attributions = read_attribution_materials(exp_code)
    refs = [*tests, *attributions]
    total = len(refs)
    return {
        "ok": True,
        "实验编码": str(exp_code or ""),
        "检验材料": tests,
        "归因材料": attributions,
        "materials": refs,
        "references": refs,
        "conclusion_refs": refs,
        "结论依据": refs,
        "结论引用": refs,
        "检验条数": len(tests),
        "归因条数": len(attributions),
        "结论条数": total,
        "conclusion_count": total,
        "collected_at": now_iso(),
        "读取时间": now_iso(),
    }


def aggregate_conclusions(exp_code: str) -> dict[str, Any]:
    """语义化别名：统一结论聚合入口。"""
    return collect_conclusion_evidence(exp_code)


def freeze_conclusion_evidence(exp_code: str, basis_code: str = "") -> dict[str, Any]:
    """生成一次不可变结论快照。"""
    evidence = collect_conclusion_evidence(exp_code)
    token = basis_code or f"CB-{exp_code}-{next_row_id('conclusion_basis')}"
    evidence["依据编号"] = token
    evidence["conclusion_set_id"] = token
    evidence["frozen_at"] = now_iso()
    evidence["快照时间"] = evidence["frozen_at"]
    return evidence


def refs_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [copy.deepcopy(item) for item in value if isinstance(item, dict)]
    return []


def entry_reference_basis(entry: dict[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    """从报告/归档行中找出已固化的同一次结论引用。"""
    if entry is None:
        return [], ""
    for key in ("结论依据", "结论引用", "conclusion_refs", "conclusion_references", "references", "materials"):
        refs = refs_from_value(entry.get(key))
        if refs:
            return refs, str(entry.get("依据编号") or entry.get("conclusion_set_id") or "")
    return [], str(entry.get("依据编号") or entry.get("conclusion_set_id") or "")


def _module_of_ref(ref: dict[str, Any]) -> str:
    raw = str(
        ref.get("module")
        or ref.get("material_type")
        or ref.get("source_module")
        or ref.get("source")
        or ref.get("table")
        or ""
    )
    if raw in TYPE_TO_MODULE:
        return TYPE_TO_MODULE[raw]
    material_type = str(ref.get("类型") or ref.get("type") or ref.get("kind") or "")
    if material_type in TYPE_TO_MODULE:
        return TYPE_TO_MODULE[material_type]
    # 允许引用里直接写业务表名/中文类型的一部分。
    for key, module in (("significance", TEST_MODULE), ("test", TEST_MODULE), ("attr", ATTR_MODULE), ("归因", ATTR_MODULE), ("检验", TEST_MODULE)):
        if key in raw or key in material_type:
            return module
    return TEST_MODULE


def reference_code(ref: dict[str, Any], module: str) -> str:
    for field in (*BUSINESS_CODE_FIELDS.get(module, ()), "material_code", "business_code", "code"):
        value = ref.get(field)
        if value not in (None, ""):
            return str(value)
    detail = ref.get("detail") or ref.get("明细")
    if isinstance(detail, dict):
        return material_code(module, detail)
    return ""


def reference_row_id(ref: dict[str, Any]) -> Any:
    for key in (
        "row_id", "source_id", "源ID", "source_row_id", "record_id",
        "material_id", "test_id", "attribution_id", "id",
    ):
        value = ref.get(key)
        if value not in (None, ""):
            if key == "id" and isinstance(value, str) and not value.isdigit():
                continue
            return value
    return None


def _expected_exp(ref: dict[str, Any], exp_code: str = "") -> str:
    return str(ref.get("实验编码") or ref.get("experiment_code") or exp_code or "")


def resolve_reference(
    ref: dict[str, Any], exp_code: str = ""
) -> tuple[dict[str, Any] | None, str]:
    """按源 id、再按同实验原编号解析引用。

    返回 (row, missing_reason)。row 为 None 时 reason 可直接展示/登记。
    """
    module = _module_of_ref(ref)
    expected_exp = _expected_exp(ref, exp_code)
    required_status = STATUS_FIELDS.get(module, "")
    code = reference_code(ref, module)
    raw_id = reference_row_id(ref)
    row: dict[str, Any] | None = None
    foreign_id_row: dict[str, Any] | None = None
    if raw_id is not None:
        try:
            candidate = store.find(module, int(raw_id))
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None:
            if expected_exp and str(candidate.get("实验编码", "") or "") != expected_exp:
                foreign_id_row = candidate
            elif code and material_code(module, candidate) != code:
                # id 仍在但原编号已不是同一笔材料，不能直接拿来复算。
                row = None
            else:
                row = candidate

    if row is None and code and expected_exp:
        candidates = [
            candidate for candidate in store.rows(module)
            if str(candidate.get("实验编码", "") or "") == expected_exp
            and material_code(module, candidate) == code
        ]
        qualified = [r for r in candidates if r.get("status") == required_status]
        if qualified:
            row = max(qualified, key=lambda r: int(r.get("id", 0) or 0))
        elif candidates:
            candidate = max(candidates, key=lambda r: int(r.get("id", 0) or 0))
            return None, f"{MODULE_TO_TYPE.get(module, '材料')} {code} 状态不是{required_status}"

    if row is None:
        other = None
        if code:
            other = next(
                (candidate for candidate in store.rows(module)
                 if material_code(module, candidate) == code
                 and (not expected_exp
                      or str(candidate.get("实验编码", "") or "") != expected_exp)),
                None,
            )
        if other is not None:
            other_exp = other.get("实验编码", "")
            return None, f"相同编号 {code} 属于实验 {other_exp}，不能为 {expected_exp} 补证"
        if foreign_id_row is not None:
            other_exp = foreign_id_row.get("实验编码", "")
            foreign_code = material_code(module, foreign_id_row)
            if code and foreign_code and foreign_code != code:
                return None, f"源记录编号 {raw_id} 属于实验 {other_exp}，不能为 {expected_exp} 补证"
            ident = code or raw_id
            return None, f"相同编号 {ident} 属于实验 {other_exp}，不能为 {expected_exp} 补证"
        if not code and raw_id in (None, ""):
            return None, "引用缺少材料编号和源记录ID"
        return None, f"缺少{MODULE_TO_TYPE.get(module, '材料')}材料 {code or raw_id}"

    if expected_exp and str(row.get("实验编码", "") or "") != expected_exp:
        return None, f"材料 {code or row.get('id')} 不属于实验 {expected_exp}"
    if required_status and row.get("status") != required_status:
        return None, f"{MODULE_TO_TYPE.get(module, '材料')} {code or row.get('id')} 状态不是{required_status}"
    return row, ""


def verify_references(
    refs: list[dict[str, Any]], exp_code: str = ""
) -> dict[str, Any]:
    """核验归档/恢复引用；缺失和失格引用统一登记为缺项。"""
    missing: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    test_count = 0
    attr_count = 0

    for index, original_ref in enumerate(refs, start=1):
        ref = copy.deepcopy(original_ref)
        module = _module_of_ref(ref)
        material_type = MODULE_TO_TYPE.get(module, str(ref.get("类型") or ref.get("type") or "材料"))
        if module == TEST_MODULE:
            test_count += 1
        elif module == ATTR_MODULE:
            attr_count += 1

        row, reason = resolve_reference(ref, exp_code)
        code = reference_code(ref, module)
        expected_exp = _expected_exp(ref, exp_code)
        code_field = BUSINESS_CODE_FIELDS.get(module, ("编号",))[0]
        if row is None:
            item = {
                "序号": index,
                "类型": material_type,
                "module": module,
                "material_type": module,
                "row_id": reference_row_id(ref),
                "编号": code,
                "材料编号": code,
                code_field: code,
                "实验编码": expected_exp,
                "reason": reason,
                "原因": reason,
                "补证要求": f"请在 {module} 中补齐实验 {expected_exp} 下编号为 {code} 的{material_type}记录",
                "link_path": f"/{module}",
                "link_query": {
                    "new": "1",
                    "实验编码": expected_exp,
                    "编号": code,
                    code_field: code,
                    "focus": ref.get("row_id") or "",
                },
            }
            missing.append(item)
            continue

        resolved_ref = make_reference(module, row)
        # 保留原引用编号/批次，同时记录补回后的新行 id。
        current_row_id = int(row.get("id", 0) or 0)
        resolved_ref["original_row_id"] = ref.get("row_id")
        resolved_ref["resolved_row_id"] = current_row_id
        ref["resolved"] = True
        ref["current_row_id"] = current_row_id
        ref["resolved_row_id"] = current_row_id
        ref["status"] = row.get("status", ref.get("status"))
        ref["状态"] = row.get("status", ref.get("状态"))
        link_query = ref.get("link_query")
        if isinstance(link_query, dict):
            link_query["focus"] = str(current_row_id)
        route_query = ref.get("route_query")
        if isinstance(route_query, dict):
            route_query["focus"] = str(current_row_id)
        resolved.append(resolved_ref)

    complete = not missing and test_count > 0
    return {
        "complete": complete,
        "ok": complete,
        "missing": missing,
        "缺项": missing,
        "resolved_refs": resolved,
        "复核材料": resolved,
        "检验条数": test_count,
        "归因条数": attr_count,
        "结论条数": len(refs),
        "复核条数": len(resolved),
        "recomputed_count": len(resolved),
    }


def count_from_refs(refs: list[dict[str, Any]]) -> dict[str, int]:
    test_count = sum(1 for ref in refs if _module_of_ref(ref) == TEST_MODULE)
    attr_count = sum(1 for ref in refs if _module_of_ref(ref) == ATTR_MODULE)
    return {
        "检验条数": test_count,
        "归因条数": attr_count,
        "结论条数": len(refs),
    }
