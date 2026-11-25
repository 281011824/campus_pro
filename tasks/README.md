# tasks — 业务层（分层模块化单体）

本目录是「班主任工作台与智能体」的**业务逻辑层**，采用业界常见的
**分层模块化单体（Layered Modular Monolith）**：按「共享内核 → 领域 → 角色模块 → 接口」
四层组织，同时保留按角色解耦的垂直模块边界。

> 本层代码取自云端 + 台式机双机**已部署且运行中**的版本，经哈希核验与回归测试
> （Web 层 129 passed，与部署基线完全一致、零回归）确认有效。

## 分层与依赖方向

```
interfaces  ──▶  modules  ──▶  domain  ──▶  shared
   ↑ 入口          ↑ 角色         ↑ 规则        ↑ 基础设施
```

依赖只能**自上而下单向**，禁止反向：

| 层 | 职责 | 允许依赖 |
|----|------|----------|
| `interfaces/` | 进程与协议入口：业务路由分发、Redis 线协议契约、后台 worker | modules / domain / shared |
| `modules/` | 角色专属业务功能，每角色一个包，彼此不互相依赖 | domain / shared |
| `domain/` | 业务实体、口径常量与领域规则，与框架无关 | shared |
| `shared/` | 配置、SQLite 连接、加解密、企业微信适配等基础设施 | —（仅标准库 / 第三方）|

## 角色定义与模块归属

| 角色包 | 角色 | 状态 | 包含模块 |
|--------|------|------|----------|
| `modules/head_teacher/` | 班主任空间 | ✅ 已实现并部署 | roster, seating, moral_criteria, moral_issues, redpoint, secretary, push, coedu, assistant, writes, exports/{seating_excel, seating_pdf} |
| `modules/supervisor/` | 教官寝管空间 | ✅ 已实现并部署 | dorms, inspection |
| `modules/student/` | 学生空间 | ✅ 已实现并部署 | student_portal, student_accounts |
| `modules/leader/` | 校领导空间 | ✅ 已实现并部署 | admins |
| `modules/subject_teacher/` | 任课老师空间 | ⏳ 预留占位 | （当前部署版本未实现）|

## 目录结构

```
tasks/
├── shared/                        # 共享基础层（无业务语义）
│   ├── config.py                  #   配置：环境变量 > .env > 默认值
│   ├── db.py                      #   SQLite 连接 / 建表 / 迁移
│   ├── crypto.py                  #   企微消息加解密
│   └── wecom.py                   #   企业微信 API 适配
│
├── domain/                        # 领域层
│   ├── models.py                  #   统一业务语言：端口 / 口径 / 红线 / 白名单常量
│   ├── identity/                  #   身份与组织子域
│   │   ├── org.py                 #     组织架构（学校 / 年级 / 班级 / 人员 / 职务）
│   │   ├── accounts.py            #     工作账号
│   │   ├── classes.py             #     班级字典
│   │   ├── bindings.py            #     账号-组织绑定
│   │   └── access.py              #     班级数据访问范围
│   ├── growth/                    #   学生成长子域
│   │   ├── growth.py              #     成长导航只读派生区
│   │   ├── growth_archive.py      #     成长档案（五维记录）
│   │   └── datadomains.py         #     十四个数据域采集与聚合
│   └── collaboration/             #   协同子域
│       ├── space.py               #     共建空间 / 共享上下文
│       └── federation.py          #     同类横向协同
│
├── modules/                       # 角色垂直模块
│   ├── head_teacher/              #   班主任空间
│   │   ├── roster.py              #     花名册
│   │   ├── seating.py             #     座位表
│   │   ├── moral_criteria.py      #     德育评分标准
│   │   ├── moral_issues.py        #     德育问题记录
│   │   ├── redpoint.py            #     红点 / 待确认事项
│   │   ├── secretary.py           #     岗位秘书智能体引擎
│   │   ├── push.py                #     六级自动推送与催办
│   │   ├── coedu.py               #     协同教育（教师端 → 班主任端）
│   │   ├── assistant.py           #     班主任小秘书（重点学生 / 科任反馈）
│   │   ├── writes.py              #     两段式写入与人审归档
│   │   └── exports/               #     导出适配器（Excel / PDF）
│   ├── supervisor/                #   教官寝管：dorms, inspection
│   ├── student/                   #   学生：student_portal, student_accounts
│   ├── leader/                    #   校领导：admins
│   └── subject_teacher/           #   任课老师（预留）
│
├── interfaces/                    # 接口层
│   ├── server.py                  #   业务路由分发（60+ 固定路由 + 动态分支）
│   ├── contract.py                #   路由清单与 Redis 线协议常量
│   └── worker.py                  #   后台 worker 入口（定时任务 / Redis 队列）
│
├── data/                          # 种子数据（fixtures / scales_seed）
├── scripts/                       # 运维脚本
│   ├── generate_bindings.py       #   生成账号-组织绑定
│   ├── import_accounts.py         #   导入账号
│   ├── seed_demo.py               #   灌入演示数据
│   └── import_student_scales.py   #   导入量表种子
└── tests/                         # 业务层测试
```

## 导入规范

- 一律使用**绝对导入**：
  - `from tasks.shared import db, config`
  - `from tasks.domain.identity import org`
  - `from tasks.modules.head_teacher import roster, seating`
  - `from tasks.interfaces import server, worker`
- 角色模块之间**不直接互相导入**；跨角色共用的能力下沉到 `domain/` 或 `shared/`。
- Web 层 `website/` 按同样路径引用本层。

## 已知的延迟导入

为避免循环依赖，以下两处保留函数内延迟导入（与部署版本行为一致）：

1. `shared/db.py` 在 `init_db()` 末尾调用 `modules/student/student_portal.ensure_schema()`
   完成学生门户建表（建表钩子）。
2. `domain/identity/org.py` 在需要时延迟导入 `domain/collaboration/space`。

新增代码请尽量避免跨层反向导入；确需反向调用时，用函数内延迟导入并在此登记。
