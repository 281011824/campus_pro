# -*- coding: utf-8 -*-
"""德育工作台独立后台的业务路由；HTTP 与 Redis 传输由调用方负责。"""
from tasks.domain import models
from tasks.domain.collaboration import (federation, space)
from tasks.domain.growth import (datadomains, growth)
from tasks.domain.identity import (access, org)
from tasks.modules.head_teacher import writes
from tasks.shared import (config, db, wecom)
from tasks.modules.head_teacher import (coedu, push, redpoint, secretary)


_TRUSTED_IDENTITY = ""


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def ok(data):
    return {"code": 0, "data": data}


def full_ctx(session_id):
    s = org.get_session(session_id)
    if s and _TRUSTED_IDENTITY and s.get("user_id") != _TRUSTED_IDENTITY:
        raise ApiError(403, "identity_mismatch", "登录身份与会话身份不一致")
    if not s:
        raise ApiError(401, "session_invalid", "会话无效或已过期，请重新用企业微信 userid 解析登录态")
    row = db.q("SELECT * FROM org_posts WHERE post_id=?", (s["post_id"],), one=True)
    if row:
        s.update({"name": row["name"], "post_name": row["post_name"],
                  "dept_path": row["dept_path"], "agent_name": row["agent_name"],
                  "level_source": row.get("level_source", ""),
                  "level_pending": bool(row.get("level_pending", 0)),
                  "in_chain": bool(row.get("in_chain", 1)),
                  "auto_level": row.get("auto_level", "")})
    return s


def need_ctx(body):
    bad = org.assert_clean(body)
    if bad:
        raise ApiError(400, "forbidden_fields",
                       "前端禁止传 level／agent_id／data_scope／curLevel（防伪造越权）；已拒绝并记审计：" + ",".join(bad))
    return full_ctx(body.get("session_id", ""))


def token_scope_guard(ctx):
    """单 token 校长角色不得给 L1 下发数据（MCP 工具扩展记录 v0.1 · 一票否决）。"""
    if config.TOKEN_SCOPE != "role_class" and ctx.get("level") == "L1":
        db.audit(ctx, "token.scope", "denied", "growth", "单 token 校长角色未改造，禁止给班主任下发数据")
        raise ApiError(403, "token_scope_required",
                       "当前 MCP 为单 token（校长角色）、工具不做学生范围过滤；"
                       "正式给班主任试用前必须换成按角色／班级过滤的 token")


