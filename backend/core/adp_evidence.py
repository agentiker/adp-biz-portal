"""Render business answers exclusively from this execution's tool receipts."""

from sqlalchemy import select

from integrations.adp.provider import allowlisted_evidence
from model.platform import PlatformToolCall


async def reconcile_tool_result(db, *, context_id, query: str) -> dict:
    calls = list((await db.execute(select(PlatformToolCall).where(
        PlatformToolCall.ExecutionContextId == context_id,
        PlatformToolCall.ToolName.in_(("shipment.lookup", "shipment.schedule", "shipment.milestones")),
        PlatformToolCall.Status == "completed",
    ).order_by(PlatformToolCall.StartedAt, PlatformToolCall.Id))).scalars())
    result = {
        "query": query.strip().upper(), "title": "业务查询结果",
        "status": "upstream_error", "auditOutcome": "missing_tool_evidence",
        "summary": "本轮没有可核实的业务查询结果，请稍后重试。", "evidence": [],
    }
    if not calls:
        return result
    # Multiple records or failed subqueries cannot be silently folded into one answer.
    outcomes = {call.Outcome for call in calls}
    if outcomes - {"found"}:
        status = ("upstream_error" if "upstream_error" in outcomes else
                  "needs_clarification" if outcomes & {"multiple_matches", "needs_clarification"} else "not_found")
        result.update(status=status, auditOutcome=status, summary={
            "upstream_error": "业务系统暂时不可用，请稍后重试。",
            "needs_clarification": "请补充一个完整的订单号、提单号或箱号后重试。",
            "not_found": "未找到当前企业可访问的业务记录，请检查查询编号。",
        }[status])
        return result
    if len({call.QueryHash for call in calls}) > 1:
        result.update(status="needs_clarification", auditOutcome="conflicting_tool_evidence",
                      summary="本轮查询涉及不同编号，请每次查询一个完整编号。")
        return result
    values = {}
    for call in calls:
        for item in allowlisted_evidence(call.Evidence):
            if item["label"] in values and values[item["label"]]["value"] != item["value"]:
                result.update(status="needs_clarification", auditOutcome="conflicting_tool_evidence",
                              summary="本轮查询涉及不同业务记录，请每次查询一个完整编号。")
                return result
            values[item["label"]] = item
    evidence = list(values.values())
    if not evidence:
        return result
    prefix = "【模拟数据，仅供联调】\n" if any("M3 Mock /" in i["source"] for i in evidence) else ""
    result.update(status="found", auditOutcome="found", evidence=evidence,
                  summary=prefix + "\n".join(f'{i["label"]}：{i["value"]}' for i in evidence))
    return result
