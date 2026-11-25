# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 协同教育推送（PC017）

教师端与班主任端**不存在隶属管理关系**，只存在协同教育学生的关系。
任课教师对所代课程班级的平时考试／学习状态，由服务端按企业微信通讯录＋教务处课表的
任课绑定（teacher post_id → class_id＋科目）自动定向推送到该班班主任端，
便于班主任统筹学生成长。

红线：
  * 单向、定向、脱敏、只读派生区；不进六级行政链、不参与逐级推送与催办、不考核不留痕
  * 不是三端打通、不是共享上下文、不是 PC016 同类池（跨端跨类）
  * 不写 spaces／space_events／chat_turns／sessions，推送前后 shared_json 完全相等校验
  * 不出学生名单、分数／排名、原始作答、心理明细、家长电话等敏感字段
  * 成绩／考试域未接入派生区时按既有红线降级，不编造分数与旧值
"""
from tasks.domain import models
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.shared import db


class CoeduForbidden(Exception):
    """权限／绑定不满足：服务端拒绝并记审计，前端不得绕过。"""


class ContextPolluted(Exception):
    """推送前后共享上下文不一致：判定上下文污染。"""


# ---------------------------------------------------------------- 演示任课绑定
# PC010：企微通讯录没有任课班级与科目来源，正式上线须由教务处补录、信息化处写入绑定表。
# 以下仅为样本内置演示数据，用于验收「一个教师多班 → 多个班主任」「一个班多位任课教师」。
DEMO_LINKS = (
    ("p_teacher1", "teacher1", "何老师（演示·纯教师）", "2611", "语文"),
    ("p_teacher1", "teacher1", "何老师（演示·纯教师）", "2607", "语文"),
    ("p_xhc_teacher", "Tiao", "徐海潮", "2607", "数学"),
    ("p_fc_teacher", "coredump", "方成", "2611", "计算机基础"),
)


def ensure_links():
    """幂等写入演示绑定；已有正式绑定（source 不含「演示」）不被覆盖。"""
    for post, uid, name, cid, subj in DEMO_LINKS:
        db.exec_(
            "INSERT OR IGNORE INTO coedu_links"
            "(teacher_post_id,teacher_user_id,teacher_name,class_id,subject,source,status) "
            "VALUES(?,?,?,?,?,?, 'active')",
            (post, uid, name, cid, subj, "演示样本内置（PC010 待教务处补录）"),
        )
    return db.q("SELECT * FROM coedu_links WHERE status='active' "
                "ORDER BY teacher_post_id, class_id, subject")


def _scrub(obj):
    """白名单＋黑名单二次过滤：只保留班级级脱敏汇总与组织元数据。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in models.COEDU_FORBIDDEN_FIELDS:
                continue
            if k not in models.COEDU_PUSH_FIELDS:
                continue
            out[k] = _scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_scrub(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return None


def _session(session_id):
    s = org.get_session(session_id)
    if not s:
        return None, "会话无效或已过期，请重新用企业微信 userid 解析登录态"
    row = db.q("SELECT * FROM org_posts WHERE post_id=?", (s["post_id"],), one=True)
    if row:
        s.update({"name": row["name"], "post_name": row["post_name"],
                  "agent_name": row["agent_name"], "dept_path": row["dept_path"],
                  "level_pending": bool(row.get("level_pending", 0)),
                  "in_chain": bool(row.get("in_chain", 1)),
                  "committee_line": bool(row["committee_line"])})
    return s, None


def _bzr_for(class_id):
    """收件人由服务端判定：只认该班班主任端 L1 职务，不认行政端／团线／待确认层级。"""
    for r in db.q("SELECT * FROM org_posts WHERE status='active' AND portal='headteacher' "
                  "AND level='L1' AND in_chain=1 AND committee_line=0"):
        if str(class_id) in [str(x) for x in db.loads(r["class_ids"], [])]:
            return r
    return None


def _links_for(teacher_post_id):
    return [r for r in ensure_links() if r["teacher_post_id"] == teacher_post_id]


def _shared_snapshot(session_id):
    row = db.q("SELECT shared_json FROM spaces WHERE session_id=? AND status='active'",
               (session_id,), one=True)
    return row["shared_json"] if row else ""


def _metric_payload(ctx, link, metric):
    """班级级脱敏汇总：只走只读派生区，不查 answers／scores，不返回名单。"""
    cid = str(link["class_id"])
    subj = link["subject"]
    f = growth.fixture(cid) if cid in growth.FIXTURE_PATHS else None
    meta = (f.get("_meta", {}) if f else {})
    ov = growth.class_overview(ctx, cid) if f else {}
    base = {
        "class_id": cid, "subject": subj,
        "batch": meta.get("ready_date", "") or "批次未标注（数据就绪日为空）",
        "source": ov.get("source") or growth._source(),
        "zone": ov.get("zone") or "派生区（只读）",
        "available": bool(f),
        "derived_pending": bool(meta.get("derived_pending")),
        "ready_date": meta.get("ready_date", ""),
    }
    if not f:
        return dict(base, available=False,
                    reason="该班级未接入成长导航只读派生区快照：" + cid,
                    rule="不拿其他班示例值或旧值顶替；本级协同推送暂停该数字")
    if metric == "exam":
        # 成绩／考试域尚未接入（COVERAGE_PENDING）：通道就绪，但绝不编造分数／排名
        return dict(
            base,
            batch=meta.get("ready_date", "") or "考试批次未接入（成绩域未接派生区）",
            exam_numeric_available=False,
            attention_count=ov.get("attention_count"),
            reconcile=ov.get("leave_reconcile"),
            reason="成绩／考试域尚未接入成长导航只读派生区（仅学籍／归寝／请假三类已就绪）",
            rule="不推送分数、排名、原始作答与明细，不以示例值或旧值估算；"
                 "待教务处按考试批次导入并接入派生区后本指标自动生效",
            note="平时考试协同提示：只推派生区需关注人数与建议动作；"
                 "不生成定性结论、评语与处分建议，班主任据此写记录仍走两段式人审",
        )
    # status：班级级脱敏学情汇总，口径未对齐／未就绪按既有红线标注
    wn = growth.weekly_numbers(ctx, cid)
    return dict(
        base,
        size=f["class"].get("size"),
        attendance_rate=ov.get("attendance_rate"),
        attention_count=ov.get("attention_count"),
        balance_unbalanced=ov.get("balance_unbalanced"),
        reconcile=ov.get("leave_reconcile"),
        degraded=bool(wn.get("degraded")),
        note="学习状态＝班级级脱敏汇总＋需关注人数＋建议动作；"
             "不出学生名单、原始作答、维度分与心理明细；"
             "数据未就绪≠未归，口径未对齐时暂停该数字、标注暂不可用",
    )


def _row(ctx, link, bzr, metric, payload, status, self_user):
    """组装一条推送记录（白名单字段），供预览与落库共用。"""
    return _scrub({
        "push_id": "coedu_preview" if status == "preview" else db.uid("cp_"),
        "ts": db.now(), "metric": metric,
        "metric_name": models.COEDU_METRIC_INDEX[metric]["name"],
        "class_id": str(link["class_id"]), "subject": link["subject"],
        "teacher_user_id": ctx["user_id"], "teacher_post_id": ctx["post_id"],
        "teacher_agent_id": ctx["agent_id"], "teacher_name": ctx.get("name", ""),
        "bzr_user_id": bzr["user_id"] if bzr else "",
        "bzr_post_id": bzr["post_id"] if bzr else "",
        "bzr_agent_id": bzr["agent_id"] if bzr else "",
        "bzr_name": bzr["name"] if bzr else "",
        "self_user": int(bool(self_user)), "status": status,
        **payload,
    })


def _record(row, ctx):
    db.exec_(
        "INSERT INTO coedu_pushes"
        "(id,ts,teacher_user_id,teacher_post_id,teacher_agent_id,teacher_name,"
        "class_id,subject,batch,metric,bzr_user_id,bzr_post_id,bzr_agent_id,bzr_name,"
        "summary_json,status,self_user) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["push_id"], row["ts"], row.get("teacher_user_id", ""), row.get("teacher_post_id", ""),
         row.get("teacher_agent_id", ""), row.get("teacher_name", ""),
         row["class_id"], row["subject"], row.get("batch", ""), row["metric"],
         row.get("bzr_user_id", ""), row.get("bzr_post_id", ""),
         row.get("bzr_agent_id", ""), row.get("bzr_name", ""),
         db.dumps(row), row["status"], int(row.get("self_user", 0))),
    )
    db.audit(ctx, "coedu.push", "ok", row["class_id"],
             "协同教育推送 %s → %s／%s（%s）；非隶属管理、不进六级链、未写任何空间共享上下文"
             % (row["metric"], row.get("bzr_post_id", "-"), row["class_id"], row["subject"]))