# ---------------------------------------------------------------- 路由表
def route(method, path, q, b):
    # ---------------- 健康 / 配置 / 就绪度
    if path == "/api/v1/health" and method == "GET":
        return {"status": "running", "settings": config.public_settings(),
                "readiness": config.readiness(),
                "note": "企业微信只作触达层；交互层＝成长导航系统·班主任工作台（内嵌）"}
    if path == "/api/v1/health/readiness" and method == "GET":
        return config.readiness()
    if path == "/api/v1/settings" and method == "GET":
        return config.public_settings()

    # ---------------- 组织架构（企业微信通讯录为主）
    if path == "/api/v1/org/directory" and method == "GET":
        return {"source": "企业微信通讯录" if config.WECOM_MODE == "real" else "内置示例通讯录（mock）",
                "posts": org.directory(), "levels": models.LEVELS,
                "portals": models.PORTALS, "portal_note": models.PORTAL_NOTE,
                "rule": "三端＝工作台／数据边界；一个 userid 可跨端持有多个 post_id，一岗一智能体；"
                        "前端只传 userid、目标 post_id 与可选 portal（筛选意图）"}
    if path == "/api/v1/org/persons" and method == "GET":
        return {"persons": org.persons(), "portals": models.PORTALS}
    if path == "/api/v1/org/posts" and method == "GET":
        uid_ = q.get("userid", "")
        return {"posts": org.posts_of(_TRUSTED_IDENTITY or uid_),
                "portals": org.portals_of(uid_) if uid_ else [],
                "portal_note": models.PORTAL_NOTE, "isolation": models.PORTAL_ISOLATION}
    if path == "/api/v1/org/conflicts" and method == "GET":
        return org.conflicts()

    # ---------------- 三端（教师端／班主任端／行政端）＋ 统一入口卡片
    if path == "/api/v1/portals" and method == "GET":
        return org.portal_summary(_TRUSTED_IDENTITY or q.get("userid", "") or None)
    if path == "/api/v1/portal/summary" and method == "GET":
        return org.portal_summary(_TRUSTED_IDENTITY or q.get("userid", "") or None)
    if path == "/api/v1/portal/auto" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "自动匹配加载不得携带层级／智能体字段")
        uid_ = (_TRUSTED_IDENTITY or b.get("userid", "")).strip()
        if not uid_:
            raise ApiError(400, "userid_required", "缺少 userid")
        d, err = org.auto_match(uid_)
        if err:
            raise ApiError(403, "auto_match_forbidden", err)
        d["ctx"] = org.public_ctx(d["ctx"])
        return d

    # ---------------- 同类横向协同（PC016）：同类池只读聚合、上下文不污染
    if path.startswith("/api/v1/federation") and method == "POST":
        forged = [k for k in models.FEDERATION_FRONTEND_FORBIDDEN if k in b]
        if forged:
            db.audit({"user_id": b.get("userid")}, "federation.forge_reject", "denied",
                     "frontend_payload", "forbidden_fields=" + ",".join(forged))
            raise ApiError(400, "forbidden_fields",
                           "同类横向协同不得由前端指定池／成员／身份／空间字段：" + ",".join(forged))
    if path == "/api/v1/federation/pools" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)                                  # 校验会话，避免跨会话查池
        d, err = federation.view(sid)
        if err:
            raise ApiError(404, "pool_not_found", err)
        return d
    if path == "/api/v1/federation/peers" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)
        d, err = federation.peers(sid)
        if err:
            raise ApiError(404, "pool_not_found", err)
        return d
    if path == "/api/v1/federation/search" and method == "POST":
        ctx = need_ctx(b)
        d, err = federation.search(ctx["session_id"], str(b.get("metric", "")).strip(),
                                   str(b.get("keyword", "") or ""))
        if err:
            raise ApiError(400, "bad_metric_or_session", err)
        return d

    # ---------------- 协同教育推送（PC017）：教师端 → 所代课程班级班主任端
    # 关系定性：非隶属管理、只协同育人；不进六级行政链、不参与逐级推送与催办。
    # 前端只传 session_id＋metric；班级／科目／批次／收件人／身份字段一律由服务端反查。
    if path.startswith("/api/v1/coedu") and method == "POST":
        forged = [k for k in models.COEDU_FRONTEND_FORBIDDEN if k in b]
        if forged:
            db.audit({"user_id": b.get("userid")}, "coedu.forge_reject", "denied",
                     "frontend_payload", "forbidden_fields=" + ",".join(forged))
            raise ApiError(400, "forbidden_fields",
                           "协同教育推送不得由前端指定班级／科目／收件人／身份／空间字段：" + ",".join(forged))
    if path == "/api/v1/coedu/view" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)
        d, err = coedu.view(sid)
        if err:
            raise ApiError(404, "coedu_view_failed", err)
        return d
    if path == "/api/v1/coedu/links" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)
        d, err = coedu.links(sid)
        if err:
            raise ApiError(404, "coedu_links_failed", err)
        return d
    if path == "/api/v1/coedu/inbox" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)
        d, err = coedu.inbox(sid)
        if err:
            raise ApiError(404, "coedu_inbox_failed", err)
        return d
    if path == "/api/v1/coedu/preview" and method == "POST":
        ctx = need_ctx(b)
        d, err = coedu.preview(ctx["session_id"], str(b.get("metric", "")).strip())
        if err:
            raise ApiError(400, "bad_metric_or_session", err)
        return d
    if path == "/api/v1/coedu/push" and method == "POST":
        ctx = need_ctx(b)
        d, err = coedu.push(ctx["session_id"], str(b.get("metric", "")).strip())
        if err:
            raise ApiError(400, "bad_metric_or_session", err)
        return d

    # ---------------- 共建空间（PC015）：秘书智能体＋工作台共享上下文
    if path.startswith("/api/v1/space") and method == "POST":
        forged = [k for k in models.SPACE_FRONTEND_FORBIDDEN if k in b]
        if forged:
            db.audit({"user_id": b.get("userid")}, "space.forge_reject", "denied",
                     "frontend_payload", "forbidden_fields=" + ",".join(forged))
            raise ApiError(400, "forbidden_fields",
                           "共建空间不得由前端指定 space_id／身份／权限字段：" + ",".join(forged))
    if path == "/api/v1/space" and method == "GET":
        sid = q.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)                                  # 校验会话有效，避免跨会话读空间
        d, err = space.view(sid)
        if err:
            raise ApiError(404, "space_not_found", err)
        return d
    if path == "/api/v1/spaces" and method == "GET":
        uid_ = q.get("userid", "").strip()
        if not uid_:
            raise ApiError(400, "userid_required", "缺少 userid")
        return space.spaces_of(uid_)
    if path == "/api/v1/space/focus" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "共建空间不得携带身份／权限字段")
        sid = b.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        ctx = full_ctx(sid)
        module = str(b.get("module", "")).strip()
        if not module:
            raise ApiError(400, "module_required", "缺少工作台模块名")
        shared, err = space.focus(sid, module, b.get("class_id"), b.get("masked"))
        if err:
            raise ApiError(403, "space_write_forbidden", err)
        db.audit(ctx, "space.focus", "ok", module,
                 "工作台模块 %s 写入共享上下文（班级 %s）" % (module, b.get("class_id") or "—"))
        return {"space_id": space.space_id_for(dict(ctx, session_id=sid)),
                "shared": shared, "updated_by": "workbench",
                "note": "工作台已写入共享上下文；秘书智能体在同一空间内立即可见"}
    if path == "/api/v1/space/event" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "共建空间不得携带身份／权限字段")
        sid = b.get("session_id", "").strip()
        if not sid:
            raise ApiError(400, "session_required", "缺少 session_id")
        full_ctx(sid)
        # 前端来源固定为工作台；秘书侧由服务端在 /api/v1/chat 内部写入，前端不得冒充
        shared, err = space.write_shared(sid, "workbench", b.get("patch"))
        if err:
            raise ApiError(403, "space_write_forbidden", err)
        return {"shared": shared, "updated_by": "workbench",
                "note": "只收白名单结构化脱敏键；自由文本、身份字段与字段黑名单已拒绝"}
    if path == "/api/v1/portal/cards" and method == "GET":
        uid_ = q.get("userid", "").strip()
        if not uid_:
            raise ApiError(400, "userid_required", "缺少 userid")
        return org.portal_cards(uid_)
    if path == "/api/v1/portal/enter" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "进入入口不得携带层级／智能体字段")
        uid_, portal = b.get("userid", "").strip(), b.get("portal", "").strip()
        if not uid_ or not portal:
            raise ApiError(400, "userid_portal_required", "缺少 userid 或 portal")
        ctx, err = org.enter_portal(uid_, portal)
        if err:
            raise ApiError(403, "portal_forbidden", err)
        return {"ctx": org.public_ctx(ctx), "cards": org.portal_cards(uid_),
                "portals": org.portals_of(uid_),
                "note": "一个入口·卡片式单口选择：选中端后才装载智能体，未选端不产生会话上下文"}
    if path == "/api/v1/wecom/sync" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "同步请求不得携带层级／智能体字段")
        return org.sync_directory()

    # ---------------- 会话 / 职务切换
    if path == "/api/v1/session/resolve" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields",
                           "前端禁止传 level／agent_id／data_scope；服务端按企业微信通讯录判定")
        userid = b.get("userid", "").strip()
        if not userid:
            raise ApiError(400, "userid_required", "缺少 userid")
        ctx, err = org.resolve(userid, b.get("post_id"), b.get("portal"))
        if err:
            raise ApiError(403, "post_forbidden", err)
        return {"ctx": org.public_ctx(ctx), "portals": org.portals_of(userid),
                "posts": [
            {"post_id": p["post_id"], "post_name": p["post_name"],
             "agent_id": p["agent_id"], "level": p["level"],
             "portal": p["portal"], "primary_flag": p["primary_flag"]}
            for p in org.posts_of(userid)]}
    if path == "/api/v1/session/switch" and method == "POST":
        bad = org.assert_clean(b)
        if bad:
            raise ApiError(400, "forbidden_fields", "切换职务不得携带层级／智能体字段")
        ctx, err = org.switch(b.get("userid", ""), b.get("post_id") or None, b.get("portal") or None)
        if err:
            raise ApiError(403, "post_forbidden", err)
        return {"ctx": org.public_ctx(ctx), "portals": org.portals_of(ctx["user_id"]),
                "note": "上一职务（端）会话上下文、待确认写入、催办草稿已全部作废；"
                        "三端数据互不打通；审计按 userid＋post_id＋agent_id 留痕"}
    if path.startswith("/api/v1/session/") and method == "GET":
        return {"ctx": org.public_ctx(full_ctx(path.split("/")[-1]))}

    # ---------------- 秘书对话
    if path == "/api/v1/chat" and method == "POST":
        ctx = need_ctx(b)
        text = str(b.get("text", ""))
        pending = writes.pending_for(ctx["session_id"])
        res = secretary.handle(ctx, text, pending)
        if res.get("audit"):
            a = res["audit"]
            db.audit(ctx, a[0], a[1], a[2], a[3] if len(a) > 3 else "")
        if res.get("persist"):
            db.exec_("INSERT INTO chat_turns(ts,session_id,role,text,card_json) VALUES(?,?,?,?,?)",
                     (db.now(), ctx["session_id"], "user", text, None))
            db.exec_("INSERT INTO chat_turns(ts,session_id,role,text,card_json) VALUES(?,?,?,?,?)",
                     (db.now(), ctx["session_id"], "assistant", res["text"],
                      db.dumps(res["card"]) if res.get("card") else None))
        # PC015：秘书智能体写共享上下文（只写结构化标签，不写回复原文）
        shared = space.record_secretary(ctx["session_id"], ctx, res)
        return {"reply": res["text"], "card": res.get("card"), "kind": res.get("kind"),
                "view": res.get("view"), "pending_id": res.get("pending_id"),
                "ctx": {"level": ctx["level"], "post_name": ctx.get("post_name"),
                        "agent_id": ctx["agent_id"], "agent_name": ctx.get("agent_name")},
                "space_shared": shared,
                "http_status": res.get("status", 200)}

    # ---------------- 两段式写入
    if path == "/api/v1/write/confirm" and method == "POST":
        ctx = need_ctx(b)
        p = writes.pending_for(ctx["session_id"])
        if not p:
            raise ApiError(404, "no_pending", "没有待确认的写入草稿")
        decision = str(b.get("decision", "")).strip()
        if decision in ("confirm", "确认", "确定", "同意"):
            r = writes.confirm(ctx, p, "confirm")
        elif decision in ("cancel", "取消", "不要", "算了"):
            r = writes.confirm(ctx, p, "cancel")
        else:
            r = secretary.out(models.REPLY["ambiguous"])
            db.audit(ctx, "write.ambiguous", "clarify", p["id"])
        return {"reply": r["text"], "card": r.get("card"), "kind": r.get("kind")}
    if path == "/api/v1/write/pending" and method == "GET":
        ctx = full_ctx(q.get("session_id", ""))
        return {"pending": writes.pending_for(ctx["session_id"])}
    if path == "/api/v1/write/records" and method == "GET":
        return {"records": db.q("SELECT * FROM write_records ORDER BY id DESC LIMIT 50")}

    # ---------------- 周报（人审归档）
    if path == "/api/v1/report/weekly" and method == "GET":
        ctx = full_ctx(q.get("session_id", ""))
        token_scope_guard(ctx)
        return {"card": secretary.weekly_card(ctx)}
    if path == "/api/v1/report/archive" and method == "POST":
        ctx = need_ctx(b)
        r = writes.archive(ctx, b.get("report_id", ""))
        return {"reply": r["text"], "card": r.get("card")}
    if path == "/api/v1/report/watchlist" and method == "GET":
        ctx = full_ctx(q.get("session_id", ""))
        token_scope_guard(ctx)
        return {"card": secretary.watchlist_card(ctx)}

    # ---------------- 试点班（2611 原型基准 / 2607 成长导航系统试点班）
    if path == "/api/v1/pilot/classes" and method == "GET":
        return growth.pilot_classes()
    if path == "/api/v1/pilot/snapshot" and method == "GET":
        cid = q.get("class_id", "2607")
        if cid not in growth.FIXTURE_PATHS:
            raise ApiError(404, "unknown_pilot_class", "未知试点班：" + cid)
        return {"snapshot": growth.class_snapshot(cid),
                "conflicts": [c for c in models.PENDING_CONFIRMATIONS
                              if c["id"] in ("PC005", "PC006", "PC007", "PC008", "PC009")],
                "rule": "仅聚合数字＋合成掩码名单；真实姓名／学号／宿舍／家长电话不进样本"}

    # ---------------- 数据域（实施方案十四域）与德育量化
    if path == "/api/v1/domains/status" and method == "GET":
        return datadomains.domains_status(q.get("class_id") or "2607")
    if path == "/api/v1/moral/summary" and method == "GET":
        ctx = full_ctx(q.get("session_id", ""))
        cid = q.get("class_id") or (ctx.get("class_ids") or ["2607"])[0]
        if not access.can_view_class(ctx.get("user_id", ""), cid):
            raise ApiError(403, "class_forbidden", "仅本班班主任可查看本班学生信息")
        period = q.get("period")
        try:
            return datadomains.moral_summary(cid, q.get("start"), q.get("end"), period, q.get("anchor"))
        except ValueError as exc:
            raise ApiError(400, "invalid_date_range", str(exc))
    if path == "/api/v1/moral/event" and method == "POST":
        ctx = need_ctx(b)
        cid = b.get("class_id") or (ctx.get("class_ids") or ["2607"])[0]
        eid = datadomains.add_behavior(cid, b.get("student_id", ""),
                                       b.get("polarity", "positive"),
                                       b.get("category", "其他"), int(b.get("points", 0)),
                                       b.get("fact", ""))
        db.audit(ctx, "moral.event", "ok", eid, "政教处登记；待班主任确认后计分")
        return {"event_id": eid, "status": "pending",
                "reply": "已登记为待确认事件，班主任确认后才计入德育量化"}
    if path == "/api/v1/moral/confirm" and method == "POST":
        ctx = need_ctx(b)
        return datadomains.confirm_behavior(ctx, b.get("event_id", ""),
                                            b.get("decision", "confirm"))
    if path.startswith("/api/v1/ingest/") and method == "POST":
        if b.get("token", "") != config.get("INGEST_TOKEN", "dev-ingest"):
            raise ApiError(403, "ingest_denied", "数据域写入令牌无效")
        domain = path.rsplit("/", 1)[-1]
        if domain not in datadomains.INGEST_SQL:
            raise ApiError(404, "unknown_domain", "未接入的数据域：" + domain)
        n = datadomains.ingest(domain, b)
        db.audit({"user_id": "-", "post_id": "-", "agent_id": "-"},
                 "domain.ingest", "ok", domain, "写入 %d 条" % n)
        return {"domain": domain, "accepted": n,
                "rule": "同一数据域只有一个采集入口、一个权威来源"}

    # ---------------- 成长导航只读派生区
    if path.startswith("/api/v1/growth/") and method == "GET":
        ctx = full_ctx(q.get("session_id", ""))
        token_scope_guard(ctx)
        fields = (q.get("fields") or "").split(",") if q.get("fields") else []
        growth.assert_derived(fields, ctx)
        # 前端可显式指定 class_id；否则按登录职务的 data_scope 自动带出（徐海潮→2607）
        cid = q.get("class_id", (ctx.get("class_ids") or ["2611"])[0])
        leaf = path.split("/api/v1/growth/")[1]
        if cid not in growth.FIXTURE_PATHS:
            # 未接入快照的班级：首页 KPI（numbers）降级为「暂不可用」，不抛错、不臆造
            if leaf == "numbers":
                return {"view": "numbers", "class_id": cid, "data": None,
                        "available": False,
                        "reason": "该班级尚未接入成长导航只读派生区快照",
                        "zone": "派生区（教师端只读）",
                        "no_direct_platform_access": config.NO_DIRECT_CAMPUS_ACCESS}
            raise ApiError(404, "unknown_class", "未知班级（只读派生区无该班快照）：" + str(cid))
        table = {
            "overview": lambda: growth.class_overview(ctx, cid),
            "attention": lambda: growth.attention_list(ctx, cid),
            "derived": lambda: growth.student_derived(ctx, q.get("student_id", "S007"), cid),
            "balance": lambda: growth.balance_view(ctx, cid),
            "goals": lambda: growth.goal_progress(ctx, cid),
            "profile": lambda: growth.growth_profile(ctx, cid),
            "readiness": lambda: growth.readiness(ctx, cid),
            "workitem": lambda: growth.work_item(ctx, q.get("item", "scores"), cid),
            "numbers": lambda: growth.weekly_numbers(ctx, cid),
        }
        if leaf not in table and not leaf.startswith("mcp/"):
            raise ApiError(404, "unknown_growth_view", "未知派生区视图：" + leaf)
        data = table[leaf]()
        db.audit(ctx, "growth.read", "ok", leaf, "只读派生区；不查 answers／scores；class_id=%s" % cid)
        return {"view": leaf, "class_id": cid, "data": data, "zone": "派生区（教师端只读）",
                "no_direct_platform_access": config.NO_DIRECT_CAMPUS_ACCESS}

    # 只读 MCP 工具调用（仅 5 个已跑通工具）
    if path == "/api/v1/mcp/call" and method == "POST":
        ctx = need_ctx(b)
        token_scope_guard(ctx)
        return growth.call_tool(b.get("tool", ""), ctx,
                                class_id=b.get("class_id") or (ctx.get("class_ids") or ["2611"])[0],
                                student_id=b.get("student_id"), date=b.get("date"))

    # ---------------- 六级推送流
    if path == "/api/v1/push/flow" and method == "GET":
        return push.flow()
    if path == "/api/v1/push/run" and method == "POST":
        # 业务参数用 push_level，避免与禁传字段 level（防伪造身份）冲突
        ctx = need_ctx(b)
        level = b.get("push_level") or ctx["level"]
        if level not in models.LEVEL_INDEX:
            raise ApiError(400, "bad_level", "未知层级")
        return push.auto_push(level, b.get("period"), trigger=b.get("trigger", "manual"))
    if path == "/api/v1/push/due" and method == "POST":
        return {"triggered": push.run_due()}

    # ---------------- 本周待确认红点（D2）＋转介单（D4-B）＋预警状态（D3 如实报告）
    if path == "/api/v1/todo/list" and method == "GET":
        return redpoint.list_items(full_ctx(q.get("session_id", "")))
    if path == "/api/v1/todo/refer" and method == "POST":
        ctx = need_ctx(b)
        r, err = redpoint.refer(ctx, str(b.get("student_id", "")).strip(),
                                str(b.get("category", "")).strip())
        if err:
            raise ApiError(403, "refer_forbidden", err)
        return r
    if path == "/api/v1/todo/note" and method == "POST":
        ctx = need_ctx(b)
        r, err = redpoint.note(ctx, str(b.get("category", "")).strip())
        if err:
            raise ApiError(400, "note_bad_category", err)
        return r
    if path == "/api/v1/todo/close" and method == "POST":
        ctx = need_ctx(b)
        r, err = redpoint.close(ctx, str(b.get("item_id", "")).strip())
        if err:
            raise ApiError(403, "close_forbidden", err)
        return r
    if path == "/api/v1/todo/referrals" and method == "GET":
        return {"slips": redpoint.slips(full_ctx(q.get("session_id", ""))),
                "l2_states": ["已接收", "处置中", "已销号"],
                "rule": "一件事一条流、一条上报线；L1 与 L2 可关联但不继承字段、不继承上下文；"
                        "转介只写事实不作定性，台账本体落点按 D4 现场确认"}
    if path == "/api/v1/todo/receipt" and method == "POST":
        ctx = need_ctx(b)
        r, err = redpoint.receipt(ctx, str(b.get("slip_id", "")).strip(),
                                  str(b.get("state", "")).strip())
        if err:
            raise ApiError(403, "receipt_forbidden", err)
        return r
    if path == "/api/v1/warning/state" and method == "GET":
        return redpoint.state()

    # ---------------- D5 周报定时（本机可证生成＋站内提醒；短信兜底属上线九项前置）
    if path == "/api/v1/scheduler/status" and method == "GET":
        return {"enabled": config.flag("ENABLE_SCHEDULER", False),
                "push_schedule": models.PUSH_SCHEDULE,
                "weekly_report_at": push.WEEKLY_REPORT_AT,
                "note": "ENABLE_SCHEDULER=true 时：六级推送按时刻表＋周报周一 06:50 自动生成草稿"
                        "＋企微站内提醒（零姓名零成绩）；归档人审点保留；短信兜底现场验"}
    if path == "/api/v1/scheduler/weekly" and method == "POST":
        return {"generated": push.weekly_due(trigger="manual"),
                "note": "手动触发与周一 06:50 定时走同一函数；草稿不归档，"
                        "人审点＝班主任确认归档（未经确认不进成长档案）"}

    # ---------------- 催办闭环
    if path == "/api/v1/dun/targets" and method == "GET":
        return {"targets": push.dun_targets(full_ctx(q.get("session_id", "")))}
    if path == "/api/v1/dun/create" and method == "POST":
        ctx = need_ctx(b)
        r, err = push.dun_create(ctx, b.get("to_userid", ""), b.get("content", ""),
                                 b.get("hours", 24))
        if err:
            raise ApiError(403, "dun_forbidden", err)
        return r
    if path == "/api/v1/dun/confirm" and method == "POST":
        ctx = need_ctx(b)
        r, err = push.dun_confirm(ctx, b.get("dun_id", ""))
        if err:
            raise ApiError(403, "dun_forbidden", err)
        return r
    if path == "/api/v1/dun/reply" and method == "POST":
        ctx = need_ctx(b)
        r, err = push.dun_reply(ctx, b.get("dun_id", ""), b.get("text", ""))
        if err:
            raise ApiError(403, "dun_forbidden", err)
        return r
    if path == "/api/v1/dun/list" and method == "GET":
        return {"duns": push.dun_list()}
    if path == "/api/v1/dun/escalate" and method == "POST":
        return {"escalated": push.escalate_overdue()}

    # ---------------- 台账 / 审计 / 提示词
    if path == "/api/v1/audit" and method == "GET":
        return {"logs": db.q("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100")}
    if path == "/api/v1/redline" and method == "GET":
        return {"counts": db.q("SELECT category,COUNT(*) AS n FROM redline_events GROUP BY category"),
                "note": "只记分类与三元组，绝不记请求内容（安全／舆情零系统留痕）"}
    if path == "/api/v1/agent/registry" and method == "GET":
        return {"agents": db.q("SELECT * FROM agent_registry ORDER BY level,agent_id"),
                "note": "一岗一智能体：一个 post_id 绑定唯一 agent_id，按职务独立装载"}
    if path == "/api/v1/agent/prompt" and method == "GET":
        return {"prompt": secretary.system_prompt_for(full_ctx(q.get("session_id", ""))),
                "llm_enabled": config.LLM_ENABLED}
    if path == "/api/v1/wecom/outbox" and method == "GET":
        return {"mode": config.WECOM_MODE, "messages": wecom.outbox(int(q.get("limit", 30)))}

    # 说明：/api/v1/wecom/callback 的 GET/POST 在 do_GET / do_POST 中单独处理
    # （URL 验证须返回明文 echostr，消息回调须返回加密 XML，均不能包 JSON）。

    raise ApiError(404, "not_found", "未知接口：" + method + " " + path)
