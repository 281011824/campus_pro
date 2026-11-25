# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 组织架构与身份解析

权威源＝企业微信通讯录（人员／部门路径／主・兼任职务／有效期）。
三端（教师端／班主任端／行政端）是第一层导航，post_id 是第二层职务；
一个 userid 可跨端持有多个 post_id，每个 post_id 绑定唯一 agent_id（一岗一智能体）。
前端只提交 userid、目标 post_id 与可选的 portal（仅作筛选意图）；
portal / level / agent_id / data_scope 一律由服务端判定下发。
"""
import hashlib
from tasks.domain import models
from tasks.shared import (config, db)


# ---------------------------------------------------------------- 示例通讯录（mock 模式）
# 与《德育工作台_试点原型.html》ORG 完全一致，便于原型／部署包／后端三方对账。
MOCK_DIRECTORY = [
    ("zhangmin", "张敏", "政教处／高一年级组／2611班", "p_bzr", "班主任",
     "bzr_secretary_v1", "班主任秘书", True, False, ["2611"]),
    ("zhangmin", "张敏", "政教处／活动与考核岗（兼任）", "p_bzr_gs4", "政教干事（活动与考核）",
     "zj_ganshi_activity_v1", "政教干事·活动考核", False, False, ["2611"]),
    ("gs1", "王干事", "政教处／纪律督查岗", "p_gs1", "政教干事（纪律督查）",
     "zj_ganshi_discipline_v1", "政教干事·纪律督查", True, False, []),
    ("gs2", "李干事", "政教处／寝室管理岗", "p_gs2", "政教干事（寝室管理）",
     "zj_ganshi_dorm_v1", "政教干事·寝室管理", True, False, []),
    ("gs3", "陈干事", "政教处／家校与帮扶岗", "p_gs3", "政教干事（家校与帮扶）",
     "zj_ganshi_family_v1", "政教干事·家校帮扶", True, False, []),
    ("gs4", "赵干事", "政教处／活动与考核岗", "p_gs4", "政教干事（活动与考核）",
     "zj_ganshi_activity_v1", "政教干事·活动考核", True, False, []),
    ("fzrA", "刘副主任", "政教处／副主任（安全纪律）", "p_fzrA", "政教副主任A",
     "zj_fzr_security_v1", "政教副主任·安全纪律", True, False, []),
    ("fzrB", "周副主任", "政教处／副主任（德育体系）", "p_fzrB", "政教副主任B",
     "zj_fzr_moral_v1", "政教副主任·德育体系", True, False, []),
    ("tw1", "孙副书记", "团委／团务与志愿服务", "p_tw1", "团委副书记1",
     "tw_fshuji_affairs_v1", "团委副书记·团务志愿", True, True, []),
    ("tw2", "吴副书记", "团委／文化与宣传", "p_tw2", "团委副书记2",
     "tw_fshuji_culture_v1", "团委副书记·文化宣传", True, True, []),
    ("zhuren", "郑主任", "政教处／主任（兼团委书记）", "p_zr", "政教处主任（兼团委书记）",
     "zj_zhuren_v1", "政教主任参谋", True, False, []),
    ("zhuren", "郑主任", "团委／书记（团内程序）", "p_twsj", "团委书记（团内程序）",
     "tw_shuji_v1", "团委书记助理（团内线）", False, True, []),
    ("chenfu", "陈副校长", "校领导／德育分管线", "p_fgx", "分管德育副校长",
     "xld_fgx_v1", "分管副校长参谋", True, False, []),
    ("wangxiao", "王校长", "校领导", "p_xz", "校长",
     "xz_canmou_v1", "校长参谋", True, False, []),
]

# ---------------------------------------------------------------- 真实通讯录补录
# 来源：G:/deepseek/京山职校通讯录.xlsx（企业微信通讯录导出，2026-11-11）
# 方成 userid=coredump，职务列为空、部门三条；绑定表由政教处补录，level 以绑定表为准，
# auto_level 记录自动判定结果供核查（见 models.PENDING_CONFIRMATIONS PC001—PC004）。
# 徐海潮 userid=Tiao：2607 班成长导航系统试点班班主任，兼任团委副书记
#   （用户 2026-11-12 更正口径；11-11 曾按「团委书记」L4 试挂，已由 PC005 收敛）。
# 企微通讯录职务列为「团支部副书记」，与「团委副书记」同属副书记序列；
# 按方案六级链 L3＝政教副主任＝团委副书记，按团委线单列原则不进六级行政推送链。
# 一个 userid 两个 post_id、一岗一智能体，见 PC005—PC009。
REAL_DIRECTORY_EXTRA = [
    dict(
        user_id="coredump", name="方成",
        dept_path="京山职校/政教科/政教处", post_id="p_fc_fzr",
        post_name="政教处分管主任（补录·待确认）",
        agent_id="zj_fzr_incharge_v1", agent_name="政教副主任·分管（待确认）",
        level="L3", level_source="政教处补录（试挂 L3，见 PC001）",
        level_pending=1, in_chain=0, data_scope="indicator_pending_confirm",
        class_ids=[], primary_flag=1, committee_line=0, status="active",
    ),
    dict(
        user_id="coredump", name="方成",
        dept_path="京山职校/政教科/政教处/班主任", post_id="p_fc_bzr",
        post_name="班主任（兼任）",
        agent_id="bzr_secretary_v1", agent_name="班主任秘书",
        level="L1", level_source="通讯录部门路径",
        level_pending=0, in_chain=1, data_scope="class:待政教处补录",
        class_ids=[], primary_flag=0, committee_line=0, status="active",
    ),
    dict(
        user_id="coredump", name="方成",
        dept_path="京山职校/教务科/教务处/任课教师", post_id="p_fc_teacher",
        post_name="任课教师（兼任·教务线）",
        agent_id="js_teacher_v1", agent_name="任课教师·教学助手",
        level="L1", level_source="教务线（不进德育六级链，见 PC002）",
        level_pending=0, in_chain=0, data_scope="line:教务科任课教师",
        class_ids=[], primary_flag=0, committee_line=0, status="active",
    ),
    # ---- 徐海潮 Tiao：2607 试点班班主任（主职务）＋ 团委副书记（兼任，团线单列） ----
    dict(
        user_id="Tiao", name="徐海潮",
        dept_path="京山职校/政教科/政教处/班主任", post_id="p_xhc_bzr_2607",
        post_name="班主任（2607 成长导航试点班）",
        agent_id="bzr_secretary_v1", agent_name="班主任秘书",
        level="L1", level_source="用户口径＋控辍保学责任班（2607／2610）",
        level_pending=0, in_chain=1, data_scope="class:2607",
        class_ids=["2607"], primary_flag=1, committee_line=0, status="active",
    ),
    dict(
        user_id="Tiao", name="徐海潮",
        dept_path="京山职校/政教科/政教处/团委", post_id="p_xhc_tw",
        post_name="团委副书记（团内程序·兼任）",
        agent_id="tw_fshuji_v1", agent_name="团委副书记助理（团内线）",
        level="L3", level_source="用户 2026-11-12 更正口径「团委副书记」＝L3（政教副主任同级）；企微通讯录记「团支部副书记」，见 PC005",
        level_pending=0, in_chain=0,
        data_scope="committee_line_only（团务不进六级链、不纳入考核与留痕）",
        class_ids=[], primary_flag=0, committee_line=1, status="active",
    ),
    # ---- 徐海潮 Tiao 第三端：教师端（任课教师·教务线，用户 2026-11-12 口径） ----
    # 企微通讯录无「任课教师」部门，任课科目／班级待教务处补录，见 PC010。
    dict(
        user_id="Tiao", name="徐海潮",
        dept_path="京山职校/教务科/教务处/任课教师", post_id="p_xhc_teacher",
        post_name="任课教师（兼任·教务线）",
        agent_id="js_teacher_v1", agent_name="任课教师·教学助手",
        level="L1", level_source="用户 2026-11-12 三端口径补录（任课科目／班级待教务处确认，见 PC010）",
        level_pending=0, in_chain=0, data_scope="line:教务科任课教师",
        class_ids=[], primary_flag=0, committee_line=0, status="active",
        portal="teacher",
    ),
]

# ---------------------------------------------------------------- 纯教师演示账号（仅用于验证 1 张卡规则）
# 用户 2026-11-12 08:12 口径：「只是一个教师，他就会自行出现一个教师单」。
# 现有真实／示例通讯录中没有「只持有任课教师一个职务」的人员（徐海潮、方成均跨三端），
# 故补一个纯教师演示账号，用于验收「按职务自动判定 1／2／3 张卡片」。
# 该账号为演示数据，不是企业微信真实人员；正式上线以通讯录同步结果为准。
DEMO_TEACHER_ONLY = [
    dict(
        user_id="teacher1", name="何老师（演示·纯教师）",
        dept_path="京山职校/教务科/教务处/任课教师", post_id="p_teacher1",
        post_name="任课教师（语文）",
        agent_id="js_teacher_v1", agent_name="任课教师·教学助手",
        level="L1", level_source="演示账号·仅用于验证统一入口 1 张卡规则（非企微真实人员）",
        level_pending=0, in_chain=0,
        data_scope="line:教务科任课教师＋所任课程班级的派生学情（只读）",
        class_ids=[], primary_flag=1, committee_line=0, status="active",
        portal="teacher",
    ),
]


def resolve_level(dept_path, post_name):
    """服务端按部门路径＋岗位判定层级，前端不得传 level。"""
    text = (dept_path or "") + "／" + (post_name or "")
    for keys, level in models.POST_LEVEL_RULES:
        if any(k in text for k in keys):
            # 「政教处主任（兼团委书记）」须判为 L4，不被「团委书记」误判顺序影响
            return level
    return "L1"


def resolve_portal(dept_path, post_name):
    """服务端按部门路径＋岗位判定三端归属；前端传 portal 只作筛选意图，不提权。"""
    text = (dept_path or "") + "／" + (post_name or "")
    for keys, portal in models.PORTAL_RULES:
        if any(k in text for k in keys):
            return portal
    return models.PORTAL_DEFAULT


def data_scope_of(level, class_ids, post_name):
    if level == "L1":
        return "class:" + ",".join(class_ids or ["2611"])
    if level == "L2":
        return "line:" + (post_name or "本岗条线")
    if level == "L3":
        return "class_dimension_no_name"
    if level == "L4":
        return "grade_dimension"
    if level == "L5":
        return "indicator_only"
    return "school_stat_only"


def _agent_for(post_name, level):
    """post_id → agent_id 绑定表（政教处维护、信息化处校验）。"""
    return AGENT_BINDING.get(post_name) or AGENT_BINDING.get(level) or ("generic_agent_v1", "岗位智能体")


AGENT_BINDING = {
    "班主任": ("bzr_secretary_v1", "班主任秘书"),
    "政教干事（活动与考核）": ("zj_ganshi_activity_v1", "政教干事·活动考核"),
    "政教干事（纪律督查）": ("zj_ganshi_discipline_v1", "政教干事·纪律督查"),
    "政教干事（寝室管理）": ("zj_ganshi_dorm_v1", "政教干事·寝室管理"),
    "政教干事（家校与帮扶）": ("zj_ganshi_family_v1", "政教干事·家校帮扶"),
    "政教副主任A": ("zj_fzr_security_v1", "政教副主任·安全纪律"),
    "政教副主任B": ("zj_fzr_moral_v1", "政教副主任·德育体系"),
    "团委副书记1": ("tw_fshuji_affairs_v1", "团委副书记·团务志愿"),
    "团委副书记2": ("tw_fshuji_culture_v1", "团委副书记·文化宣传"),
    "团委副书记（团内程序·兼任）": ("tw_fshuji_v1", "团委副书记助理（团内线）"),
    "政教处主任（兼团委书记）": ("zj_zhuren_v1", "政教主任参谋"),
    "团委书记（团内程序）": ("tw_shuji_v1", "团委书记助理（团内线）"),
    "分管德育副校长": ("xld_fgx_v1", "分管副校长参谋"),
    "校长": ("xz_canmou_v1", "校长参谋"),
    "L1": ("bzr_secretary_v1", "班主任秘书"),
    "L2": ("zj_ganshi_generic_v1", "政教干事参谋"),
    "L3": ("zj_fzr_generic_v1", "政教副主任参谋"),
    "L4": ("zj_zhuren_v1", "政教主任参谋"),
    "L5": ("xld_fgx_v1", "分管副校长参谋"),
    "L6": ("xz_canmou_v1", "校长参谋"),
}


def _real_directory():
    """从企业微信通讯录拉取部门树＋成员，生成兼任职务清单。

    企微 user.position 中的多个职务以「／」分隔；每个部门＋职务生成一个 post_id。
    """
    from tasks.shared import wecom
    dept_map = wecom.department_map()
    rows = []
    for u in wecom.list_users():
        uid_ = u.get("userid", "")
        name = u.get("name", "")
        deps = u.get("department", []) or []
        dept_path = "／".join(dept_map.get(str(d), str(d)) for d in deps) or "未分配部门"
        posts = [p.strip() for p in (u.get("position") or "").split("／") if p.strip()]
        if not posts:
            posts = [dept_path.split("／")[-1] or "未标注岗位"]
        for i, post in enumerate(posts):
            level = resolve_level(dept_path, post)
            pid = hashlib.sha1(("%s|%s|%s|%d" % (uid_, dept_path, post, i)).encode()).hexdigest()[:12]
            pid = "p_" + pid
            agent_id, agent_name = _agent_for(post, level)
            rows.append(dict(
                user_id=uid_, name=name, dept_path=dept_path, post_id=pid, post_name=post,
                agent_id=agent_id, agent_name=agent_name, level=level,
                data_scope=data_scope_of(level, ["2611"], post),
                portal=resolve_portal(dept_path, post), class_ids=["2611"],
                primary_flag=1 if i == 0 else 0,
                committee_line=1 if ("团委" in dept_path) else 0,
                status="active" if u.get("status", 1) == 1 else "disabled",
            ))
    return rows


def sync_directory():
    """通讯录同步。mock＝内置示例＋真实通讯录补录；real＝企微 API。
    绑定表（政教处补录）优先于自动判层；岗位调整 T+1 生效、离岗即时回收。
    """
    if config.WECOM_MODE == "real":
        rows = _real_directory()
    else:
        rows = []
        for (u, n, dept, pid, post, aid, aname, primary, committee, classes) in MOCK_DIRECTORY:
            level = resolve_level(dept, post)
            rows.append(dict(
                user_id=u, name=n, dept_path=dept, post_id=pid, post_name=post,
                agent_id=aid, agent_name=aname, level=level,
                data_scope=data_scope_of(level, classes, post),
                portal=resolve_portal(dept, post), class_ids=classes,
                primary_flag=1 if primary else 0, committee_line=1 if committee else 0,
                status="active",
            ))
        rows.extend(dict(x) for x in REAL_DIRECTORY_EXTRA)
        rows.extend(dict(x) for x in DEMO_TEACHER_ONLY)

    # 自动判层结果留作对照（绑定表 level 优先）；补齐新增字段默认值
    for r in rows:
        r.setdefault("class_ids", [])
        r.setdefault("data_scope", data_scope_of(r["level"], r["class_ids"], r["post_name"]))
        r.setdefault("level_source", "通讯录部门路径自动判定")
        r.setdefault("level_pending", 0)
        r.setdefault("in_chain", 1)
        r.setdefault("portal", resolve_portal(r["dept_path"], r["post_name"]))
        # 教师端（任课教学）不属于德育六级行政链：不生成上行报告、不作为催办对象
        if r["portal"] == "teacher":
            r["in_chain"] = 0
        r["auto_level"] = resolve_level(r["dept_path"], r["post_name"])

    ts = db.now()
    for r in rows:
        db.exec_(
            "INSERT INTO org_posts(user_id,name,dept_path,post_id,post_name,agent_id,agent_name,"
            "level,data_scope,portal,class_ids,primary_flag,committee_line,level_source,level_pending,"
            "in_chain,auto_level,status,valid_from,synced_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET name=excluded.name,dept_path=excluded.dept_path,"
            "post_name=excluded.post_name,agent_id=excluded.agent_id,agent_name=excluded.agent_name,"
            "level=excluded.level,data_scope=excluded.data_scope,portal=excluded.portal,"
            "class_ids=excluded.class_ids,"
            "primary_flag=excluded.primary_flag,committee_line=excluded.committee_line,"
            "level_source=excluded.level_source,level_pending=excluded.level_pending,"
            "in_chain=excluded.in_chain,auto_level=excluded.auto_level,"
            "status=excluded.status,synced_at=excluded.synced_at",
            (r["user_id"], r["name"], r["dept_path"], r["post_id"], r["post_name"],
             r["agent_id"], r["agent_name"], r["level"], r["data_scope"], r["portal"],
             db.dumps(r["class_ids"]), r["primary_flag"], r["committee_line"],
             r["level_source"], r["level_pending"], r["in_chain"], r["auto_level"],
             r["status"], ts, ts),
        )
        # 同岗位跨人复用同一 agent_id（既有约定）：台账按 agent_id 登记，职务实例由 org_posts 承载
        db.exec_(
            "INSERT INTO agent_registry(agent_id,post_id,level,agent_name,prompt_file,status) "
            "VALUES(?,?,?,?,?,'shadow') ON CONFLICT(agent_id) DO NOTHING",
            (r["agent_id"], r["post_id"], r["level"], r["agent_name"],
             "../02_系统提示词.md#%s" % r["agent_id"]),
        )
    # 离岗即时回收：本次同步未出现的 post_id 置为 disabled
    keep = {r["post_id"] for r in rows}
    for row in db.q("SELECT post_id FROM org_posts WHERE status='active'"):
        if row["post_id"] not in keep:
            db.exec_("UPDATE org_posts SET status='disabled' WHERE post_id=?", (row["post_id"],))
    db.audit({"user_id": "system"}, "org.sync", "ok", "directory",
             "mode=%s posts=%d pending=%d" % (config.WECOM_MODE, len(rows),
                                              len(models.PENDING_CONFIRMATIONS)))
    return {"mode": config.WECOM_MODE, "posts": len(rows),
            "pending_confirmations": len(models.PENDING_CONFIRMATIONS), "synced_at": ts}


def portal_cards(user_id):
    """统一入口卡片：只返回该账号「有职务」的端，按固定顺序排列。

    一个入口、卡片式单口选择（用户 2026-11-12 08:12 口径）：
    只是教师→1 张；教师＋班主任→2 张；教师＋班主任＋行政→3 张。
    无职务的端不返回、不渲染、不可进入；此处不装载任何智能体。
    """
    groups = {g["portal"]: g for g in portals_of(user_id)}
    posts = posts_of(user_id)
    person = next((p for p in persons() if p["user_id"] == user_id), None)
    cards = []
    for pid in models.PORTAL_ORDER:
        g = groups.get(pid)
        if not g or not g["has"]:
            continue
        meta = models.PORTAL_INDEX[pid]
        mine = g["posts"]
        primary = next((x for x in mine if x["primary_flag"]),
                       next((x for x in mine if x["in_chain"]), mine[0]))
        cards.append({
            "portal": pid, "name": meta["name"], "sub": meta["sub"],
            "manages": meta["manages"], "one_liner": meta["one_liner"],
            "focus": meta["focus"], "desk": meta["desk"], "chain": meta["chain"],
            "post_count": g["count"],
            "primary_post": {
                "post_id": primary["post_id"], "post_name": primary["post_name"],
                "agent_id": primary["agent_id"], "level": primary["level"],
                "in_chain": primary["in_chain"], "committee_line": primary["committee_line"],
            },
            "posts": mine,
        })
    return {
        "user_id": user_id, "name": (person or {}).get("name", ""),
        "total_posts": len(posts), "cards": cards, "card_count": len(cards),
        "rule": models.PORTAL_ENTRY_RULE, "card_note": models.PORTAL_CARD_NOTE,
        "manages_note": models.PORTAL_MANAGES_NOTE, "note": models.PORTAL_NOTE,
    }


def enter_portal(userid, portal):
    """统一入口：选中卡片后才装载该端主职务智能体；端由服务端校验，前端不提权。"""
    cards = portal_cards(userid)
    if not any(c["portal"] == portal for c in cards["cards"]):
        db.audit({"user_id": userid}, "portal.enter", "denied", portal,
                 "该账号在指定端无有效职务，未装载任何智能体")
        pname = models.PORTAL_INDEX.get(portal, {}).get("name", portal)
        return None, "「%s」不在您的可选入口中（企业微信通讯录无该端职务），已拒绝并记审计" % pname
    ctx, err = switch(userid, portal=portal)
    if err:
        return None, err
    db.audit(ctx, "portal.enter", "ok", portal,
             "统一入口选中 %s，装载 %s／%s" % (ctx["portal_name"], ctx["post_id"], ctx["agent_id"]))
    return ctx, None


def auto_match(user_id):
    """企微角色自动匹配加载（PC014）：一次解析全部职务、自动装载主职务，无需手动选端。

    角色来源只有企业微信通讯录同步后的 org_posts；一人多角色时全部自动匹配，
    但同一时刻只装载一个会话上下文，其余角色仅作就绪登记（不产生会话、不共享上下文）。
    """
    rows = posts_of(user_id)
    if not rows:
        db.audit({"user_id": user_id}, "portal.auto", "denied", user_id,
                 "企业微信通讯录无有效职务，未自动匹配加载任何智能体")
        return None, "企业微信通讯录中该账号无有效职务，无法自动匹配加载"

    # 主职务：primary_flag → in_chain → PORTAL_ORDER 顺序，全部由服务端判定
    primary = next((r for r in rows if r["primary_flag"]), None)
    if primary is None:
        primary = next((r for r in rows if r["in_chain"]), None)
    if primary is None:
        primary = sorted(rows, key=lambda r: models.PORTAL_ORDER.index(r["portal"]))[0]

    ctx, err = resolve(user_id, post_id=primary["post_id"])
    if err:
        return None, err

    roles = []
    for r in rows:
        meta = models.PORTAL_INDEX.get(r["portal"], {})
        roles.append({
            "post_id": r["post_id"], "post_name": r["post_name"],
            "agent_id": r["agent_id"], "agent_name": r["agent_name"],
            "portal": r["portal"], "portal_name": meta.get("name", r["portal"]),
            "level": r["level"], "data_scope": r["data_scope"],
            "in_chain": r["in_chain"], "committee_line": r["committee_line"],
            "level_pending": r["level_pending"], "primary_flag": r["primary_flag"],
            "is_current": r["post_id"] == primary["post_id"],
            "manages": meta.get("manages", ""), "one_liner": meta.get("one_liner", ""),
            "status": "已自动装载" if r["post_id"] == primary["post_id"]
                      else "自动匹配就绪（未装载）",
        })
    db.audit(ctx, "portal.auto", "ok", user_id,
             "企微通讯录自动匹配 %d 个角色，自动装载主职务 %s／%s"
             % (len(roles), primary["post_id"], primary["agent_id"]))
    # PC015：主职务空间随角色共建并激活，其余角色仅就绪登记（不共建、不共享上下文）
    sv, serr = None, None
    try:
        from tasks.domain.collaboration import space
        sv, serr = space.view(ctx["session_id"])
    except Exception as e:                                    # 空间不可用时不影响自动匹配
        serr = str(e)
    return {
        "user_id": user_id, "name": ctx.get("name", ""),
        "ctx": ctx, "roles": roles, "role_count": len(roles),
        "portals": portals_of(user_id),
        "space": sv, "space_error": serr,
        "space_rule": models.SPACE_RULE, "space_note": models.SPACE_NOTE,
        "space_isolation": models.SPACE_ISOLATION,
        "auto_rule": models.PORTAL_AUTO_RULE, "auto_note": models.PORTAL_AUTO_NOTE,
        "manages_note": models.PORTAL_MANAGES_NOTE, "note": models.PORTAL_NOTE,
        "entry_rule": models.PORTAL_ENTRY_RULE, "card_note": models.PORTAL_CARD_NOTE,
    }, None


def conflicts():
    """真实通讯录接入的待确认口径（确认前不作正式层级依据）。"""
    posts = db.q(
        "SELECT post_id,post_name,user_id,name,level,auto_level,level_source,level_pending,"
        "in_chain,data_scope,portal FROM org_posts WHERE status='active' "
        "AND (level_pending=1 OR in_chain=0) ORDER BY user_id,post_id")
    return {"items": models.PENDING_CONFIRMATIONS, "posts": posts,
            "rule": "待确认项在政教处／信息化处确认前不得作为正式层级依据；"
                    "level_pending=1 或 in_chain=0 的职务不参与六级自动推送与催办的层级判定"}


def directory():
    return db.q("SELECT * FROM org_posts WHERE status='active' ORDER BY level, user_id, primary_flag DESC")


def persons():
    rows = directory()
    seen, out = set(), []
    for r in rows:
        if r["user_id"] not in seen:
            seen.add(r["user_id"])
            mine = [x for x in rows if x["user_id"] == r["user_id"]]
            plist = sorted({x["portal"] for x in mine},
                           key=lambda p: models.PORTAL_ORDER.index(p))
            out.append({"user_id": r["user_id"], "name": r["name"],
                        "posts": len(mine), "portals": plist,
                        "portal_count": len(plist)})
    return out


def portals_of(user_id):
    """某 userid 的三端职务分组（端是第一层导航、post_id 是第二层职务）。"""
    rows = posts_of(user_id)
    out = []
    for pid in models.PORTAL_ORDER:
        p = models.PORTAL_INDEX[pid]
        mine = [r for r in rows if r["portal"] == pid]
        out.append({
            "portal": pid, "name": p["name"], "sub": p["sub"],
            "focus": p["focus"], "desk": p["desk"], "chain": p["chain"],
            "rule": p["rule"], "count": len(mine), "has": bool(mine),
            "posts": [{"post_id": x["post_id"], "post_name": x["post_name"],
                       "agent_id": x["agent_id"], "level": x["level"],
                       "data_scope": x["data_scope"], "in_chain": x["in_chain"],
                       "committee_line": x["committee_line"],
                       "primary_flag": x["primary_flag"]} for x in mine],
        })
    return out


def portal_summary(user_id=None):
    """三端总览：某人或全员跨端分布；不含任何学生数据。"""
    if user_id:
        pl = portals_of(user_id)
        return {"user_id": user_id, "portals": pl,
                "portal_count": len([p for p in pl if p["has"]]),
                "rule": models.PORTAL_ISOLATION, "note": models.PORTAL_NOTE,
                "entry_rule": models.PORTAL_ENTRY_RULE,
                "card_note": models.PORTAL_CARD_NOTE,
                "manages_note": models.PORTAL_MANAGES_NOTE,
                "auto_rule": models.PORTAL_AUTO_RULE,
                "auto_note": models.PORTAL_AUTO_NOTE,
                "space_rule": models.SPACE_RULE,
                "space_note": models.SPACE_NOTE,
                "space_isolation": models.SPACE_ISOLATION}
    rows = directory()
    people = {}
    for r in rows:
        v = people.setdefault(r["user_id"], {
            "user_id": r["user_id"], "name": r["name"], "portals": set(), "posts": 0})
        v["portals"].add(r["portal"])
        v["posts"] += 1
    out = [{"user_id": v["user_id"], "name": v["name"],
            "portals": [p for p in models.PORTAL_ORDER if p in v["portals"]],
            "portal_count": len(v["portals"]), "posts": v["posts"]}
           for v in people.values()]
    out.sort(key=lambda x: (-x["portal_count"], x["user_id"]))
    return {"portals": models.PORTALS, "people": out,
            "cross_portal_people": [x for x in out if x["portal_count"] > 1],
            "rule": models.PORTAL_ISOLATION, "note": models.PORTAL_NOTE,
            "entry_rule": models.PORTAL_ENTRY_RULE,
            "card_note": models.PORTAL_CARD_NOTE,
            "manages_note": models.PORTAL_MANAGES_NOTE,
            "auto_rule": models.PORTAL_AUTO_RULE,
            "auto_note": models.PORTAL_AUTO_NOTE,
            "space_rule": models.SPACE_RULE,
            "space_note": models.SPACE_NOTE,
            "space_isolation": models.SPACE_ISOLATION}


def posts_of(user_id):
    rows = db.q("SELECT * FROM org_posts WHERE user_id=? AND status='active' "
                "ORDER BY primary_flag DESC, post_id", (user_id,))
    # 全校账号映射（account_bindings）与通讯录并行生效，不受同步回收影响
    try:
        from tasks.domain.identity import bindings
        rows = list(rows) + bindings.posts_of(user_id)
    except Exception:
        pass
    rows.sort(key=lambda r: (-int(r.get("primary_flag") or 0), r.get("post_id") or ""))
    return rows


def assert_clean(payload):
    """前端伪造 level / agent_id / data_scope 一律拒绝并记审计（防越权）。"""
    bad = [k for k in models.FRONTEND_FORBIDDEN_FIELDS if k in (payload or {})]
    if bad:
        db.audit({"user_id": (payload or {}).get("userid")}, "identity.forge_reject",
                 "denied", "frontend_payload", "forbidden_fields=" + ",".join(bad))
        return bad
    return []


def _bound_classes(user_id):
    """班主任绑定班级（account_bindings.portal='headteacher'）。

    通讯录同步出的 org_posts.class_ids 可能为空，班主任的真实班级以绑定表为准。
    """
    try:
        row = db.q("SELECT class_ids FROM account_bindings WHERE userid=? AND portal='headteacher'",
                   (str(user_id or ""),), one=True)
        return db.loads((row or {}).get("class_ids"), [])
    except Exception:
        return []


def _make_ctx(row):
    sid = db.uid("s_")
    portal = row.get("portal") or models.PORTAL_DEFAULT
    pinfo = models.PORTAL_INDEX.get(portal, {})
    ctx = dict(
        session_id=sid, user_id=row["user_id"], name=row["name"],
        post_id=row["post_id"], post_name=row["post_name"], dept_path=row["dept_path"],
        agent_id=row["agent_id"], agent_name=row["agent_name"], level=row["level"],
        portal=portal, portal_name=pinfo.get("name", portal),
        data_scope=row["data_scope"], class_ids=db.loads(row["class_ids"], []),
        committee_line=bool(row["committee_line"]),
        level_source=row.get("level_source", "通讯录部门路径自动判定"),
        level_pending=bool(row.get("level_pending", 0)),
        in_chain=bool(row.get("in_chain", 1)),
        auto_level=row.get("auto_level", ""),
    )
    # 通讯录未带班级时，以班主任绑定表补齐；任课教师端同样按此口径解析，
    # 避免周报等班级数据回落到默认班（2611）而串班。
    if not ctx["class_ids"]:
        bound = _bound_classes(ctx["user_id"])
        if bound:
            ctx["class_ids"] = bound
            ctx["data_scope"] = "class:" + ",".join(bound)
    db.exec_(
        "INSERT INTO sessions(session_id,user_id,post_id,agent_id,level,data_scope,portal,class_ids,"
        "committee_line,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'active',?)",
        (sid, ctx["user_id"], ctx["post_id"], ctx["agent_id"], ctx["level"],
         ctx["data_scope"], ctx["portal"], db.dumps(ctx["class_ids"]),
         int(ctx["committee_line"]), db.now()),
    )
    db.audit(ctx, "session.resolve", "ok", row["post_id"],
             "装载 %s（%s）" % (row["agent_id"], row["agent_name"]))
    # PC015：随角色共建空间（延迟导入避免 space↔org 循环依赖）
    from tasks.domain.collaboration import space
    ctx["space_id"] = space.ensure_space(ctx)
    return ctx


def resolve(userid, post_id=None, portal=None):
    """登录态解析：可按端筛选；不传 post_id 时取该端（或全量）的主职务。
    portal 只作筛选意图，不能提权：目标职务必须仍在该 userid 的合法职务列表内。"""
    posts = posts_of(userid)
    if not posts:
        db.audit({"user_id": userid}, "session.resolve", "denied", "userid", "通讯录无有效职务")
        return None, "企业微信通讯录中无该 userid 的有效职务，已拒绝并记审计日志"
    if portal:
        cand = [p for p in posts if p["portal"] == portal]
        if not cand:
            db.audit({"user_id": userid}, "portal.resolve", "denied", portal,
                     "该账号在指定端无有效职务，已拒绝跨端装载")
            pname = models.PORTAL_INDEX.get(portal, {}).get("name", portal)
            return None, "该账号在「%s」无有效职务，已拒绝并记审计日志，未装载任何智能体" % pname
        posts = cand
    if post_id:
        row = next((p for p in posts if p["post_id"] == post_id), None)
        if not row:
            db.audit({"user_id": userid}, "post.switch", "denied", post_id,
                     "目标 post_id 不属于该 userid 的合法职务列表（或不属于指定端）")
            return None, "该职务不属于当前企业微信账号的合法职务列表，已拒绝并记审计日志，未装载任何智能体"
    else:
        row = next((p for p in posts if p["primary_flag"]), posts[0])
    return _make_ctx(row), None


def switch(userid, post_id=None, portal=None):
    """切换职务／切换端：作废旧会话 → 清空上下文／pending／催办草稿 → 装载新智能体。
    不传 post_id 时按 portal 取该端主职务；跨端切换同样清空，三端数据互不打通。"""
    old = db.q("SELECT session_id FROM sessions WHERE user_id=? AND status='active'", (userid,))
    for s in old:
        db.clear_session_state(s["session_id"])
    ctx, err = resolve(userid, post_id, portal)
    if err:
        return None, err
    db.audit(ctx, "post.switch", "ok", post_id or ctx["portal"],
             "切换至 %s／%s；上一职务（端）上下文／pending／dunDraft 已清空"
             % (ctx["portal_name"], ctx["post_id"]))
    return ctx, None


def get_session(session_id):
    r = db.q("SELECT * FROM sessions WHERE session_id=? AND status='active'", (session_id,), one=True)
    if not r:
        return None
    portal = r["portal"] or models.PORTAL_DEFAULT
    return dict(session_id=r["session_id"], user_id=r["user_id"], post_id=r["post_id"],
                agent_id=r["agent_id"], level=r["level"], data_scope=r["data_scope"],
                portal=portal, portal_name=models.PORTAL_INDEX.get(portal, {}).get("name", portal),
                class_ids=db.loads(r["class_ids"], []), committee_line=bool(r["committee_line"]))


def public_ctx(ctx):
    """下发给前端的会话上下文（层级／智能体由服务端判定，前端不可传）。"""
    keys = ("session_id", "user_id", "name", "post_id", "post_name", "dept_path",
            "agent_id", "agent_name", "level", "data_scope", "class_ids", "committee_line",
            "portal", "portal_name", "space_id")
    out = {k: ctx[k] for k in keys if k in ctx}
    out["portal_name"] = ctx.get("portal_name") or models.PORTAL_INDEX.get(
        out.get("portal"), {}).get("name", out.get("portal", ""))
    out.update({
        "level_source": ctx.get("level_source", "通讯录部门路径自动判定"),
        "level_pending": bool(ctx.get("level_pending", 0)),
        "in_chain": bool(ctx.get("in_chain", 1)),
        "auto_level": ctx.get("auto_level", ""),
    })
    return out