def _build(ctx, metric, persist):
    """生成定向推送；persist=False 为预览（不落库、不写收件箱）。"""
    if metric not in models.COEDU_METRIC_INDEX:
        return None, "未知协同教育指标：只支持 exam（平时考试）／status（学习状态）"
    if ctx["portal"] != "teacher":
        raise CoeduForbidden("只有教师端职务可发起协同教育推送；班主任端／行政端不得反向取数或代发")
    links = _links_for(ctx["post_id"])
    if not links:
        raise CoeduForbidden("该教师职务未绑定所代课程班级与科目（PC010 待教务处补录），不猜测收件人")
    before = _shared_snapshot(ctx["session_id"])
    rows, pushed, skipped = [], 0, 0
    for lk in links:
        cid = str(lk["class_id"])
        bzr = _bzr_for(cid)
        if not bzr:
            skipped += 1
            rows.append(_scrub({
                "class_id": cid, "subject": lk["subject"], "metric": metric,
                "available": False, "status": "no_recipient",
                "reason": "该班级在通讯录绑定表中没有班主任端 L1 职务，服务端不猜测收件人",
            }))
            continue
        payload = _metric_payload(ctx, lk, metric)
        if not payload.get("available"):
            skipped += 1
            rows.append(_scrub(dict(payload, metric=metric, status="degraded",
                                    subject=lk["subject"],
                                    bzr_post_id=bzr["post_id"])))
            continue
        self_user = bzr["user_id"] == ctx["user_id"] and bzr["post_id"] != ctx["post_id"]
        row = _row(ctx, lk, bzr, metric, payload,
                   "delivered" if persist else "preview", self_user)
        if persist:
            _record(row, ctx)
            pushed += 1
        rows.append(row)
    after = _shared_snapshot(ctx["session_id"])
    if before != after:
        db.audit(ctx, "coedu.pollution", "denied", "spaces",
                 "协同教育推送前后共享上下文不一致，已判定上下文污染")
        raise ContextPolluted("协同教育推送前后共享上下文不一致，已判定上下文污染并记审计")
    return {
        "metric": metric, "metric_name": models.COEDU_METRIC_INDEX[metric]["name"],
        "rows": rows, "row_count": len(rows),
        "recipient_count": len(links), "pushed_count": pushed if persist else 0,
        "skipped_count": skipped, "persisted": bool(persist),
        "space_shared_before": sorted(db.loads(before, {}).keys()),
        "space_shared_after": sorted(db.loads(after, {}).keys()),
        "no_context_pollution": before == after,
        "writes_to_space": False, "stateless": True,
        "rule": models.COEDU_RULE, "relation": models.COEDU_RELATION_NOTE,
        "isolation": models.COEDU_ISOLATION, "note": models.COEDU_NOTE,
    }, None


