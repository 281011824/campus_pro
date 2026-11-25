# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 同类横向协同（PC016 / v0.15）

用户 2026-11-12 口径：同一类如教师角色，智能体可以横向协同搜索聚合，但是自己的上下文不污染。

设计边界（与 PC014 自动匹配、PC015 共建空间及全部既有红线兼容）：
  * 同类池（pool）由服务端按 portal＋level＋in_chain＋committee_line＋level_pending
    五元组判定，pool_id 确定性生成；前端只传 session_id＋metric（＋可选 keyword），
    不得指定池、成员、身份或空间字段。
  * 聚合只走 growth 只读派生区，结果经 FEDERATION_AGGREGATE_FIELDS 白名单与
    FEDERATION_FORBIDDEN_FIELDS 黑名单二次过滤；名单、学生明细、敏感字段、自由文本
    与任何共建空间上下文键一律不返回。
  * 不污染：本模块不写 spaces／space_events／chat_turns／sessions，不调用 space 的
    任何写方法；聚合前后对当前角色空间的 shared_json 做完全相等校验，不一致即抛
    PollutionDetected（服务端返回错误并写审计）。
  * 留痕：只写 federation_queries（池 id、成员数、指标、时间戳、发起者三元组），
    不记业务数据原文、不记对话原文。
  * 无状态：每次请求重新取数、即取即弃，不缓存聚合结果、不新建会话与空间。
