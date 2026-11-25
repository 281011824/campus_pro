# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 共建空间（PC015 / v0.14）

用户 2026-11-12 12:24 口径：秘书智能体随着角色不同，跟随工作台一起共建空间、共享上下文。

设计边界（与既有红线兼容，见 models.SPACE_ISOLATION）：
  * 一个「角色装载」＝一个空间：space_id 由服务端按 userid＋post_id＋agent_id＋session_id
    确定性生成并绑定会话；前端只传 session_id，不得指定 space_id 或跨空间读写。
  * 空间成员＝该角色的秘书智能体（agent_id）＋该角色的工作台（模块／视图）。
    两者共同读写同一份 shared_json（共享上下文）。
  * 共享上下文只收 models.SPACE_SHARED_FIELDS 白名单的结构化脱敏键，
    身份／权限字段、自由文本、字段黑名单一律拒绝。
  * 空间之间隔离：切换职务时 db.clear_session_state() 归档旧空间并清空 shared_json，
    新空间由 org._make_ctx() 重建，不继承任何旧上下文。
  * 自动匹配加载只共建并激活主职务空间；其余角色仅作「就绪登记（未共建）」。
  * 读写均按 userid＋post_id＋agent_id＋space_id 四元组留痕，不记对话原文。
"""
import hashlib
import re

from tasks.domain import models
from tasks.domain.identity import org
from tasks.shared import db

SOURCES = ("secretary", "workbench")          # 共建双方
_MAX_STR = 60
_RE_BAD_TEXT = re.compile(
    r"家长电话|联系方式|家庭住址|身份证|学籍号|心理量表|测评结果|请假事由|"
    r"\d{11}|[\r\n]", re.S)


def space_id_for(ctx):
    """服务端确定性生成：同一角色不同会话也是不同空间（切换即重建，不继承）。"""
    raw = "%s|%s|%s|%s" % (ctx["user_id"], ctx["post_id"], ctx["agent_id"], ctx["session_id"])
    return "sp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def ensure_space(ctx):
    """装载职务智能体时由 org._make_ctx 调用：共建并激活该角色空间。

    同一 userid 同时只激活一个空间（对齐 PC014「同一时刻只装载一个会话上下文」）：
    再次自动匹配或切换时，先归档该账号其余 active 空间并清空其共享上下文。
    """
    sid = space_id_for(ctx)
    db.exec_(
        "UPDATE spaces SET status='archived', archived_at=?, shared_json='{}' "
        "WHERE user_id=? AND status='active' AND space_id<>?",
        (db.now(), ctx["user_id"], sid),
    )
    db.exec_(
        "INSERT OR REPLACE INTO spaces(space_id,session_id,user_id,post_id,agent_id,"
        "portal,level,shared_json,status,created_at) VALUES(?,?,?,?,?,?,?,'{}','active',?)",
        (sid, ctx["session_id"], ctx["user_id"], ctx["post_id"], ctx["agent_id"],
         ctx.get("portal", models.PORTAL_DEFAULT), ctx.get("level", "L1"), db.now()),
    )
    db.audit(ctx, "space.build", "ok", sid,
             "随角色共建空间：%s／%s（秘书智能体＋工作台）"
             % (ctx.get("post_name", ctx["post_id"]), ctx["agent_id"]))
    return sid


def active_for_session(session_id):
    return db.q("SELECT * FROM spaces WHERE session_id=? AND status='active'",
                (session_id,), one=True)


def _validate(patch):
    """白名单校验：返回 (accepted, rejected)。只收结构化脱敏键，不收自由文本。"""
    accepted, rejected = {}, []
    for k, v in (patch or {}).items():
        if k not in models.SPACE_SHARED_FIELDS or k in models.SPACE_FORBIDDEN_FIELDS:
            rejected.append(k)
            continue
        if isinstance(v, bool) or v is None or isinstance(v, int):
            accepted[k] = v
            continue
        if isinstance(v, str):
            if len(v) > _MAX_STR or _RE_BAD_TEXT.search(v):
                rejected.append(k)
                continue
            accepted[k] = v
            continue
        if isinstance(v, dict) and k == "module_hits":
            clean = {str(kk)[:24]: vv for kk, vv in v.items()
                     if isinstance(vv, int) and not isinstance(vv, bool)}
            accepted[k] = clean
            continue
        rejected.append(k)
    return accepted, rejected


def write_shared(session_id, source, patch):
    """共建写入：秘书对话或工作台模块更新共享上下文。返回 (shared, err)。"""
    row = active_for_session(session_id)
    if not row:
        return None, "当前会话没有激活的共建空间，请重新按企业微信职务装载"
    if source not in SOURCES:
        return None, "共建来源只能是秘书智能体或工作台"
    accepted, rejected = _validate(patch)
    if not accepted and patch:
        ctx = {"user_id": row["user_id"], "post_id": row["post_id"],
               "agent_id": row["agent_id"], "level": row["level"]}
        db.audit(ctx, "space.write", "denied", row["space_id"],
                 "共享上下文拒绝非白名单字段：" + ",".join(rejected[:8]))
        return None, "共享上下文只收白名单结构化脱敏键，已拒绝：" + ",".join(rejected[:8])
    shared = db.loads(row["shared_json"], {})
    if "module_hits" in accepted and isinstance(shared.get("module_hits"), dict):
        merged = dict(shared["module_hits"])
        merged.update(accepted.pop("module_hits"))
        shared["module_hits"] = merged
    shared.update(accepted)
    shared["updated_by"] = source
    db.exec_("UPDATE spaces SET shared_json=? WHERE space_id=? AND status='active'",
             (db.dumps(shared), row["space_id"]))
    db.exec_(
        "INSERT INTO space_events(ts,space_id,user_id,post_id,agent_id,source,fields,result) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (db.now(), row["space_id"], row["user_id"], row["post_id"], row["agent_id"],
         source, ",".join(sorted(accepted.keys())),
         "ok" if not rejected else "partial(拒绝 %s)" % ",".join(rejected[:5])),
    )
    return shared, None


def focus(session_id, module, class_id=None, masked=None):
    """工作台侧写 focus：切模块／选班级／选中学生掩码。"""
    patch = {"focus_module": str(module)[:_MAX_STR], "updated_by": "workbench"}
    if class_id:
        patch["focus_class"] = str(class_id)[:_MAX_STR]
    if masked:
        patch["focus_masked"] = str(masked)[:_MAX_STR]
    hits = active_for_session(session_id)
    cur = db.loads(hits["shared_json"], {}).get("module_hits", {}) if hits else {}
    cur[str(module)[:24]] = int(cur.get(str(module)[:24], 0)) + 1
    patch["module_hits"] = cur
    return write_shared(session_id, "workbench", patch)


def record_secretary(session_id, ctx, res):
    """秘书侧写共享上下文：意图标签、卡片类型、写入草稿 id、对话轮次。

    只写结构化标签，绝不写回复原文／对话文本（零留痕红线不变）。
    """
    row = active_for_session(session_id)
    if not row:
        return None
    shared = db.loads(row["shared_json"], {})
    patch = {
        "last_intent": str(res.get("kind") or "text")[:_MAX_STR],
        "last_card": str((res.get("card") or {}).get("type") or "none")[:_MAX_STR],
        "turn_count": int(shared.get("turn_count", 0)) + 1,
        "updated_by": "secretary",
    }
    if res.get("pending_id"):
        patch["pending_write_id"] = str(res["pending_id"])[:_MAX_STR]
    if res.get("view"):
        patch["focus_module"] = str(res["view"])[:_MAX_STR]
    return write_shared(session_id, "secretary", patch)[0]


def view(session_id):
    """前端「共建空间」视图：成员、共享上下文、共建留痕、隔离口径。"""
    row = active_for_session(session_id)
    if not row:
        return None, "当前会话没有激活的共建空间"
    ctx = org.get_session(session_id) or {}
    post = db.q("SELECT post_name,agent_name FROM org_posts WHERE post_id=?",
                (row["post_id"],), one=True) or {}
    shared = db.loads(row["shared_json"], {})
    pinfo = models.PORTAL_INDEX.get(row["portal"], {})
    events = db.q("SELECT ts,source,fields,result FROM space_events WHERE space_id=? "
                  "ORDER BY id DESC LIMIT 30", (row["space_id"],))
    post_name = post.get("post_name", row["post_id"])
    agent_name = post.get("agent_name", row["agent_id"])
    return {
        "space_id": row["space_id"], "session_id": session_id,
        "user_id": row["user_id"], "post_id": row["post_id"],
        "post_name": post_name, "agent_id": row["agent_id"], "agent_name": agent_name,
        "level": row["level"],
        "portal": row["portal"], "portal_name": pinfo.get("name", row["portal"]),
        "status": row["status"], "created_at": row["created_at"],
        "members": [
            {"role": "秘书智能体", "id": row["agent_id"], "name": agent_name,
             "duty": "随角色不同：本职务的智能体，读写空间共享上下文、生成卡片与草稿"},
            {"role": "工作台", "id": "%s-workbench" % row["portal"],
             "name": pinfo.get("name", row["portal"]) + " · 德育工作台",
             "duty": "本端 %d 个模块／视图，读写同一份共享上下文，随角色呈现"
                     % len(pinfo.get("desk", []))},
        ],
        "workbench_modules": pinfo.get("desk", []),
        "shared": shared,
        "shared_fields": list(models.SPACE_SHARED_FIELDS),
        "events": events, "event_count": len(events),
        "rule": models.SPACE_RULE, "note": models.SPACE_NOTE,
        "isolation": models.SPACE_ISOLATION,
        "sources": list(SOURCES),
    }, None


def spaces_of(user_id):
    """我的空间：当前激活的主职务空间 ＋ 其余角色的就绪登记（未共建）。"""
    active = db.q("SELECT * FROM spaces WHERE user_id=? AND status='active' "
                  "ORDER BY created_at DESC", (user_id,))
    posts = {p["post_id"]: p for p in org.posts_of(user_id)}
    cur_post = active[0]["post_id"] if active else ""
    out = []
    for r in active:
        pinfo = models.PORTAL_INDEX.get(r["portal"], {})
        out.append({
            "space_id": r["space_id"], "post_id": r["post_id"],
            "post_name": posts.get(r["post_id"], {}).get("post_name", r["post_id"]),
            "agent_id": r["agent_id"], "portal": r["portal"],
            "portal_name": pinfo.get("name", r["portal"]),
            "level": r["level"], "status": "已共建并激活（当前空间）",
            "shared_keys": sorted(db.loads(r["shared_json"], {}).keys()),
            "is_current": r["post_id"] == cur_post,
        })
    have = {x["post_id"] for x in out}
    for p in posts.values():
        if p["post_id"] in have:
            continue
        pinfo = models.PORTAL_INDEX.get(p["portal"], {})
        out.append({
            "space_id": "", "post_id": p["post_id"], "post_name": p["post_name"],
            "agent_id": p["agent_id"], "portal": p["portal"],
            "portal_name": pinfo.get("name", p["portal"]), "level": p["level"],
            "status": "自动匹配就绪（未共建、不装载、不共享上下文）",
            "shared_keys": [], "is_current": False,
        })
    return {
        "user_id": user_id, "spaces": out, "space_count": len(out),
        "active_count": len([x for x in out if x["is_current"]]),
        "rule": models.SPACE_RULE, "note": models.SPACE_NOTE,
        "isolation": models.SPACE_ISOLATION,
    }