def preview(session_id, metric):
    ctx, err = _session(session_id)
    if err:
        return None, err
    return _build(ctx, metric, persist=False)


def push(session_id, metric):
    ctx, err = _session(session_id)
    if err:
        return None, err
    d, err = _build(ctx, metric, persist=True)
    if err:
        return None, err
    db.audit(ctx, "coedu.auto_push", "ok", ctx["post_id"],
             "协同教育自动推送完成 metric=%s 收件人=%d 已投=%d 降级跳过=%d"
             % (metric, d["recipient_count"], d["pushed_count"], d["skipped_count"]))
    return d, None


def links(session_id):
    ctx, err = _session(session_id)
    if err:
        return None, err
    mine = _links_for(ctx["post_id"]) if ctx["portal"] == "teacher" else []
    return {
        "portal": ctx["portal"], "link_count": len(mine),
        "links": [_scrub(dict(r, teacher_post_id=r["teacher_post_id"],
                              class_id=r["class_id"], subject=r["subject"],
                              teacher_user_id=r["teacher_user_id"],
                              teacher_name=r["teacher_name"], status=r["status"],
                              note=r["source"])) for r in mine],
        "link_note": models.COEDU_LINK_NOTE,
    }, None


def inbox(session_id, limit=50):
    """班主任端只读收件箱：只看本职务收到的协同教育推送，不反查教师端数据。"""
    ctx, err = _session(session_id)
    if err:
        return None, err
    if ctx["portal"] != "headteacher":
        raise CoeduForbidden("协同教育收件箱只面向班主任端；行政端不直接管学生个体、不接收学生级推送")
    rows = db.q("SELECT * FROM coedu_pushes WHERE bzr_post_id=? ORDER BY ts DESC, id DESC LIMIT ?",
                (ctx["post_id"], int(limit)))
    items = []
    for r in rows:
        d = _scrub(dict(db.loads(r["summary_json"], {})))
        d["push_id"] = r["id"]
        d["status"] = r["status"]
        items.append(d)
    return {
        "portal": ctx["portal"], "bzr_post_id": ctx["post_id"],
        "class_ids": ctx.get("class_ids", []), "inbox_count": len(items),
        "inbox": items, "relation": models.COEDU_RELATION_NOTE,
        "note": models.COEDU_NOTE,
    }, None