"""
import hashlib

from tasks.domain import models
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.shared import db


class PollutionDetected(Exception):
    """聚合前后共享上下文不一致（理论上不应发生，发生即判定上下文污染）。"""


POOL_DIMS = ("portal", "level", "in_chain", "committee_line", "level_pending")


def _dims(row):
    return (
        row.get("portal") or models.PORTAL_DEFAULT,
        row.get("level") or "L1",
        int(bool(row.get("in_chain", 1))),
        int(bool(row.get("committee_line", 0))),
        int(bool(row.get("level_pending", 0))),
    )


def pool_id_for(dims):
    raw = "|".join(str(x) for x in dims)
    return "pool_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _meta(row, pool=None):
    """成员元数据（组织层，不含任何学生数据）。"""
    return {
        "post_id": row["post_id"], "post_name": row["post_name"],
        "agent_id": row["agent_id"], "user_id": row["user_id"], "name": row["name"],
        "portal": row.get("portal") or models.PORTAL_DEFAULT,
        "level": row["level"], "in_chain": int(bool(row.get("in_chain", 1))),
        "committee_line": int(bool(row.get("committee_line", 0))),
        "level_pending": int(bool(row.get("level_pending", 0))),
        "class_ids": db.loads(row["class_ids"], []),
        "data_scope": row["data_scope"],
        "is_self": bool(pool and row["post_id"] == pool.get("self_post_id")),
        "status": "同类只读协同就绪",
    }


def all_pools():
    """全员同类池概览（只含组织架构元数据，不含任何学生数据）。"""
    groups = {}
    for r in org.directory():
        dims = _dims(r)
        pid = pool_id_for(dims)
        g = groups.setdefault(pid, {
            "pool_id": pid, "dims": dict(zip(POOL_DIMS, dims)),
            "portal": dims[0], "level": dims[1], "in_chain": dims[2],
            "committee_line": dims[3], "level_pending": dims[4],
            "portal_name": models.PORTAL_INDEX.get(dims[0], {}).get("name", dims[0]),
            "member_count": 0, "posts": [],
        })
        g["member_count"] += 1
        g["posts"].append({
            "post_id": r["post_id"], "post_name": r["post_name"],
            "agent_id": r["agent_id"], "user_id": r["user_id"], "name": r["name"],
        })

    def sort_key(x):
        pi = (models.PORTAL_ORDER.index(x["portal"])
              if x["portal"] in models.PORTAL_ORDER else 99)
        return (pi, x["level"], -x["member_count"], x["pool_id"])

    return sorted(groups.values(), key=sort_key)


def pool_of(session_id):
    """按当前会话的职务反查所属同类池（服务端判定，前端不可指定）。"""
    s = org.get_session(session_id)
    if not s:
        return None, "会话无效或已过期，请重新按企业微信职务装载"
    row = db.q("SELECT * FROM org_posts WHERE post_id=? AND status='active'",
               (s["post_id"],), one=True)
    if not row:
        return None, "当前职务不在企业微信通讯录有效职务中"
    dims = _dims(row)
    pid = pool_id_for(dims)
    members = [r for r in org.directory() if _dims(r) == dims]
    pool = {
        "pool_id": pid, "dims": dict(zip(POOL_DIMS, dims)),
        "portal": dims[0],
        "portal_name": models.PORTAL_INDEX.get(dims[0], {}).get("name", dims[0]),
        "level": dims[1], "in_chain": dims[2], "committee_line": dims[3],
        "level_pending": dims[4], "member_count": len(members),
        "self_post_id": row["post_id"],
    }
    return {"pool": pool, "members": members, "session": s, "row": row}, None


def peers(session_id):
    """当前同类池成员清单（脱敏组织元数据，不产生会话、不读空间上下文）。"""
    d, err = pool_of(session_id)
    if err:
        return None, err
    pool, members = d["pool"], d["members"]
    out = [_meta(r, pool) for r in members]
    return {
        "pool": pool, "peers": out, "member_count": len(out),
        "metrics": list(models.FEDERATION_METRICS),
        "rule": models.FEDERATION_RULE, "pool_note": models.FEDERATION_POOL_NOTE,
        "isolation": models.FEDERATION_ISOLATION, "note": models.FEDERATION_NOTE,
    }, None


def query_log(user_id, limit=20):
    return db.q(
        "SELECT ts,pool_id,metric,keyword_len,member_count,result FROM federation_queries "
        "WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


def view(session_id):
    """「横向协同」视图总览：当前池、全员池、指标、最近聚合留痕与隔离口径。"""
    d, err = pool_of(session_id)
    if err:
        return None, err
    pool, s = d["pool"], d["session"]
    pools = all_pools()
    return {
        "current_pool": pool, "pools": pools, "pool_count": len(pools),
        "metrics": list(models.FEDERATION_METRICS),
        "queries": query_log(s["user_id"]),
        "rule": models.FEDERATION_RULE,
        "pool_note": models.FEDERATION_POOL_NOTE,
        "isolation": models.FEDERATION_ISOLATION,
        "note": models.FEDERATION_NOTE,
    }, None


# ---------------------------------------------------------------- 只读派生区聚合
def _scrub(obj):
    """白名单＋黑名单二次过滤：只保留结构化脱敏键，绝不返回名单／明文／空间上下文。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in models.FEDERATION_FORBIDDEN_FIELDS:
                continue
            if k not in models.FEDERATION_AGGREGATE_FIELDS:
                continue
            out[k] = _scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_scrub(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return None


def _member_metric(row, metric, pool, ctx):
    """单个同类成员的只读派生区聚合：只返回白名单脱敏数字，不借用他人身份。"""
    base = _meta(row, pool)
    if metric == "roster":
        return dict(base, available=True,
                    note="岗位协同名册：只含组织架构元数据，不含任何学生数据")
    classes = db.loads(row["class_ids"], [])
    if not classes:
        return dict(base, available=False,
                    reason="该职务在企业微信通讯录／绑定表中未绑定班级，无可读派生区范围",
                    rule="不拿默认班级示例值或旧值顶替；池级汇总只统计已覆盖成员")
    cid = str(classes[0])
    if cid not in growth.FIXTURE_PATHS:
        return dict(base, available=False,
                    reason="班级未接入只读派生区快照：" + cid,
                    rule="不以其他班示例值或旧值替代；本级报告暂停该数字")
    if metric == "overview":
        d = growth.class_overview(ctx, cid)
    elif metric == "dorm":
        n = growth.weekly_numbers(ctx, cid)
        w = growth.call_tool("get_warning_summary", ctx, class_id=cid)
        wd = (w.get("data") or {}) if isinstance(w, dict) else {}
        d = {
            "class_id": cid, "warning_count": wd.get("warning_count"),
            "dorm_anomaly": n.get("dorm_anomaly"), "dorm_note": n.get("dorm_note"),
            "leave_note": n.get("leave_note"), "degraded": n.get("degraded"),
            "source": n.get("source"), "zone": "派生区（只读）",
            "note": "只写「需人工关注」与事实，不写结论、不带请假事由；未就绪≠未归",
        }
    elif metric == "readiness":
        r = growth.readiness(ctx, cid)
        f = growth.fixture(cid)
        meta = f.get("_meta", {})
        d = {
            "class_id": cid, "ready_date": meta.get("ready_date", ""),
            "ready_dates": f["dorm"].get("ready_dates", []),
            "reconcile_conflict": bool(meta.get("reconcile_conflict")),
            "reconcile_note": meta.get("reconcile_note", ""),
            "derived_pending": bool(meta.get("derived_pending")),
            "derived_pending_note": meta.get("derived_pending_note", ""),
            "coverage_ready": r["coverage_ready"],
            "coverage_pending": r["coverage_pending"],
            "no_full_profile": r["no_full_profile"],
            "data_ready_note": r["data_ready_note"],
            "mcp_tools": r["mcp_tools"],
            "field_whitelist": r["field_whitelist"],
            "field_blacklist": r["field_blacklist"],
            "no_direct_platform_access": r["no_direct_platform_access"],
            "token_scope_ok": r["token_scope_ok"],
            "source": growth._source(),
            "note": "当前画像仅学籍／归寝／请假三类，不得称完整学生画像",
        }
    else:
        d = {}
    return dict(base, available=True, **d)


def _aggregate(rows, metric, pool):
    """池级汇总：只统计已绑定班级且数据可用的成员，不补齐、不估算。"""
    covered = [r for r in rows if r.get("available")]

    def nums(k):
        return [r[k] for r in covered
                if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]

    totals = {}
    for k in ("size", "attention_count", "warning_count", "dorm_anomaly"):
        v = nums(k)
        totals["sum_" + k] = sum(v)
    a = nums("attention_count")
    totals["max_attention_count"] = max(a) if a else 0
    totals["degraded_members"] = len([r for r in covered if r.get("degraded")])
    totals["reconcile_conflict_members"] = len(
        [r for r in covered if r.get("reconcile_conflict") or r.get("leave_note")])
    totals["ready_date_members"] = len([r for r in covered if r.get("ready_date")])
    return {
        "metric": metric, "pool_id": pool["pool_id"],
        "pool_members": pool["member_count"], "covered_members": len(covered),
        "partial": len(covered) < pool["member_count"],
        "totals": totals,
        "note": "只统计已绑定班级且数据可用的成员；未绑定／未就绪／口径未对齐不补齐、不估算",
    }


def _shared_snapshot(session_id):
    """只读当前角色空间的共享上下文原文（用于聚合前后完全相等校验）。"""
    row = db.q("SELECT shared_json FROM spaces WHERE session_id=? AND status='active'",
               (session_id,), one=True)
    return row["shared_json"] if row else ""


def _audit_query(ctx, pool, metric, kw, member_count, result):
    db.exec_(
        "INSERT INTO federation_queries(ts,pool_id,user_id,post_id,agent_id,level,portal,"
        "metric,keyword_len,member_count,result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (db.now(), pool["pool_id"], ctx.get("user_id", "-"), ctx.get("post_id", "-"),
         ctx.get("agent_id", "-"), ctx.get("level", "-"), ctx.get("portal", "-"),
         metric, len(kw or ""), member_count, result),
    )


