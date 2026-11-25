# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 岗位秘书引擎（规则版）

LLM_ENABLED=false 时走本规则引擎（可直接运行、可回归测试）；
LLM_ENABLED=true 时把 system_prompt_for() 注入大模型，但护栏仍在本层强制执行
（红线拦截、派生区校验、两段式写入、审计留痕不交给模型决定）。
意图优先级与《德育工作台_试点原型.html》reply() 完全一致。
"""
import re
from datetime import date
from pathlib import Path

from tasks.domain import models
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.shared import (config, db)

PROMPT_FILE = config.ROOT.parent / "02_系统提示词.md"


def _r(pattern):
    return re.compile(pattern)


RE_CANCEL = _r(r"^(取消|不要|算了)$")
RE_AMBIGUOUS = _r(r"^(嗯|行吧|好吧|随便|嗯嗯|可以|好的)$")
RE_OFFLINE = _r(models.OFFLINE_PATTERN)
RE_SENSITIVE = _r(r"家长电话|联系方式|家庭住址|身份证|学籍号|心理量表|测评结果|请假事由")
RE_PSYCH = _r(r"抑郁|心理问题|自杀|自伤|干预|预警原因|什么信号")
RE_EXTERNAL = _r(r"发给家长|通知家长|群发|发到群|发群里|处分说明|评语终稿|下结论|品行不好|定性")
RE_CROSS = _r(r"隔壁班|其他班|别的班|班级排名|全年级|年级排名|年级汇总|全校|全校排名|其他年级|跨年级")
RE_DERIVED = _r(models.DERIVED_FORBIDDEN_PATTERN)
RE_POST = _r(r"切换职务|兼任|我的职务|岗位切换|换职务|另一个职务|一岗一智能体|不同智能体")
RE_IDENTITY = _r(r"我是谁|识别|组织架构|通讯录|我的权限|为什么是|层级依据|登录|映射表")
RE_READINESS = _r(r"工具就绪|MCP|能接什么|已接入|单token|单\s*token|权限过滤|数据就绪|未就绪|对账|贴源"
                  r"|智慧校园|平台地址|部署|试用态|校内网|代码基线|完整画像|请假事由")
RE_SCORES = _r(r"成绩|学情|分数|月考|下滑|作业完成")
RE_TALENT = _r(r"特长|兴趣|优势|擅长|隐形优势|多元智能")
RE_PEER = _r(r"交友|同伴|朋友|同桌|人际|独处|四维|平衡|失衡")
RE_GOAL = _r(r"目标|六级|打卡|制定|规划")
RE_REPORT = _r(r"周报|简报|月报|态势|报告|汇总|一页纸|生成")
RE_DUN = _r(r"催办|催一下|提醒下级|督办")
RE_DISPATCH = _r(r"下发|布置|通知下级")
RE_PUSH = _r(r"上报|推送|推送流|报给|签发|五级|六级")
RE_WATCH = _r(r"需关注|关注清单|谁.*关注|最需要|风险学生|重点学生")
RE_TODO = _r(r"待确认红点|本周待确认|待确认事项|红点|转介|销号|劝返")
RE_WRITE = _r(r"加分|扣分|表扬|违纪|玩手机|迟到|旷课|记一笔|登记|记一下|德育|沟通|家访|联系家长|记录一次")
RE_BATCH = _r(r"批量|导入|CSV|座位表|课程表|排座|值日表|重排|导出|备份")
RE_DEGRADE = _r(r"数据.*(失败|不可用|暂停|没有)|口径|不一致|对不上")
RE_HELP = _r(r"你好|在吗|能做什么|帮助|功能|本级职责")
RE_SPACE = _r(r"共建空间|共享上下文|空间状态|工作台在看|当前空间|空间成员|谁在共建")
RE_FEDERATION = _r(r"横向协同|同类聚合|同类搜索|协同搜索|同类池|横向搜索|跨智能体聚合|"
                   r"聚合.*同类|其他老师|别的老师|其他班主任|别的班主任|一起汇总")
RE_COEDU = _r(r"协同教育|协同育人|推送给班主任|推给班主任|发给班主任|所代课程|任课班级|"
              r"平时考试.*推送|考试.*班主任|学习状态.*推送|班主任统筹|教师.*班主任.*推送")


def out(text, card=None, kind="text", status=200, persist=True,
        audit=None, pending_id=None, view=None):
    return {"text": text, "card": card, "kind": kind, "status": status,
            "persist": persist, "audit": audit, "pending_id": pending_id, "view": view}


def _iso_week(day=None):
    y, w, _ = (day or date.today()).isocalendar()
    return "%d-W%02d" % (y, w)


# ---------------------------------------------------------------- 一页纸周报卡片
def weekly_card(ctx):
    cids = ctx.get("class_ids") or []
    cid = str(cids[0]) if cids else ""
    if not cid:
        # 未绑定班级不得回落到任何默认班，避免把别的班数据展示给当前账号（数据域红线）
        return {
            "type": "weekly_report", "report_id": "", "title": "本周班级周报（一页纸）",
            "lines": ["当前账号尚未绑定班级，周报暂不可用。",
                      "请先在管理台「班主任管理」完成班级绑定后再查看。"],
            "numbers": {}, "attention": [], "status": "unavailable",
            "hint": models.REPLY["archive_hitl"],
        }
    n = growth.weekly_numbers(ctx, cid)
    att = growth.attention_list(ctx, cid)
    na = lambda v: v if v not in (None, "") else "暂不可用"
    lines = [
        "【%s · 班级周报（一页纸）· %s】" % (ctx.get("post_name") or "班主任", cid),
        "出勤率 %s ｜ 需关注 %d 人 ｜ 德育 %s ｜ 归寝异常 %s" % (
            na(n["attendance_rate"]), n["attention_count"], na(n["moral_delta"]),
            na(n["dorm_anomaly"])),
    ]
    for note in (n.get("attendance_note"), n.get("moral_note"), n["dorm_note"], n["leave_note"]):
        if note:
            lines.append("· " + note)
    lines.append("需关注清单（只含标记＋建议动作，不含原因与分数）：")
    for it in att["items"][:6]:
        lines.append("  %s ｜ %s ｜ %s" % (it["name_masked"], it["mark"], it["action"]))
    lines.append("数据源：" + n["source"])
    lines.append("班主任工作四项（附列）：成绩／学情、特长／兴趣、交友／同伴、目标制定；只读派生区")
    lines.append("未经确认不归档（人审点：周报确认归档）")

    # 读接口不重复造草稿：同一班级同一周复用已有草稿（已归档则原样返回归档态）
    week = _iso_week()
    payload = db.dumps({"numbers": n, "attention": att["items"]})
    row = db.q("SELECT id,status,payload_json FROM weekly_reports WHERE class_id=? AND week=? "
               "ORDER BY ts DESC LIMIT 1", (cid, week), one=True)
    if row:
        rid, status = row["id"], row["status"]
        if status == "draft" and row["payload_json"] != payload:
            db.exec_("UPDATE weekly_reports SET payload_json=? WHERE id=?", (payload, rid))
    else:
        rid, status = db.uid("wr_"), "draft"
        db.exec_("INSERT INTO weekly_reports(id,ts,class_id,week,level,payload_json,status) "
                 "VALUES(?,?,?,?,?,?,'draft')",
                 (rid, db.now(), cid, week, ctx.get("level", "L1"), payload))
    return {
        "type": "weekly_report", "report_id": rid, "title": "本周班级周报（一页纸）",
        "lines": lines, "numbers": n, "attention": att["items"], "status": status,
        "hint": models.REPLY["archive_hitl"],
    }


def watchlist_card(ctx):
    att = growth.attention_list(ctx, (ctx.get("class_ids") or ["2611"])[0])
    return {"type": "watchlist_digest", "title": "本班需关注清单（派生区）",
            "items": att["items"], "note": att["note"], "source": att["source"]}


def echo_card(ctx, kind, payload):
    return {"type": "write_echo", "title": "写入回显（确认后才落库）",
            "kind": models.WRITE_KINDS.get(kind, kind), "payload": payload,
            "hint": "请明确回复「确认」或「取消」；含糊回复不会触发写入。"}


def system_prompt_for(ctx):
    """LLM 模式的系统提示词＝部署包 02_系统提示词.md ＋ 当前职务上下文（不传 level 给前端）。"""
    base = ""
    try:
        base = PROMPT_FILE.read_text(encoding="utf-8")
    except Exception:
        base = "# 德育工作台 · 岗位秘书系统提示词（部署包 02_系统提示词.md）"
    dyn = ("\n\n## 当前会话上下文（服务端注入）\n"
           "- userid：%s\n- post_id：%s（%s）\n- agent_id：%s（%s）\n"
           "- 层级：%s（服务端判定，前端不可传）\n- 数据范围：%s\n"
           "- 字段白名单：%s\n- 当前工具就绪度：%s\n"
           % (ctx.get("user_id"), ctx.get("post_id"), ctx.get("post_name"),
              ctx.get("agent_id"), ctx.get("agent_name"), ctx.get("level"),
              ctx.get("data_scope"), "、".join(models.FIELD_WHITELIST),
              "仅 5 个只读 MCP 工具；画像仅学籍／归寝／请假三类"))
    portal = ctx.get("portal") or models.PORTAL_DEFAULT
    pinfo = models.PORTAL_INDEX.get(portal, {})
    psec = ("\n\n## 当前端（三端划分 · 服务端注入）\n"
            "- 端：%s（%s／%s）\n- 本端职责：%s\n- 本端工作台：%s\n"
            "- 本端数据边界：%s\n- 本端可用工具：%s\n"
            "- 与六级行政链的关系：%s\n- 本端红线：%s\n- 跨端隔离：%s\n"
            % (pinfo.get("name", portal), portal, pinfo.get("sub", ""),
               pinfo.get("focus", ""), "、".join(pinfo.get("desk", [])),
               pinfo.get("data_scope", ""), "、".join(pinfo.get("tools", [])),
               pinfo.get("chain", ""), pinfo.get("rule", ""), models.PORTAL_ISOLATION))
    # PC015：共建空间 —— 秘书智能体与工作台共享上下文（服务端注入，不含学生明细）
    ssec = ("\n\n## 共建空间（随角色，服务端注入）\n"
            "- 空间规则：%s\n- 共享上下文字段：%s\n"
            "- 共享范围与隔离：%s\n- 本端说明：%s\n"
            % (models.SPACE_RULE, "、".join(models.SPACE_SHARED_FIELDS),
               models.SPACE_ISOLATION, models.SPACE_NOTE))
    # PC016：同类横向协同 —— 只读聚合、上下文不污染（服务端注入，不含学生明细）
    fsec = ("\n\n## 同类横向协同（PC016，服务端注入）\n"
            "- 同类池规则：%s\n- 池判定维度：%s\n"
            "- 只读聚合指标：%s\n- 上下文不污染：%s\n"
            "- 与共建空间的关系：%s\n"
            % (models.FEDERATION_RULE, models.FEDERATION_POOL_NOTE,
               "、".join(m["id"] + "（" + m["name"] + "）" for m in models.FEDERATION_METRICS),
               models.FEDERATION_ISOLATION, models.FEDERATION_NOTE))
    # PC017：协同教育推送 —— 教师端 → 所代课程班级班主任端，非隶属管理、上下文不污染
    csec = ("\n\n## 协同教育推送（PC017，服务端注入）\n"
            "- 关系与通道规则：%s\n- 关系定性：%s\n"
            "- 任课绑定与收件人：%s\n"
            "- 可推送指标：%s\n- 上下文不污染：%s\n"
            "- 与既有机制的关系：%s\n"
            % (models.COEDU_RULE, models.COEDU_RELATION_NOTE, models.COEDU_LINK_NOTE,
               "、".join(m["id"] + "（" + m["name"] + "）" for m in models.COEDU_METRICS),
               models.COEDU_ISOLATION, models.COEDU_NOTE))
    return base + psec + ssec + fsec + csec + dyn


# ---------------------------------------------------------------- 主对话入口
def handle(ctx, text, pending=None):
    """返回 out() 结构；pending 为该会话当前待确认写入（由 server 传入）。"""
    s = (text or "").strip()
    L = models.LEVELS[models.LEVEL_INDEX.get(ctx.get("level", "L1"), 0)]

    # 0. 两段式写入的确认环节优先级最高
    if pending:
        if RE_CANCEL.match(s) or s in ("取消", "不要", "算了", "cancel"):
            return out(models.REPLY["cancel"], audit=("write.cancel", "ok", pending["id"]))
        if RE_AMBIGUOUS.match(s):
            return out(models.REPLY["ambiguous"], audit=("write.ambiguous", "clarify", pending["id"]))
        if s in ("确认", "确定", "同意", "confirm", "yes", "是"):
            from tasks.modules.head_teacher import writes
            return writes.confirm(ctx, pending, "confirm")
        return out(models.REPLY["ambiguous"], audit=("write.ambiguous", "clarify", pending["id"]))

    # 1. 取消
    if RE_CANCEL.match(s):
        return out(models.REPLY["cancel"])

    # 2. 人工通道：命中即回退电话／当面话术，零留痕（只记分类计数）
    if RE_OFFLINE.search(s):
        db.redline(ctx, "offline_channel")
        db.audit(ctx, "offline.intercept", "ok", "manual", "命中人工通道关键词，未生成、未转述")
        return out("【人工通道】" + models.OFFLINE_REPLY,
                   kind="offline", persist=False,
                   audit=("offline.intercept", "ok", "manual"))

    # 3. 敏感字段 / 心理区 / 对外定性
    if RE_SENSITIVE.search(s):
        db.redline(ctx, "sensitive_field")
        return out(models.REPLY["sensitive"], kind="forbidden", persist=False,
                   audit=("derived.sensitive", "denied", "field"))
    if RE_PSYCH.search(s):
        db.redline(ctx, "psych_zone")
        return out(models.REPLY["psych"], kind="forbidden", persist=False,
                   audit=("derived.psych", "denied", "psych_zone"))
    if RE_EXTERNAL.search(s):
        return out(models.REPLY["external"], kind="forbidden",
                   audit=("hitl.external", "denied", "external_release"))

    # 4. 跨范围取数 → 403 语义 + 审计
    if RE_CROSS.search(s):
        db.audit(ctx, "scope.cross", "denied", "cross_class")
        return out(models.REPLY["cross_scope"], kind="forbidden", status=403,
                   audit=("scope.cross", "denied", "cross_class"))

    # 5. 职务切换 / 身份说明
    if RE_POST.search(s):
        posts = org.posts_of(ctx["user_id"])
        lines = ["当前 userid：%s，共 %d 个兼任职务（企业微信通讯录为主，一岗一智能体）：" %
                 (ctx["user_id"], len(posts))]
        for p in posts:
            lines.append("  · %s → %s ／ %s（%s）%s" %
                         (p["post_id"], p["post_name"], p["agent_id"], p["level"],
                          " 【当前】" if p["post_id"] == ctx["post_id"] else ""))
        lines.append("切换职务请点顶栏「切换职务」；服务端校验 post_id 归属后清空上一职务上下文，"
                     "前端不传 level／agent_id／data_scope；审计按 userid＋post_id＋agent_id 留痕。")
        return out("\n".join(lines), card={"type": "post_switch", "posts": [
            {"post_id": p["post_id"], "post_name": p["post_name"],
             "agent_id": p["agent_id"], "level": p["level"]} for p in posts]},
            audit=("post.list", "ok", "directory"))
    if RE_IDENTITY.search(s):
        return out("当前 <b>%s %s</b>（%s）｜职务 %s｜智能体 %s（%s）｜数据范围 %s。"
                   "层级由服务端按企业微信通讯录部门路径＋岗位判定，前端只持 userid 与目标 post_id。" %
                   (ctx["level"], L["name"], ctx["user_id"], ctx["post_name"],
                    ctx["agent_id"], ctx.get("agent_name", ""), ctx["data_scope"]),
                   audit=("identity.explain", "ok", "session"))

    # 5b. 共建空间 / 共享上下文（PC015）：秘书与工作台共读一份共享上下文
    if RE_SPACE.search(s):
        from tasks.domain.collaboration import space as _sp
        v, err = _sp.view(ctx["session_id"])
        if err:
            return out("当前会话未共建空间：" + err, audit=("space.view", "denied", "session"))
        sh = v["shared"]
        focus_txt = "、".join("%s＝%s" % (k, sh[k]) for k in
                             ("focus_module", "focus_class", "focus_masked",
                              "last_intent", "last_card", "pending_write_id",
                              "ready_date", "turn_count") if k in sh) or "（尚无共建记录）"
        lines = [
            "【共建空间 · %s】" % v["space_id"],
            "· 角色：%s（%s）｜端：%s｜层级：%s" %
            (v["post_name"], v["post_id"], v["portal_name"], v["level"]),
            "· 空间成员：%s" % "＋".join("%s（%s）" % (m["role"], m["id"]) for m in v["members"]),
            "· 共享上下文：%s" % focus_txt,
            "· 最近共建留痕：%d 条（秘书智能体／工作台共同写入）" % v["event_count"],
            "· 秘书知道工作台当前模块与班级，工作台也能显示秘书刚生成的卡片与草稿。",
            "· 空间间隔离：切换职务即归档并清空本空间上下文，新空间不继承；三端数据互不打通。",
        ]
        return out("\n".join(lines), view="space",
                   card={"type": "space_view", "space_id": v["space_id"],
                         "members": v["members"], "shared": sh},
                   audit=("space.view", "ok", v["space_id"]))

    # 5c. 同类横向协同（PC016）：同类池只读搜索聚合，自己的上下文不污染
    if RE_FEDERATION.search(s):
        from tasks.domain.collaboration import federation as _fed
        v, err = _fed.view(ctx["session_id"])
        if err:
            return out("当前会话未解析到同类池：" + err,
                       audit=("federation.view", "denied", "session"))
        cp = v["current_pool"]
        q = _fed.query_log(ctx["user_id"], 5)
        lines = [
            "【同类横向协同 · %s】" % cp["pool_id"],
            "· 同类池判定：%s／%s／进链 %d／团线 %d／层级待确认 %d；池内 %d 个同类智能体" %
            (cp["portal_name"], cp["level"], cp["in_chain"], cp["committee_line"],
             cp["level_pending"], cp["member_count"]),
            "· 可横向只读搜索聚合：roster／overview／dorm／readiness 四类指标；"
            "只走只读派生区脱敏数字，不返回名单、学生明细与敏感字段。",
            "· 上下文不污染：聚合结果不写回任何一方空间的共享上下文，"
            "不带入他人 focus／意图／卡片／草稿；服务端在聚合前后对 shared_json 做完全相等校验。",
            "· 最近同类聚合留痕：%d 条（只记池 id／指标／成员数，不记业务原文）" % len(q),
            "· 请在「横向协同」视图选择指标并搜索；本秘书不把聚合结果写入当前空间。",
        ]
        return out("\n".join(lines), view="federation",
                   card={"type": "federation_view", "title": "同类横向协同 · 只读聚合",
                         "lines": lines, "pool_id": cp["pool_id"],
                         "member_count": cp["member_count"], "metrics": v["metrics"]},
                   audit=("federation.view", "ok", cp["pool_id"]))

    # 5d. 协同教育推送（PC017）：教师端 → 所代课程班级班主任端，非隶属管理
    if RE_COEDU.search(s):
        from tasks.modules.head_teacher import coedu as _co
        v, err = _co.view(ctx["session_id"])
        if err:
            return out("当前会话无法读取协同教育视图：" + err,
                       audit=("coedu.view", "denied", "session"))
        lines = [
            "【协同教育 · 非隶属管理、只协同育人】",
            "· 当前端：%s｜我的任课绑定 %d 条｜本班协同教育收件 %d 条" %
            (v["portal_name"] or v["portal"], v["link_count"], v["inbox_count"]),
            "· 可自动推送：exam（平时考试／学情批次）、status（学习状态）；"
            "服务端按教师 post_id → 所代课程班级 → 该班班主任端自动定向，前端不指定收件人。",
            "· 关系定性：教师与班主任不存在隶属管理，只存在协同教育学生关系；"
            "不进六级行政链、不参与逐级推送与催办、不纳入考核与留痕，也不属于同类池。",
            "· 内容边界：只推班级级脱敏派生区汇总＋需关注人数＋建议动作，不出名单、分数／排名、"
            "家长电话与对话原文；成绩域未接入前平时考试指标按红线降级为暂不可用，不编造数字。",
            "· 上下文不污染：只写独立收件箱与三元组审计，不写任何空间共享上下文；"
            "推送前后对 shared_json 做完全相等校验。请在「协同教育」视图预览并推送。",
        ]
        return out("\n".join(lines), view="coedu",
                   card={"type": "coedu_view", "title": "协同教育 · 教师端 → 班主任端",
                         "lines": lines, "link_count": v["link_count"],
                         "inbox_count": v["inbox_count"], "metrics": v["metrics"]},
                   audit=("coedu.view", "ok", ctx["post_id"]))

    # 6. 派生区越权 → 固定话术
    if RE_DERIVED.search(s):
        db.redline(ctx, "derived_zone")
        db.audit(ctx, "derived.forbidden", "denied", "answers/scores")
        return out(models.DERIVED_BOUNDARY_REPLY,
                   kind="forbidden", card={"type": "derived_boundary",
                                           "text": models.DERIVED_BOUNDARY_REPLY},
                   audit=("derived.forbidden", "denied", "answers/scores"))

    # 7. 工具就绪度 / 平台对接 / 部署基线
    if RE_READINESS.search(s):
        r = config.readiness()
        return out("【成长导航对接就绪度（%s）】\n"
                   "· 已跑通只读 MCP 工具 5 个：%s\n"
                   "· 当前画像仅：%s；未接：%s\n"
                   "· %s\n"
                   "· 权限：%s（校长角色单 token 须换按角色／班级过滤）\n"
                   "· 运行基线：%s\n"
                   "· 不直连智慧校园平台，只走成长导航数据服务；字段白名单：%s\n"
                   "· %s\n"
                   "· 上线前置：%d/9 已完成（%s）" %
                   (r["state"], "、".join(t["name"] for t in models.MCP_TOOLS),
                    "／".join(models.COVERAGE_READY), "／".join(models.COVERAGE_PENDING),
                    models.NO_FULL_PROFILE,
                    "按角色／班级过滤 token" if r["token_scope_ok"] else "单 token 校长角色（一票否决）",
                    config.CODE_BASELINE, "、".join(models.FIELD_WHITELIST),
                    models.DATA_READY_NOTE, r["done"], r["state"]),
                   card={"type": "degraded_notice", "text": models.RECONCILE_NOTE},
                   audit=("growth.readiness", "ok", "integration"))

    # 8. 班主任工作四项
    if RE_SCORES.search(s):
        r = growth.work_item(ctx, "scores")
        return out("【成绩／学情】" + r["reason"] + "。" + r["rule"] +
                   " 依据：14 数据域成绩域由教务系统按考试批次导入，不是成长导航画像维度分。",
                   card={"type": "growth_overview", "item": "成绩／学情", "available": False},
                   audit=("growth.work_item", "degraded", "scores"))
    if RE_TALENT.search(s):
        cid = (ctx.get("class_ids") or ["2611"])[0]
        g = growth.growth_profile(ctx, cid)
        if g.get("available") is False:   # 2607 派生区未绑定 → 降级，不拿示例值替代
            return out("【特长／兴趣 · 派生区结论】" + g["reason"] + "。" + g["rule"],
                       card={"type": "degraded_notice", "item": "特长／兴趣", "available": False},
                       audit=("growth.work_item", "degraded", "talent"))
        return out("【特长／兴趣 · 派生区结论】\n派生标签：%s\n赛道建议：%s\n%s" %
                   ("、".join(g["tags"]), "、".join(g["advice"]), g["note"]),
                   card={"type": "growth_overview", "item": "特长／兴趣", "available": True, "data": g},
                   audit=("growth.work_item", "ok", "talent"))
    if RE_PEER.search(s):
        cid = (ctx.get("class_ids") or ["2611"])[0]
        b = growth.balance_view(ctx, cid)
        if b.get("available") is False:
            return out("【四维平衡 · 本班派生统计】" + b["reason"] + "。" + b["rule"],
                       card={"type": "degraded_notice", "item": "交友／同伴", "available": False},
                       audit=("growth.work_item", "degraded", "balance"))
        return out("【四维平衡 · 本班派生统计（学习／交友／兴趣／健康）】\n%s\n%s" %
                   ("\n".join("  %s：%s（%s）" % (x["k"], x["v"], x["s"]) for x in b["balance"]),
                    b["note"]),
                   card={"type": "growth_overview", "item": "交友／同伴", "available": True, "data": b},
                   audit=("growth.work_item", "ok", "balance"))
    if RE_GOAL.search(s):
        cid = (ctx.get("class_ids") or ["2611"])[0]
        g = growth.goal_progress(ctx, cid)
        if g.get("available") is False:
            return out("【目标制定 · 班级派生进度】" + g["reason"] + "。" + g["rule"],
                       card={"type": "degraded_notice", "item": "目标制定", "available": False},
                       audit=("growth.work_item", "degraded", "goals"))
        return out("【目标制定 · 班级派生进度】\n六级目标：%s\n本周打卡：%s（待跟进 %s 人）\n隐形优势：%s\n%s" %
                   (g["六级目标"], g["本周打卡"], g["待跟进"], g["隐形优势"], g["note"]),
                   card={"type": "growth_overview", "item": "目标制定", "available": True, "data": g},
                   audit=("growth.work_item", "ok", "goals"))

    # 9. 周报 / 需关注
    if RE_REPORT.search(s):
        c = weekly_card(ctx)
        return out("已生成本级周报一页纸（草稿，未归档）。", card=c, kind="card",
                   audit=("report.generate", "ok", c["report_id"]))
    if RE_WATCH.search(s):
        c = watchlist_card(ctx)
        return out("本班需关注 %d 人（只含标记＋建议动作）。" % len(c["items"]), card=c, kind="card",
                   audit=("watchlist.get", "ok", "29"))

    # 9b. 本周待确认红点（D2 集中待办：转介／告知／销号）
    if RE_TODO.search(s):
        from tasks.modules.head_teacher import redpoint as _rp
        v = _rp.summary_for_chat(ctx)
        return out(v["text"], card=v["card"], kind="card", view="todo",
                   audit=("todo.view", "ok", "redpoint"))

    # 10. 催办 / 下发 / 推送流（引导到对应 API）
    if RE_DUN.search(s):
        return out("催办只到直接下级（逐级不越级），先回显、确认下达、限时反馈、超时自动升级提醒。"
                   "请在「六级推送流」视图选择下级并填写催办内容；团委线按团内程序单列，不进入行政催办链。",
                   view="flow", audit=("dun.guide", "ok", "flow"))
    if RE_DISPATCH.search(s) or RE_PUSH.search(s):
        return out("上行按频率自动生成、逐级自动推送，不设逐级人工放行卡点；"
                   "人审保留在写入类、对外发布、对外口径、处分与复学审批。"
                   "可在「六级推送流」查看 L1→L6 时刻表并手动触发一次推送。",
                   view="flow", audit=("push.guide", "ok", "flow"))

    # 11. 写入 → 两段式草稿（不落业务库）
    if RE_WRITE.search(s):
        from tasks.modules.head_teacher import writes
        pid = writes.draft(ctx, s)
        return out("已生成写入草稿，请确认后再落库。", card=echo_card(ctx, "moral_record", {"text": s}),
                   kind="card", pending_id=pid,
                   audit=("write.draft", "ok", pid))

    # 12. 批量 / 图形化操作保留界面
    if RE_BATCH.search(s):
        return out(models.REPLY["batch"], view="desk", audit=("batch.redirect", "ok", "desk"))

    # 13. 降级不估算
    if RE_DEGRADE.search(s):
        return out(models.REPLY["degrade"], card={"type": "degraded_notice", "text": models.REPLY["degrade"]},
                   kind="card", audit=("data.degrade", "ok", "reconcile"))

    # 14. 帮助与兜底
    if RE_HELP.search(s):
        return out("当前 <b>%s %s</b> 视角，可见范围：%s。\n本级主责：%s。\n"
                   "可说「生成本级报告」「本班需关注有谁」「记一笔德育」「切换职务」「工具就绪度」；"
                   "上级不直接改动下级明细；安全／舆情类事项一律人工电话或当面处置。" %
                   (ctx["level"], L["name"], L["scope"],
                    "周报一页纸、需关注清单、德育记录、工作四项派生区查询、家校沟通留痕"),
                   audit=("help", "ok", "session"))
    return out("已收到。当前为 %s %s 视角，可处理本级报告、需关注清单、写入回显、职务切换与推送流；"
               "换个说法或点下方指令试试。" % (ctx["level"], L["name"]),
               audit=("chat.fallback", "ok", "session"))
