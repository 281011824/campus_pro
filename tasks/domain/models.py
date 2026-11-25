# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 方案口径常量（对齐部署包 v0.10 / 原型 v0.10）

一切组织层级、频率、红线、字段口径均以本文件为单一来源；服务端判定，前端只传
userid 与目标 post_id，禁止传 level / agent_id / data_scope / curLevel。
"""

# ---------------------------------------------------------------- 三端划分（工作台／界面与数据边界维度）
# 用户 2026-11-12 口径：按「教师端／班主任端／行政端」三个端来分，一人可跨三端，
# 例如徐海潮（Tiao）既是任课教师、又是 2607 班主任、又是行政端的团委副书记。
# 三端是上层导航，post_id 是下层职务；每个 post_id 仍绑定唯一 agent_id（一岗一智能体）。
PORTALS = [
    {
        "id": "teacher", "name": "教师端", "sub": "日常学习",
        "who": "任课教师（含兼任班主任／行政职务的教师）",
        "manages": "学生 · 所任课程的日常学习",
        "one_liner": "教学生日常学习：课堂、作业、学情与成绩参考",
        "focus": "所任课程的日常教学、学情、作业与课堂；不承接班级综合管理与行政履职管理",
        "desk": ["所任课程", "日常学情", "作业与测评", "教学待办"],
        "data_scope": "line:教务科任课教师＋所任课程班级的派生学情；不含德育处分、归寝处置、家长电话与心理明细",
        "tools": ["get_class_summary"],
        "chain": "不进德育六级行政链（in_chain=0）：不生成上行报告、不作为催办对象、不纳入德育考核",
        "agent": "js_teacher_v1（任课教师·教学助手）",
        "rule": "成绩／学情只作教学参考，不据此生成德育结论或写入德育周报；与班主任端／行政端数据互不打通",
    },
    {
        "id": "headteacher", "name": "班主任端", "sub": "学生综合",
        "who": "班主任（含兼任任课教师／行政职务者）",
        "manages": "学生 · 本班综合（德育、成绩、特长、交友、目标、归寝、请假）",
        "one_liner": "管学生综合：德育为主，兼工作四项与归寝请假",
        "focus": "班级学生综合管理：以德育为主，兼班主任工作四项＝成绩／特长／交友／目标制定（只读派生区结论）",
        "desk": ["班级概览", "需关注清单", "归寝与请假", "德育记录", "周报与归档", "目标跟进"],
        "data_scope": "class:本班（教师端只读派生区，姓名掩码）；物理不查 answers／scores",
        "tools": ["get_class_summary", "list_class_unreturned", "get_warning_summary",
                  "get_student_profile", "get_consecutive_unreturned"],
        "chain": "六级行政链 L1 起点：周报自动生成并逐级上行，人审不阻断上行；写入类须两段式回显确认",
        "agent": "bzr_secretary_v1（班主任秘书）",
        "rule": "不得跨班、不得查家长电话／身份证／请假事由；派生区未就绪一律降级，不以旧值或估算值替代",
    },
    {
        "id": "admin", "name": "行政端", "sub": "管老师与班主任",
        "who": "政教干事、政教副主任／团委副书记、政教主任、分管副校长、校长及团线职务",
        "manages": "教师与班主任（管理者）· 不直接管学生个体",
        "one_liner": "管老师或班主任：履职、汇总、审批、逐级推送与催办",
        "focus": "对教师与班主任的履职管理：条线汇总、分级审批、对外口径、逐级自动推送与上级催办；不直接处置学生个体",
        "desk": ["所辖岗位与履职", "条线汇总", "分级审批", "推送流", "催办闭环", "台账与审计"],
        "data_scope": "随六级层级递增脱敏：L2 条线明细→L3 班级维度→L4 年级维度→L5 指标级→L6 全校统计；行政端不下发学生姓名级明细",
        "tools": ["get_class_summary", "get_warning_summary"],
        "chain": "六级行政链 L2—L6 在本端内运行；团委线单列（团内程序，不进链、不纳入考核与留痕）",
        "agent": "按 post_id 一岗一智能体（zj_*／tw_*／xld_*／xz_*）",
        "rule": "上级只催办直接下级、逐级不越级；安全／舆情／重大心理危机／涉法涉诉不进系统，以电话／当面为准",
    },
]
PORTAL_INDEX = {p["id"]: p for p in PORTALS}
PORTAL_ORDER = [p["id"] for p in PORTALS]

# 岗位／部门关键字 → 端（服务端判定，前端只把 portal 作为筛选意图提交）
PORTAL_RULES = [
    (["任课教师", "教务科", "教务处", "教师端", "教研"], "teacher"),
    (["班主任"], "headteacher"),
]
PORTAL_DEFAULT = "admin"

# 用户 2026-11-12 08:12 口径：按「管理对象」区分三端
PORTAL_MANAGES_NOTE = (
    "教师端管学生的**日常学习**（课堂教学、作业、学情）；"
    "班主任端管学生的**综合**（德育为主，兼工作四项与归寝请假）；"
    "行政端管**老师或班主任**（管理者履职、汇总、审批、推送与催办），不直接管学生个体。"
    "管理对象不同决定了数据边界：教师端与班主任端面向学生数据（按课程／按班、姓名掩码、只读派生区），"
    "行政端面向教师与班主任的履职数据，只收逐级脱敏聚合，不下发学生姓名级明细。"
)

# 用户 2026-11-12 08:12 升级：一个入口 ＋ 卡片式单口选择
PORTAL_ENTRY_RULE = (
    "一个入口：所有账号从同一入口进入，服务端按企业微信通讯录判定其实际职务，"
    "只把「有职务的端」渲染成卡片；只是教师→1 张（教师端），教师＋班主任→2 张，"
    "教师＋班主任＋行政→3 张；无职务的端不出现、不可进入。"
    "卡片为单选，选中后才装载该端主职务的智能体；未选端时不装载任何智能体、不产生会话上下文。"
)
PORTAL_CARD_NOTE = (
    "卡片按 PORTAL_ORDER（教师端→班主任端→行政端）固定顺序排列，不受账号主职务影响；"
    "卡片只显示端名、管理对象、一句话职责、职务数与主职务，不显示该端以外的数据，"
    "也不因卡片存在而提权；选择卡片时前端只传 userid＋portal，服务端重新校验合法职务列表。"
)

# 用户 2026-11-12 08:42 口径：根据企业微信一个人多个角色自动匹配加载，不要手动选择
PORTAL_AUTO_RULE = (
    "自动匹配加载：以企业微信通讯录为唯一角色来源，账号登录（或企微回调）后服务端一次性解析"
    "该 userid 的全部有效职务（一人可多角色、可跨教师端／班主任端／行政端），"
    "自动为每个 post_id 匹配唯一 agent_id，自动装载主职务智能体并直接进入工作台；"
    "其余角色自动匹配就绪、在工作台内直接切换，不出现入口卡片、不要求用户手动选端或选卡。"
    "主职务取 primary_flag=1，其次 in_chain=1，再次按 PORTAL_ORDER 的首个职务；"
    "角色清单按端分组下发，前端只提交 userid，不得提交 level／agent_id／data_scope／curLevel。"
    "自动匹配只装载一个当前会话上下文，其余角色仅作就绪登记、不产生会话、不共享上下文；"
    "切换职务仍作废旧会话、清空待确认写入与催办草稿，三端智能体与数据互不打通，"
    "审计按 userid＋post_id＋agent_id 三元组留痕。"
)
PORTAL_AUTO_NOTE = (
    "「自动匹配加载」取代 2026-11-12 08:12 的「一个入口·卡片式单口选择」："
    "按角色自动判定、三端管理对象与端间数据隔离口径均不变，取消的是「手动点卡片选端」这一步；"
    "卡片形态保留为「我的角色」非阻断面板，仅用于查看自动匹配结果与切换职务，不是进入系统的前置动作。"
    "portal/cards 与 portal/enter 保留为兼容接口与历史快照，不再是进入路径。"
)

PORTAL_NOTE = (
    "三端是「工作台／界面与数据边界」的划分，六级行政链是「行政端内部的推送层级」，"
    "二者维度不同、不得混用：教师端与班主任端不属于行政层级，行政端 L2—L6 才是链上的推送节点，"
    "班主任端作为 L1 起点向行政端 L2 上行。一个 userid 可跨端持有多个 post_id，"
    "端是第一层导航、职务是第二层；团线职务归行政端但仍按团内程序单列。"
    + PORTAL_MANAGES_NOTE
)
PORTAL_ISOLATION = (
    "切换端＝切换一组职务：作废旧会话，清空上一端的会话上下文、待确认写入与催办草稿；"
    "三端智能体与数据互不打通，跨端不继承 level／data_scope／agent_id，"
    "审计按 userid＋post_id＋agent_id 留痕。"
)

# ---------------------------------------------------------------- 共建空间（PC015，v0.14）
# 用户 2026-11-12 12:24 口径：秘书智能体随着角色不同，跟随工作台一起共建空间、共享上下文。
# 边界：共享只发生在「同一角色空间内」（秘书智能体 ↔ 工作台模块／视图），
#       不同角色＝不同空间，空间之间仍按 PORTAL_ISOLATION 与数据边界互不打通。
SPACE_RULE = (
    "共建空间：秘书智能体不是独立的对话窗口，而是随角色（post_id→agent_id）跟随该角色的工作台"
    "一起共建一个空间（space）；空间内「秘书对话」与「工作台模块／视图」共同读写同一份共享上下文，"
    "秘书知道工作台当前打开的模块、班级与数据就绪日，工作台也能显示秘书刚生成的周报卡片、"
    "需关注清单与待确认写入草稿，二者不再各说各话。"
    "一个角色一个空间：space 由服务端在装载该职务智能体时按 userid＋post_id＋agent_id 建立，"
    "前端不得指定 space_id、不得跨空间写入或读取。"
    "秘书智能体随角色不同而不同（一岗一智能体），工作台随角色呈现本端模块，空间随角色共建，"
    "自动匹配加载时只共建并激活主职务空间，其余角色的空间仅登记就绪、不装载、不共享上下文。"
)
SPACE_SHARED_FIELDS = (
    # 空间内共享上下文的白名单字段：仅结构化、脱敏、非敏感键；禁止任何自由文本与身份字段
    "focus_module",       # 工作台当前模块／视图
    "focus_class",        # 当前班级 class_id
    "focus_masked",       # 当前学生姓名掩码（字段白名单内）
    "last_intent",        # 秘书最近一次意图标签（固定枚举，非原文）
    "last_card",          # 最近一次卡片类型
    "pending_write_id",   # 待确认写入草稿 id
    "dun_draft_id",       # 催办草稿 id
    "ready_date",         # 数据就绪日
    "reconcile",          # 口径未对齐标注
    "turn_count",         # 空间内对话轮次
    "module_hits",        # 工作台模块访问计数
    "updated_by",         # 最近写入方：secretary／workbench
)
# 身份与权限字段由服务端独占；自由文本与字段黑名单／禁查库字段一律不进共享上下文
# （字面量列出，避免引用本文件后面才定义的 FIELD_BLACKLIST／FORBIDDEN_DB_FIELDS）
SPACE_FORBIDDEN_FIELDS = (
    "space_id", "session_id", "user_id", "post_id", "agent_id", "level",
    "data_scope", "portal", "curLevel", "role_level", "text", "content", "reply",
    "parent_name", "parent_phone", "student_phone", "leave_reason", "id_card", "home_address",
    "answers", "scores", "psych_detail", "goal_text", "checkin_detail",
)
# 空间接口的前端请求体禁止字段：space_id／身份／权限一律由服务端按 session_id 反查
# （session_id 本身允许，前端只凭会话操作自己的空间）
SPACE_FRONTEND_FORBIDDEN = (
    "space_id", "user_id", "post_id", "agent_id", "portal", "level",
    "data_scope", "curLevel", "role_level",
)
SPACE_ISOLATION = (
    "空间间隔离不变：切换职务＝归档旧空间并清空其共享上下文（连同会话上下文、待确认写入、催办草稿），"
    "重建新角色空间；新空间不继承旧空间的 focus／卡片／草稿，不继承 level／data_scope／agent_id，"
    "三端智能体与数据互不打通。共享上下文只收 SPACE_SHARED_FIELDS 白名单的结构化脱敏键，"
    "字段黑名单、只读派生区、家长电话／请假事由／身份证、人工通道零留痕全部不变；"
    "秘书对话与工作台读写均按 userid＋post_id＋agent_id＋space_id 四元组留痕。"
)
SPACE_NOTE = (
    "「共建」＝秘书智能体与工作台在同一空间内共同写上下文：工作台切模块／选班级写 focus，"
    "秘书对话写 last_intent／last_card／pending_write_id／turn_count；任一方写入后另一方立即可见。"
    "「共享上下文」≠ 跨角色共享数据：不同角色、不同端的空间各自独立，"
    "共享的是本角色空间的脱敏工作状态，不是学生明细或他职务数据。"
)

# ---------------------------------------------------------------- 同类横向协同（PC016，v0.15）
# 用户 2026-11-12 口径：同一类如教师角色，智能体可以横向协同搜索聚合，但是自己的上下文不污染。
# 边界：横向＝同一类角色池内；只读＝只搜聚合脱敏业务数据，不写回任何一方空间的共享上下文；
#       无状态＝一次性取数即弃，不新建会话／空间，不把别人的上下文带到自己这里。
FEDERATION_RULE = (
    "同类横向协同：服务端按企业微信通讯录把「同一类角色」的智能体归为一个同类池（pool），"
    "池内多个秘书智能体可横向协同：只读地搜索、聚合彼此可见范围内的脱敏业务数据，"
    "形成池级汇总供本角色参考；但不合并智能体、不合并工作台、不新建会话与空间。"
    "聚合是一次性只读取数、即取即弃，聚合结果不写回任何一方空间的共享上下文，"
    "也不把其他成员的共享上下文（focus／意图／卡片／草稿等）带到自己这里。"
)
FEDERATION_POOL_NOTE = (
    "同类池由服务端按 portal＋level＋in_chain＋committee_line＋level_pending 五元组判定："
    "同端、同层级、同在链状态、同团线归属、同层级确认状态才算同类，"
    "跨端／跨层级／跨链／团线与行政线／待确认层级与已确认层级一律不同池、不可互相聚合。"
    "pool_id 由服务端按五元组确定性生成，前端只提交 session_id 与指标枚举，"
    "不得指定池、成员或身份字段。"
)
FEDERATION_METRICS = (
    {"id": "roster", "name": "岗位协同名册",
     "desc": "同类池成员的岗位元数据聚合（不含任何学生数据）"},
    {"id": "overview", "name": "班级概览聚合",
     "desc": "各成员已绑定班级的班级概览脱敏数字＋池级汇总"},
    {"id": "dorm", "name": "归寝与预警聚合",
     "desc": "各成员已绑定班级的归寝异常／预警数与数据就绪状态"},
    {"id": "readiness", "name": "就绪度聚合",
     "desc": "各成员班级的数据就绪日、口径冲突与派生区绑定状态"},
)
FEDERATION_METRIC_INDEX = {m["id"]: m for m in FEDERATION_METRICS}
# 聚合结果字段白名单：只放组织元数据与脱敏聚合数字／布尔／状态；名单、明文、空间上下文键一律不收
FEDERATION_AGGREGATE_FIELDS = (
    # 成员与池元数据
    "post_id", "post_name", "agent_id", "user_id", "name", "portal", "level",
    "in_chain", "committee_line", "level_pending", "class_ids", "data_scope",
    "pool_id", "pool_dims", "member_count", "metric", "keyword", "is_self", "status",
    # 可用性与降级
    "available", "reason", "rule", "source", "zone", "note", "returns",
    # 班级概览／周报数字
    "class_id", "size", "attendance_rate", "attention_count", "balance_unbalanced",
    "role_registered", "leave_count", "leave_reconcile", "attendance_note", "moral_note",
    "dorm_anomaly", "dorm_note", "leave_note", "degraded", "warning_count",
    # 就绪度
    "ready_date", "ready_dates", "reconcile_conflict", "reconcile_note", "derived_pending",
    "derived_pending_note", "coverage_ready", "coverage_pending", "no_full_profile",
    "data_ready_note", "mcp_tools", "field_whitelist", "field_blacklist",
    "no_direct_platform_access", "token_scope_ok",
    # 池级汇总
    "covered_members", "pool_members", "partial", "aggregate", "totals",
    "sum_size", "sum_attention_count", "sum_warning_count", "sum_dorm_anomaly",
    "max_attention_count", "degraded_members", "reconcile_conflict_members",
    "ready_date_members", "posts", "peers", "pools", "metrics", "queries",
    "keyword_len", "result", "ts", "dims", "metric_name", "desc",
    "no_context_pollution", "writes_to_space", "stateless", "row_count", "rows",
    "space_shared_before", "space_shared_after", "pool_count", "current_pool",
    "self_post_id", "portal_name", "rule", "pool_note", "isolation", "id",
)
# 明确禁止：学生明细／敏感字段／自由文本／共建空间上下文键／身份与权限伪造字段
FEDERATION_FORBIDDEN_FIELDS = (
    "students", "items", "unreturned", "late", "missing_info", "name_masked", "student_id",
    "parent_name", "parent_phone", "student_phone", "leave_reason", "id_card", "home_address",
    "answers", "scores", "psych_detail", "goal_text", "checkin_detail", "dorm_no",
    "text", "content", "reply", "shared", "shared_json", "space_id", "session_id",
    "focus_module", "focus_class", "focus_masked", "last_intent", "last_card",
    "pending_write_id", "dun_draft_id", "turn_count", "module_hits", "updated_by",
    "space_events", "chat_turns", "payload", "payload_json", "shared_json_before",
)
# 前端请求体禁止字段：池／成员／身份／空间上下文一律由服务端按 session_id 反查
FEDERATION_FRONTEND_FORBIDDEN = (
    "pool_id", "members", "peers", "pool_dims", "member_count", "agent_id", "level",
    "data_scope", "portal", "post_id", "user_id", "space_id", "space_shared",
    "shared", "shared_json", "patch", "aggregate", "metric_data", "rows",
)
FEDERATION_ISOLATION = (
    "上下文不污染：聚合只走只读派生区，不调用 space.write_shared／record_secretary，"
    "不写 spaces／space_events／chat_turns／sessions，不新建或激活任何空间；"
    "服务端在聚合前后对当前角色空间的 shared_json 做完全相等校验，"
    "任何不一致即判定污染、返回错误并写审计；"
    "聚合结果只作为一次响应返回，不留入本角色空间的共享上下文，"
    "不继承其他成员的 level／data_scope／agent_id／space_id，也不携带他方共享上下文键。"
    "切换职务归档旧空间、空间间不继承、三端数据互不打通等既有红线全部不变；"
    "字段白名单、只读派生区、家长电话／请假事由／身份证、人工通道零留痕不变。"
)
FEDERATION_NOTE = (
    "「横向协同」不等于「合并上下文」：PC015 的共享上下文只发生在同一角色空间内"
    "（秘书智能体 ↔ 本角色工作台）；PC016 的聚合发生在同类池的多个角色之间，"
    "是只读、无状态、即取即弃的搜索聚合，二者方向不同、互不覆盖。"
    "同类池内每个成员仍是一岗一智能体、一个角色一个空间；未绑定班级的成员一律 available=false，"
    "不拿默认班级示例值或旧值顶替，池级汇总只统计已覆盖成员并标注覆盖数。"
)

# ---------------------------------------------------------------- 协同教育推送（PC017）
# 用户 2026-11-12 口径：教师端与班主任端在关系上不存在隶属管理，但存在协同教育学生的关系；
# 任课教师可把所代课程班级的平时考试／学习状态自动推送给该班班主任，便于班主任统筹学生成长。
COEDU_RULE = (
    "协同教育推送：教师端与班主任端在关系上不存在隶属管理，但存在协同教育学生的关系。"
    "任课教师对所代课程班级的平时考试／学习状态，由服务端按企业微信通讯录的任课绑定"
    "（教师 post_id → 所代课程班级 class_id＋科目）自动定向推送到该班班主任端，"
    "便于班主任统筹学生成长；教师端不因此成为班主任的上级，班主任端也不因此成为教师端的上级。"
    "该通道是单向、定向、脱敏、只读派生区的协同教育消息，不是三端打通、不是共享上下文、"
    "不是跨端取数，也不属于 PC016 同类池（跨端跨类角色）。"
)
COEDU_RELATION_NOTE = (
    "关系定性：非隶属管理、只协同育人。协同教育推送不构成上下级、不进入六级行政链、"
    "不参与逐级自动推送与上级催办、不纳入考核与留痕；上级催办仍只发生在 L1—L6 行政链内。"
    "行政端不直接管学生个体、团线单列、三端数据互不打通等既有边界全部不变。"
)
COEDU_METRICS = (
    {"id": "exam", "name": "平时考试／学情批次",
     "desc": "考试批次就绪标注＋派生区需关注人数与建议动作；成绩域未接入前不出分数／排名／明细"},
    {"id": "status", "name": "学习状态",
     "desc": "班级级脱敏学情汇总（出勤率／需关注人数／四维失衡人数／数据就绪日／口径标注）"},
)
COEDU_METRIC_INDEX = {m["id"]: m for m in COEDU_METRICS}
COEDU_LINK_NOTE = (
    "任课绑定由服务端按企业微信通讯录＋教务处课表判定：教师 post_id → 所代课程班级 class_id＋科目。"
    "一个教师可教多个班（多条收件人）、一个班可有多位任课教师（班主任收到多条）。"
    "任课班级／科目在企微通讯录尚无来源（PC010，教务处待补录）；样本内置演示绑定仅用于验收，"
    "正式上线须由教务处补录、信息化处写入通讯录绑定表后才生效。"
    "收件人只认该班班主任端 L1 职务（in_chain=1、committee_line=0），不认行政端、团线与待确认层级。"
)
# 推送内容白名单：只放班级级脱敏汇总、组织元数据、状态与口径标注
COEDU_PUSH_FIELDS = (
    "push_id", "ts", "metric", "metric_name", "class_id", "subject", "batch",
    "available", "reason", "rule", "note", "source", "zone", "size",
    "attendance_rate", "attention_count", "balance_unbalanced", "reconcile",
    "ready_date", "exam_numeric_available", "derived_pending", "degraded",
    "teacher_user_id", "teacher_post_id", "teacher_agent_id", "teacher_name",
    "bzr_user_id", "bzr_post_id", "bzr_agent_id", "bzr_name",
    "status", "self_user", "recipient_count", "pushed_count", "skipped_count",
    "no_context_pollution", "writes_to_space", "stateless",
    "rows", "links", "inbox", "push_count", "inbox_count", "link_count",
    "metrics", "rule_text", "relation", "link_note", "isolation", "note_text",
    "pending", "space_shared_before", "space_shared_after",
)
# 明确禁止：学生名单与明细、成绩／作答原文、敏感字段、自由文本、对话原文、空间上下文键
COEDU_FORBIDDEN_FIELDS = (
    "students", "items", "unreturned", "late", "missing_info", "student_id", "name_masked",
    "student_list", "exam_items", "score", "scores", "rank", "answers", "paper", "psych_detail",
    "goal_text", "checkin_detail", "parent_name", "parent_phone", "student_phone",
    "leave_reason", "id_card", "home_address", "text", "content", "reply",
    "shared", "shared_json", "space_id", "session_id", "focus_module", "focus_class",
    "focus_masked", "last_intent", "last_card", "pending_write_id", "dun_draft_id",
    "turn_count", "module_hits", "updated_by", "space_events", "chat_turns", "payload",
)
# 前端请求体禁止字段：班级／科目／批次／收件人／身份／空间一律由服务端按 session_id 反查
COEDU_FRONTEND_FORBIDDEN = (
    "class_id", "subject", "batch", "recipients", "recipient", "bzr_post_id", "bzr_user_id",
    "bzr_agent_id", "teacher_post_id", "teacher_user_id", "teacher_agent_id",
    "self_user", "summary", "summary_json", "push_id", "status", "metric_data", "rows",
    "pool_id", "members", "peers", "agent_id", "level", "data_scope", "portal",
    "post_id", "user_id", "space_id", "shared", "shared_json", "patch",
)
COEDU_ISOLATION = (
    "上下文不污染：推送只写独立的 coedu_pushes 收件箱与三元组审计，"
    "不调用 space.write_shared／record_secretary，不写 spaces／space_events／chat_turns／sessions，"
    "不新建或激活任何空间；服务端在推送前后对发起者当前角色空间的 shared_json 做完全相等校验，"
    "不一致即判定污染、记审计并拒绝。班主任端读取收件箱为纯只读，不回写班主任空间共享上下文；"
    "教师端不能反查班主任端德育数据，班主任端也不能反查教师端工作台与空间上下文。"
    "字段白名单、只读派生区、家长电话／请假事由／身份证、数据就绪日与口径未对齐降级、"
    "2607／2611 双试点分源、人工通道零留痕全部不变。"
)
COEDU_NOTE = (
    "「协同教育推送」不等于「打通三端」：它是有明确收件人的单向定向投递，"
    "既不是 PC015 同一角色空间内的共享上下文，也不是 PC016 同类池内的横向只读聚合。"
    "自动推送由考试批次导入／学情状态更新事件触发，不设逐级人工放行卡点；"
    "但推送内容只含班级级脱敏事实与建议动作，不生成定性结论、评语、处分与需关注名单明细；"
    "班主任据此写德育记录、生成周报仍走两段式草稿与人审。"
    "成绩／考勤／德育／心理尚未接入成长导航画像，平时考试指标按既有红线降级为「暂不可用」，"
    "不编造分数、排名或旧值，通道与收件人已就绪，待成绩域接入后自动生效。"
)

# ---------------------------------------------------------------- 六级行政链
LEVELS = [
    {"id": "L1", "name": "班主任", "scope": "本班派生结论（姓名掩码）· 德育为主＋工作四项",
     "out": "班级周报 → 政教干事", "freq": "每周一 06:50",
     "hitl": "周报确认归档、写入回显确认", "desensitize": "姓名掩码"},
    {"id": "L2", "name": "政教干事", "scope": "本岗条线明细＋所辖班级维度（姓名掩码）",
     "out": "条线周汇总 → 政教副主任", "freq": "每周一 12:00",
     "hitl": "条线数据核对、异常处置审核", "desensitize": "姓名掩码"},
    {"id": "L3", "name": "政教副主任＝团委副书记", "scope": "分管条线汇总（班级维度，不含姓名）· 同级双线并列",
     "out": "双线周汇总 → 政教主任", "freq": "每周五 17:00",
     "hitl": "教育惩戒审核、处分提出、对外发布初审", "desensitize": "班级维度"},
    {"id": "L4", "name": "政教主任（兼团委书记）", "scope": "全校德育口径、各年级对比（年级维度）",
     "out": "条线简报 → 分管德育副校长", "freq": "每月 1 日",
     "hitl": "警告／严重警告审批、对外发布、记过及以上审核", "desensitize": "年级维度"},
    {"id": "L5", "name": "分管德育副校长", "scope": "分管线指标与项目进度（不含个人数据）",
     "out": "条线态势 → 校长", "freq": "每月 5 日",
     "hitl": "复学审批、约谈与资源事项签发确认", "desensitize": "指标级"},
    {"id": "L6", "name": "校长", "scope": "仅全校统计指标（不含任何个人与班级明细）",
     "out": "决策与对外口径", "freq": "每季度／学期",
     "hitl": "对外口径终审、年度评估、记过及以上提交校长办公会", "desensitize": "全校统计"},
]
LEVEL_INDEX = {l["id"]: i for i, l in enumerate(LEVELS)}

# 逐级自动推送时刻表：报告自动生成、自动推送，不设逐级人工放行卡点
PUSH_SCHEDULE = [
    {"level": "L1", "cron": "周一 06:50", "weekday": 0, "hour": 6, "minute": 50, "day": None},
    {"level": "L2", "cron": "周一 12:00", "weekday": 0, "hour": 12, "minute": 0, "day": None},
    {"level": "L3", "cron": "周五 17:00", "weekday": 4, "hour": 17, "minute": 0, "day": None},
    {"level": "L4", "cron": "每月 1 日", "weekday": None, "hour": 8, "minute": 0, "day": 1},
    {"level": "L5", "cron": "每月 5 日", "weekday": None, "hour": 8, "minute": 0, "day": 5},
    {"level": "L6", "cron": "每季度／学期", "weekday": None, "hour": 8, "minute": 0, "day": None},
]

# 岗位关键字 → 层级（企业微信通讯录的部门路径＋岗位由服务端判定）
POST_LEVEL_RULES = [
    (["班主任"], "L1"),
    (["政教干事"], "L2"),
    (["政教副主任", "团委副书记"], "L3"),
    (["政教处主任", "政教主任"], "L4"),
    (["团委书记"], "L4"),
    (["分管德育副校长", "分管副校长"], "L5"),
    (["校长"], "L6"),
]

# ---------------------------------------------------------------- 人工通道（零留痕）
OFFLINE_ITEMS = [
    "校园安全事件（伤害、事故、消防、食品安全）",
    "舆情与负面传播（网络、媒体、家长群扩散）",
    "重大心理危机与自伤风险",
    "涉法涉诉、师德师风、纪检线索",
    "其他需即时人工判断、不宜数据留痕的事项",
]
OFFLINE_REPLY = (
    "该类事项不纳入本系统，也不生成、不转述、不留系统痕迹。"
    "请按学校既定线下制度，由责任人电话直报或当面汇报；确需记录走线下纸质流程。"
)
OFFLINE_PATTERN = (
    r"安全事故|伤害|消防|食品安全|舆情|负面|曝光|媒体|网上|家长群.*扩散|"
    r"涉法|纪检|举报|越级|抄送|上报校长|直接报|自杀|自伤"
)

# ---------------------------------------------------------------- 派生区红线
DERIVED_FORBIDDEN_PATTERN = (
    r"原始分|维度分|原始作答|雷达图|八维|心理明细|心理内容|谁看过我|"
    r"目标写了什么|目标文本|打卡明细|个人目标|帮我看他.*目标|"
    r"心理量表|测评结果|身份证|学籍号|家庭住址|家长电话|联系方式"
)
DERIVED_BOUNDARY_REPLY = (
    "该数据属于学生成长导航系统个人区／心理区，班主任只读派生区，"
    "请由学生本人在学生端查看或主动授权分享。"
)
# 教师端接口物理上不查 answers / scores；越权返回 HTTP 403 并写审计
FORBIDDEN_DB_FIELDS = ("answers", "scores", "psych_detail", "goal_text", "checkin_detail",
                       "parent_phone", "parent_name", "student_phone", "leave_reason", "id_card")

# 字段白名单（智慧校园平台对接方案 §五）：白名单外一律不进模型上下文
FIELD_WHITELIST = ["student_id", "name_masked", "class_id", "grade", "dorm_status",
                   "leave_type", "leave_start", "leave_end"]
FIELD_BLACKLIST = ["parent_name", "parent_phone", "student_phone", "leave_reason",
                   "id_card", "home_address"]

# 当前已跑通的只读 MCP 工具（growth-agent，2026-11-11 实测）
MCP_TOOLS = [
    {"name": "get_class_summary", "returns": "人数／男女生／住宿走读／专业分布／归寝统计／请假数"},
    {"name": "list_class_unreturned", "returns": "本班未归／晚归／缺信息名单"},
    {"name": "get_warning_summary", "returns": "未归＋缺信息名单，可按班"},
    {"name": "get_student_profile", "returns": "单个学生画像（含班级上下文）"},
    {"name": "get_consecutive_unreturned", "returns": "连续未归天数（只计数据就绪日）"},
]
COVERAGE_READY = ["学籍", "归寝", "请假"]
COVERAGE_PENDING = ["成绩", "考勤", "德育", "心理"]
NO_FULL_PROFILE = "当前仅学籍／归寝／请假三类，成绩／考勤／德育／心理未接，不得称「完整学生画像」，不得据此生成成绩或德育结论"

# 数据就绪日：查寝数据未生成 → 未就绪，不把未生成当未归
DATA_READY_NOTE = "归寝统计只认「数据就绪日」；未生成返回「未就绪」，不把未生成当未归；连续未归链条遇缺口日提示截断、不补算"
RECONCILE_NOTE = "请假与归寝口径未对齐（请假 1 条 vs leave=0）时暂停该数字、标注暂不可用、通知信息化处，不以估算值或旧值替代"

# ---------------------------------------------------------------- 三套术语（不得混用）
TERMINOLOGY = {
    "work_items": "班主任工作四项＝成绩／特长／交友／目标制定（工作口径，德育为主）",
    "balance": "成长导航「四维平衡」＝学习／交友／兴趣／健康（方案任务13、57号接口）",
    "goals": "学生「六级目标」＝三年／年／学期／月／周／日，与组织六级行政链无关",
}

# ---------------------------------------------------------------- 团委线单列
COMMITTEE_NOTE = (
    "团委副书记与政教副主任同为 L3；团员发展、团费、团内评优、换届等按团内程序"
    "经团委委员会／团员大会决定，报学校党组织和上级团委，不进入六级行政推送链、"
    "不纳入本工作台考核与留痕"
)

# ---------------------------------------------------------------- 前端禁止伪造字段
FRONTEND_FORBIDDEN_FIELDS = ("level", "agent_id", "data_scope", "curLevel", "role_level")

# ---------------------------------------------------------------- 固定话术
REPLY = {
    "cancel": "已取消，未产生任何写入。",
    "ambiguous": "请明确回复「确认」或「取消」；含糊回复不会触发写入。",
    "sensitive": "该字段不在字段白名单内，不进模型上下文、不返回。请通过线下渠道按学校制度办理。",
    "psych": "心理明细属心理区独立库独立密钥，仅布尔 referred 过河、内容永不过河，班主任不可见。",
    "external": "对外发布、处分说明、评语终稿、能力／人际定性需人工签发，本秘书不生成、不代发。",
    "cross_scope": "无权访问：请求超出本职务数据范围，已拒绝并记审计日志（userid＋post_id＋agent_id）。",
    "degrade": "该项数据暂不可用（口径表更新中／数据未就绪），已通知信息化处，不以旧值或估算值替代；本级报告暂停该数字。",
    "batch": "该操作请在工作台完成（图形化操作保留界面），已为您切换过去。",
    "not_connected": "成绩／考勤／德育／心理尚未接入当前画像工具，该结论暂不可用；不得据此生成结论或写入周报。",
    "archive_hitl": "周报需班主任确认后方可归档至成长导航档案；未经确认的版本不进入档案。",
    "committee": COMMITTEE_NOTE,
}

# ---------------------------------------------------------------- 卡片类型（对齐 04_卡片与消息模板.json）
CARD_TYPES = ["weekly_report", "write_echo", "event_alert", "watchlist_digest",
              "degraded_notice", "growth_overview", "post_switch", "derived_boundary"]

# ---------------------------------------------------------------- 写入类型（两段式）
WRITE_KINDS = {
    "moral_record": "德育记录（加分／扣分／表扬／违纪）",
    "communication": "沟通／家访留痕",
    "attendance_patch": "单笔出勤补记",
    "task": "待办（P0／P1／P2）",
    "archive": "周报归档",
    "dun": "催办下达",
}

# ---------------------------------------------------------------- 真实通讯录接入的待确认口径
# 来源：G:/deepseek/京山职校通讯录.xlsx（企业微信通讯录导出，2026-11-11）
# 待确认项在确认前不得作为正式层级依据，也不参与六级自动推送的层级判定。
PENDING_CONFIRMATIONS = [
    {
        "id": "PC001",
        "topic": "方成「政教处分管主任」的层级归属",
        "detail": "《当日未归分级推送与处置流程》把方成标为政教处分管主任、L3 升级节点；"
                  "但六级行政链 L3＝政教副主任／团委副书记，L4＝政教处主任（兼团委书记）。"
                  "「分管主任」是否等同 L3 副主任、或应归 L4，尚无定论。",
        "current": "绑定表按 L3 试挂（对齐未归处置流程），标记 level_pending=1、in_chain=0；"
                   "确认前不参与自动推送与催办的层级判定",
        "owner": "政教处＋信息化处",
        "status": "待确认",
    },
    {
        "id": "PC002",
        "topic": "教务线兼任职务是否纳入德育六级推送链",
        "detail": "方成同时挂「京山职校/教务科/教务处/任课教师」，属教务线，不在政教处六级行政链内。"
                  "参照团委线单列原则，暂按独立岗位智能体装载，不并入德育上行链。",
        "current": "in_chain=0；确认前不生成上行报告、不作为催办对象",
        "owner": "政教处",
        "status": "待确认",
    },
    {
        "id": "PC003",
        "topic": "通讯录「职务」列为空导致自动判层失效",
        "detail": "企微通讯录导出中方成的职务列为空、部门路径只到「政教处」；"
                  "resolve_level() 按部门关键字会把三个职务全部误判为 L1（班主任规则优先命中）。"
                  "绑定表必须由政教处补录，且以绑定表为准，自动判定结果仅留作对照。",
        "current": "level_source=政教处补录；org_posts 同时保留 auto_level 供核查",
        "owner": "政教处＋信息化处",
        "status": "待确认",
    },
    {
        "id": "PC004",
        "topic": "coredump 账号与工号口径对齐",
        "detail": "方成企微 userid 为 coredump（非工号）。按《账号规范化方案》，"
                  "昵称类账号统一改工号、企微 userid 写入 Casdoor 的 external_id 作对照。",
        "current": "样本按 userid=coredump 直接接入；正式上线前须完成工号映射并留 external_id",
        "owner": "信息化处",
        "status": "待确认",
    },
    {
        "id": "PC005",
        "topic": "徐海潮团线职务口径：团委副书记（已确认）",
        "detail": "用户 2026-11-12 明确更正：徐海潮是「团委副书记」。"
                  "11-11 曾按「团委书记」L4 试挂，与企微通讯录「团支部副书记」不一致；"
                  "按方案六级行政链 L3＝政教副主任＝团委副书记、L4＝政教主任（兼团委书记），"
                  "「团委副书记」与通讯录「团支部副书记」同属副书记序列，口径已对齐。",
        "current": "已收敛：p_xhc_tw 改为「团委副书记（团内程序·兼任）」，绑定 L3、"
                   "agent_id=tw_fshuji_v1、level_pending=0；"
                   "团线仍单列（committee_line=1、in_chain=0），不进六级自动推送与催办、不纳入考核与留痕。"
                   "班主任职务 p_xhc_bzr_2607（L1）不变，一岗一智能体",
        "owner": "政教处＋团委＋信息化处",
        "status": "已确认（2026-11-12）",
    },
    {
        "id": "PC006",
        "topic": "2607「成长导航系统试点班」与 2611「一期试点班」不得混用",
        "detail": "用户本次口径：2607 是成长导航系统试点班、班主任徐海潮；"
                  "既往文档中「试点班」多指 2611（AI 教学／学生成长智能助手一期 50 人）。"
                  "两套数据一个来自真实系统只读贴源聚合、一个来自原型脱敏示例。",
        "current": "样本按 class_id 分源（data/fixtures_2607.json 与 data/fixtures.json）；"
                   "2611 保留原型基准、2607 为真实拉取脱敏汇总，禁止互相替代或合并统计",
        "owner": "政教处＋信息化处",
        "status": "待确认",
    },
    {
        "id": "PC007",
        "topic": "2607 教师端派生区（四维平衡／六级目标／成长画像）尚未绑定",
        "detail": "真实成长导航系统 /teacher/classes 当前只返回 1 个班级「2026级1班」(classId=1)，"
                  "/admin/roles 账号体系中无徐海潮与 2607 的班主任绑定；"
                  "2607 目前只有学籍／归寝／请假贴源聚合，没有四维平衡、六级目标、"
                  "growthScore／优势标签等派生区结论。",
        "current": "2607 的 4 个派生区视图一律降级 available=false（不拿 2611 示例值或旧值替代）；"
                   "需信息化处在成长导航系统完成 2607 班级绑定与按角色／班级过滤 token 后再启用",
        "owner": "信息化处＋成长导航系统运维",
        "status": "待确认",
    },
    {
        "id": "PC008",
        "topic": "2607 请假与归寝口径未对齐（已命中红线）",
        "detail": "2026-11-11 归寝聚合 2607 的 leave=0，但 /admin/campus/leaves 中 2607 有 2 条"
                  "病假记录且状态为「已归校」。归寝与请假两域口径不一致。",
        "current": "暂停该数字、标注「暂不可用」、通知信息化处，不以估算值或旧值替代；"
                   "周报 degraded=true，本级报告暂停请假数字（对齐 RECONCILE_NOTE）",
        "owner": "信息化处＋政教处",
        "status": "待确认",
    },
    {
        "id": "PC009",
        "topic": "成长导航账号体系缺少徐海潮（Tiao）与 2607 绑定",
        "detail": "企微 userid=Tiao（徐海潮）在真实成长导航 /admin/roles 职工列表中不存在；"
                  "teacher 派生区只绑定演示账号「陈老师」classId=1。试点班主任无法用真实登录态"
                  "读取 2607 派生区，当前拉取走的是 admin 只读贴源聚合。",
        "current": "样本以企微 userid=Tiao 装载班主任秘书（真实系统绑定待补）；"
                   "上线前须完成 Casdoor／企微账号同步、只读专用账号替换演示高权限账号、"
                   "按角色／班级过滤 token（单 token 校长角色一票否决项）",
        "owner": "信息化处",
        "status": "待确认",
    },
    {
        "id": "PC010",
        "topic": "徐海潮教师端（任课教师）职务来源与任课班级／科目待补录",
        "detail": "用户 2026-11-12 口径：徐海潮既是老师、又是班主任、又是行政端团委副书记。"
                  "但企微通讯录 Tiao 的部门为「京山职校/政教科/政教处」「…/团委」「…/教职员工」，"
                  "职务列为「团支部副书记」，既无「班主任」也无「任课教师」部门；"
                  "班主任（2607）来自用户口径＋控辍保学责任班，任课科目与任教班级没有任何来源记录。",
        "current": "样本按用户口径补录 p_xhc_teacher（任课教师·教务线），portal=teacher、"
                   "agent_id=js_teacher_v1、in_chain=0、data_scope=line:教务科任课教师；"
                   "不进德育六级链、不生成上行报告、不作为催办对象，与班主任端／行政端数据互不打通。"
                   "正式上线前须由教务处补录任课班级与科目，再由信息化处写入通讯录绑定表",
        "owner": "教务处＋政教处＋信息化处",
        "status": "待确认",
    },
    {
        "id": "PC011",
        "topic": "三端与六级行政链的维度边界（不得混用）",
        "detail": "三端＝工作台／界面与数据边界；六级行政链＝行政端内部的逐级推送层级。"
                  "教师端不属于行政层级，班主任端是 L1 起点（不是行政端 L1），"
                  "行政端承载 L2—L6；团线职务归行政端但按团内程序单列、不进链、不考核、不留痕。",
        "current": "已按 PORTAL_NOTE／PORTAL_ISOLATION 固化：端是第一层导航、post_id 是第二层职务；"
                   "切换端清空上下文与草稿；in_chain=0 的职务一律不参与自动推送与催办",
        "owner": "政教处＋信息化处",
        "status": "已确认（2026-11-12 设计口径）",
    },
    {
        "id": "PC012",
        "topic": "本次口语「徐涛／团委书记」与已确认「徐海潮／团委副书记」的口径差异",
        "detail": "用户 2026-11-12 07:52 提到「像徐涛，既是老师又是班主任，又是行政的团委书记」。"
                  "企微通讯录中无「徐涛」，对应人员为徐海潮（userid=Tiao，女）；"
                  "用户同日 00:xx 已明确更正团线职务为「团委副书记」（企微记「团支部副书记」），"
                  "方案 L3＝政教副主任＝团委副书记、L4＝政教主任（兼团委书记）。",
        "current": "样本沿用已确认口径：人名＝徐海潮、团线职务＝团委副书记（L3、团线单列）；"
                   "「团委书记」仅保留为 L4 政教主任兼职及郑主任 p_twsj 团线岗位的合法口径。"
                   "若确需改名或改职务，须由政教处出具书面口径后统一改通讯录绑定表与全部文档",
        "owner": "政教处＋团委＋信息化处",
        "status": "待确认",
    },
    {
        "id": "PC013",
        "topic": "三端管理对象与入口形态（用户 2026-11-12 08:12 口径）",
        "detail": "用户明确：教师端管学生日常学习、班主任端管学生综合、行政端管老师或班主任"
                  "（管理者，不直接管学生个体）；并要求把三端设计升级为「一个入口＋卡片式单口选择」，"
                  "卡片按账号自身在企业微信通讯录中的职务自动判定：只是教师→1 张、"
                  "教师＋班主任→2 张、教师＋班主任＋行政→3 张，未选端不装载智能体。",
        "current": "已按 PORTALS.manages／PORTAL_MANAGES_NOTE／PORTAL_ENTRY_RULE／PORTAL_CARD_NOTE 固化："
                   "行政端管理对象改为「教师与班主任」、只收逐级脱敏聚合、不下发学生姓名级明细；"
                   "新增 /api/v1/portal/cards 与 /api/v1/portal/enter，前端改为统一入口卡片页；"
                   "无职务的端不出卡，强行进入返回 403 并记审计。"
                   "因现有通讯录无「只持任课教师一个职务」的人员，另补演示账号 teacher1（何老师·演示·纯教师，"
                   "非企微真实人员）用于验收「只是教师→1 张教师卡」，正式上线以通讯录同步结果为准。"
                   "2026-11-12 08:42 起由 PC014 迭代为企微角色自动匹配加载、取消手动选卡，"
                   "管理对象与三端边界不变",
        "owner": "政教处＋信息化处",
        "status": "已确认（2026-11-12 设计口径，已由 PC014 迭代）",
    },
    {
        "id": "PC014",
        "topic": "企微角色自动匹配加载、取消手动选卡（用户 2026-11-12 08:42 口径）",
        "detail": "用户明确：根据企业微信一个人多个角色自动匹配加载，不要手动选择。"
                  "上一版「一个入口·卡片式单口选择」仍要求用户点一张卡才进入，与自动加载不符。"
                  "角色来源仍是企微通讯录（userid → 全部有效职务 → post_id → agent_id），"
                  "一人多角色时服务端自动匹配全部角色并直接装载主职务工作台，其余角色自动就绪、"
                  "工作台内直接切换；不新增任何人工选择入口的步骤。",
        "current": "已按 PORTAL_AUTO_RULE／PORTAL_AUTO_NOTE 固化：新增 POST /api/v1/portal/auto，"
                   "前端 init() 直接自动进入主职务工作台，入口覆盖层改为非阻断「我的角色」面板；"
                   "自动匹配只装载一个会话上下文，其余角色不产生会话、不共享上下文；"
                   "切换职务仍清空上一会话、端间数据互不打通、三元组审计不变。"
                   "PC013 的卡片式单口选择口径由本项迭代，三端管理对象与六级链边界不变",
        "owner": "政教处＋信息化处",
        "status": "已确认（2026-11-12 设计口径）",
    },
    {
        "id": "PC015",
        "topic": "秘书智能体随角色跟随工作台共建空间、共享上下文（用户 2026-11-12 12:24 口径）",
        "detail": "用户明确：秘书智能体随着角色不同跟随工作台一起共建空间，共享上下文。"
                  "此前 PC014 的「同一时刻只装载一个会话上下文、切换职务清空上下文、三端数据互不打通」"
                  "是跨角色的隔离红线；本项新增的是「同一角色空间内」的协同："
                  "秘书智能体与该角色的工作台模块／视图共同读写一份共享上下文，"
                  "秘书知道工作台当前模块与班级，工作台能看到秘书刚生成的卡片与草稿。"
                  "角色不同则秘书智能体不同（一岗一智能体）、工作台模块不同、空间也不同；"
                  "自动匹配只共建并激活主职务空间，其余角色空间仅就绪登记。",
        "current": "已按 SPACE_RULE／SPACE_SHARED_FIELDS／SPACE_ISOLATION／SPACE_NOTE 固化："
                   "新增 app/space.py 与 spaces／space_events 表；space_id 由服务端按 "
                   "userid＋post_id＋agent_id 生成并绑定会话，前端只传 session_id；"
                   "新增 GET /api/v1/space、GET /api/v1/spaces、POST /api/v1/space/focus、"
                   "POST /api/v1/space/event；秘书对话与工作台模块读写同一份共享上下文，"
                   "只收白名单结构化脱敏键，禁止自由文本、身份字段与字段黑名单；"
                   "切换职务归档并清空旧空间上下文，空间之间不继承、不打通；"
                   "审计按 userid＋post_id＋agent_id＋space_id 四元组留痕。"
                   "PC014 的自动匹配加载、三端管理对象、六级链与全部数据红线不变",
        "owner": "政教处＋信息化处",
        "status": "已确认（2026-11-12 设计口径）",
    },
    {
        "id": "PC016",
        "topic": "同类角色横向协同搜索聚合、自己的上下文不污染（用户 2026-11-12 口径）",
        "detail": "用户明确：同一类如教师角色，智能体可以横向协同搜索聚合，但是自己的上下文不污染。"
                  "此前 PC015 只解决「同一角色空间内」秘书智能体与工作台共享上下文；"
                  "本项新增的是「同类池内多个智能体之间」的横向只读聚合能力，"
                  "且明确聚合结果不得写回任何一方空间的共享上下文、不得带入他人上下文。",
        "current": "已按 FEDERATION_RULE／FEDERATION_POOL_NOTE／FEDERATION_ISOLATION／FEDERATION_NOTE 固化："
                   "新增 app/federation.py、federation_queries 只读聚合留痕表与 "
                   "/api/v1/federation/pools｜peers｜search 三个接口；"
                   "同类池按 portal＋level＋in_chain＋committee_line＋level_pending 五元组由服务端判定，"
                   "只聚合只读派生区脱敏数字（roster／overview／dorm／readiness 四类指标），"
                   "结果不写 spaces／space_events／chat_turns／sessions，"
                   "聚合前后对当前空间 shared_json 做完全相等校验；"
                   "前端不得指定池、成员、身份与空间字段。"
                   "PC014 自动匹配加载、PC015 共建空间与全部数据红线不变",
        "owner": "政教处＋教务处＋信息化处",
        "status": "已确认（2026-11-12 设计口径）",
    },
    {
        "id": "PC017",
        "topic": "教师端 → 班主任端协同教育推送：平时考试／学习状态自动推送到所代课程班级（用户 2026-11-12 口径）",
        "detail": "用户明确：以上思路保存；教师对学生的平时考试、学习状态可以自动推送到所代课程班级的"
                  "班主任，便于班主任统筹学生成长；他们在关系上不存在隶属管理，但存在协同教育学生关系。"
                  "这是教师端与班主任端之间的横向协同教育通道，不是上下级、不是三端打通、不是共享上下文，"
                  "也不属于 PC016 同类池（跨端跨类角色）。",
        "current": "已按 COEDU_RULE／COEDU_RELATION_NOTE／COEDU_LINK_NOTE／COEDU_ISOLATION／COEDU_NOTE 固化："
                   "新增 app/coedu.py、coedu_links（任课绑定，PC010 待教务处补录，样本内置演示绑定）"
                   "与 coedu_pushes（定向推送留痕）表，以及 /api/v1/coedu/view｜links｜preview｜push｜inbox 接口；"
                   "服务端按教师 post_id → 所代课程班级 → 该班班主任端 L1 职务自动定向投递，"
                   "只推班级级脱敏派生区汇总＋需关注人数＋建议动作，不出学生名单、分数／排名、"
                   "家长电话／请假事由／身份证、自由文本与对话原文；成绩／考试域未接入派生区时按既有红线"
                   "降级为暂不可用、不编造分数或旧值；不写 spaces／space_events／chat_turns／sessions，"
                   "推送前后对 shared_json 做完全相等校验；前端不得指定收件人、班级与身份字段。"
                   "不进六级行政链、不参与逐级推送与催办、不纳入考核与留痕；PC010 仍待教务处补录",
        "owner": "教务处＋政教处＋信息化处",
        "status": "已确认（2026-11-12 设计口径）",
    },
]