def search(session_id, metric, keyword=""):
    """同类池横向只读搜索聚合。返回一次性结果，不写回任何空间共享上下文。"""
    if metric not in models.FEDERATION_METRIC_INDEX:
        return None, "未知聚合指标：只支持 roster／overview／dorm／readiness 四类"
    d, err = pool_of(session_id)
    if err:
        return None, err
    pool, members, s, row = d["pool"], d["members"], d["session"], d["row"]
    ctx = dict(s, name=row["name"], post_name=row["post_name"],
               agent_name=row["agent_name"])
    before = _shared_snapshot(session_id)
    kw = (keyword or "").strip()[:20]
    if kw:
        sel = [r for r in members
               if kw in (r["post_name"] or "") or kw in (r["name"] or "")
               or kw in (r["user_id"] or "") or kw in (r["post_id"] or "")]
    else:
        sel = members
    rows = [_scrub(_member_metric(r, metric, pool, ctx)) for r in sel]
    aggregate = _scrub(_aggregate(rows, metric, pool))
    after = _shared_snapshot(session_id)
    if before != after:
        _audit_query(ctx, pool, metric, kw, len(members), "pollution_detected")
        db.audit(ctx, "federation.pollution", "denied", pool["pool_id"],
                 "聚合前后共享上下文不一致，已判定上下文污染")
        raise PollutionDetected("聚合前后共享上下文不一致，已判定上下文污染并记审计")
    _audit_query(ctx, pool, metric, kw, len(members), "ok")
    db.audit(ctx, "federation.search", "ok", pool["pool_id"],
             "同类池横向只读聚合 metric=%s members=%d；未写任何空间共享上下文"
             % (metric, len(members)))
    return {
        "pool": pool, "metric": metric,
        "metric_name": models.FEDERATION_METRIC_INDEX[metric]["name"],
        "keyword": kw, "rows": rows, "row_count": len(rows),
        "aggregate": aggregate,
        "space_shared_before": sorted(db.loads(before, {}).keys()),
        "space_shared_after": sorted(db.loads(after, {}).keys()),
        "no_context_pollution": before == after,
        "writes_to_space": False, "stateless": True,
        "rule": models.FEDERATION_RULE, "pool_note": models.FEDERATION_POOL_NOTE,
        "isolation": models.FEDERATION_ISOLATION, "note": models.FEDERATION_NOTE,
    }, None