def view(session_id):
    """「协同教育」视图总览：关系定性、规则、指标、我的绑定／收件箱与最近推送留痕。"""
    ctx, err = _session(session_id)
    if err:
        return None, err
    ensure_links()
    lk = links(session_id)[0]
    ib = inbox(session_id)[0] if ctx["portal"] == "headteacher" else None
    recent = db.q("SELECT id,ts,metric,class_id,subject,bzr_post_id,teacher_post_id,status "
                  "FROM coedu_pushes ORDER BY ts DESC, id DESC LIMIT 20")
    # 留痕也按角色隔离：教师端只看自己发出的、班主任端只看自己收到的；行政端不接收学生级留痕
    if ctx["portal"] == "teacher":
        recent = [r for r in recent if r["teacher_post_id"] == ctx["post_id"]]
    elif ctx["portal"] == "headteacher":
        recent = [r for r in recent if r["bzr_post_id"] == ctx["post_id"]]
    else:
        recent = []
    pending = [{"id": c["id"], "topic": c["topic"], "status": c["status"]}
               for c in models.PENDING_CONFIRMATIONS if c["id"] in ("PC010", "PC017")]
    return {
        "portal": ctx["portal"], "portal_name": ctx.get("portal_name", ""),
        "post_id": ctx["post_id"], "user_id": ctx["user_id"],
        "rule": models.COEDU_RULE, "relation": models.COEDU_RELATION_NOTE,
        "link_note": models.COEDU_LINK_NOTE, "isolation": models.COEDU_ISOLATION,
        "note": models.COEDU_NOTE, "metrics": list(models.COEDU_METRICS),
        "links": lk["links"] if lk else [], "link_count": lk["link_count"] if lk else 0,
        "inbox": ib["inbox"] if ib else [], "inbox_count": ib["inbox_count"] if ib else 0,
        "push_count": len(recent),
        "pushes": [_scrub(dict(r)) for r in recent],
        "pending": pending,
    }, None
