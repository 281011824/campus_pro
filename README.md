# campus_pro · 班主任工作台与智能体

> 京山市中等职业技术学校 · 班主任工作台与智能体系统
> FastAPI + SQLite + 原生 JS（零前端构建）· 多角色一体化平台
>
> 项目代号：**campus_pro**（GitHub: `281011824/campus_pro`）

## 🚀 当前部署（campus_pro）

| 项 | 云端 | 台式机（业务主库） |
|----|------|--------------------|
| 部署目录 | `/opt/campus_pro` | `/opt/campus_pro` |
| 应用进程 | `127.0.0.1:5005`（systemd `campus-website`）| `10.66.0.4:5005`（`bin/start.sh` 常驻）|
| Redis | `127.0.0.1:6381`（`campus-redis`）| `127.0.0.1:6381` |
| Worker | `campus-worker`（`-m tasks.interfaces.worker`）| `bin/start.sh` 托管 |
| 数据库 | `/opt/campus_pro/runtime/dywork.db` | `/opt/campus_pro/runtime/dywork.db` |
| 访问入口 | `http://124.221.26.96:19003`（nginx → 台式机主 / 云端备）| — |

> 原有 `/opt/school_pro`（`htw-*` 服务、19002 入口）保持运行，互不影响；
> 新栈使用独立端口（5005 / 6381 / 19003）与独立数据库副本。
>
> 云端 19003 需在云控制台安全组放行后才能从公网访问。

## ✅ 代码有效性声明

本仓库（`pro/`）中的全部业务代码取自**云端与台式机两台服务器上已部署且正在运行**的版本，
并经过以下核验，确保不是本地开发草稿的简单复制：

| 核验项 | 结果 |
|--------|------|
| 云端 `root@124.221.26.96:/opt/school_pro` 部署文件 | 152 个源文件 |
| 台式机 `fc@10.66.0.4:/opt/school_pro` 部署文件 | 152 个，与云端**完全一致**（零差异）|
| 本地 vs 云端 SHA-256 哈希比对 | 143 个完全一致；6 个本地缺失、3 个内容不一致 → **均已从服务器拉取覆盖**，最终 152/152 哈希全部匹配 |
| 角色拆分后回归测试 | `pytest` **129 passed / 5 failed / 1 skipped**，与部署基线完全一致，**零回归** |
| 分层重构后回归测试 | 同上 **129 / 5 / 1**，路由仍为 **254** 条，零回归 |
| 应用导入冒烟 | `app.main` 正常加载，注册 **254 条路由** |

> 5 个预存失败为部署代码本身与历史测试用例的差异（数据列、文案），与本次整理无关。

## 目录结构

```
pro/
├── README.md                  ← 本文件
├── .gitignore
├── tasks/                     ← 业务层（分层模块化单体）
│   ├── README.md              ← 分层约定 + 角色模块映射
│   ├── shared/                ← 共享基础层：config / db / crypto / wecom
│   ├── domain/                ← 领域层：models / identity / growth / collaboration
│   ├── modules/               ← 角色垂直模块
│   │   ├── head_teacher/      ←   班主任空间（含 exports/ 导出适配器）
│   │   ├── supervisor/        ←   教官寝管空间
│   │   ├── student/           ←   学生空间
│   │   ├── leader/            ←   校领导空间
│   │   └── subject_teacher/   ←   任课老师空间（预留）
│   ├── interfaces/            ← 接口层：server（业务路由分发）/ contract / worker
│   ├── data/                  ← 种子数据（fixtures / scales_seed）
│   ├── scripts/               ← 运维脚本（绑定生成 / 账号导入 / 演示数据 / 量表导入）
│   └── tests/                 ← 业务层测试
│
├── website/                   ← Web 网络服务层（FastAPI 单体）
│   ├── app/
│   │   ├── main.py            ← 应用入口，lifespan 中初始化 DB + 业务模块
│   │   ├── api/v1/            ← REST API（按角色分文件）
│   │   ├── services/          ← 各角色鉴权与服务
│   │   ├── middleware/        ← CORS / 异常 / HTTP 日志
│   │   ├── templates/         ← Jinja2 页面（按角色分目录）
│   │   └── static/            ← 静态资源（原生 JS/CSS，无构建）
│   ├── config/                ← app_dev / app_prod / app_test 配置 + .env.example
│   ├── tests/                 ← Web 层测试
│   ├── requirements.txt
│   ├── runserver.py
│   └── README.md
│
├── deploy/                    ← 部署配置
│   ├── htw.env.example        ← 环境变量模板
│   ├── systemd/               ← systemd 服务（website / worker / redis）
│   └── nginx/htw.conf         ← Nginx 反向代理
│
├── tools/                     ← 运维工具（db_audit / db_sync）
└── docs/                      ← 需求 / 设计 / 进度文档与截图
```

## 架构说明

当前为**单体模式**：`website` 进程直接 `import tasks.*` 业务模块，在同一进程内
完成请求处理与业务逻辑（`website/app/main.py` lifespan 初始化）。`tasks/interfaces/worker.py`
为独立后台进程，处理定时任务与可选的 Redis 队列，通过 `tasks/interfaces/contract.py`
与 Web 层约定数据契约。

`tasks` 内部采用**分层模块化单体**：依赖方向严格单向
`interfaces → modules → domain → shared`。

```
                ┌──────────────────────────────────┐
  浏览器/企微 ──▶│  website  (FastAPI, 单进程单体)    │
                │  api/v1/*  ·  templates  · static │
                └───────────────┬──────────────────┘
                                │ import
                ┌───────────────▼──────────────────┐
                │  tasks/interfaces  路由/契约/worker │
                ├──────────────────────────────────┤
                │  tasks/modules     5 个角色模块     │
                ├──────────────────────────────────┤
                │  tasks/domain      领域规则         │
                ├──────────────────────────────────┤
                │  tasks/shared      配置/DB/企微      │
                └───────────────┬──────────────────┘
                                │ SQLite
                        tasks/runtime/dywork.db
```

## 角色与入口

| 角色 | Web 入口 | 页面模板 | tasks 模块归属 |
|------|----------|----------|----------------|
| 管理员 | `/api/admin` | `templates/admin/` | `modules/leader` + `domain/identity` |
| 政教处 | `/api/deyu` | `templates/deyu/` | `domain/*`（德育口径）|
| 班主任 | `/api/head_teacher_workbench` | `templates/head_teacher_workbench/` | `modules/head_teacher` |
| 教官寝管 | `/api/inspector` | `templates/inspector/` | `modules/supervisor` |
| 学生 | `/api/student` | `templates/student/` | `modules/student` |
| 家长 | `/api/family`（分享链接）| `templates/student/share_view.html` | `modules/student` |

## 本地运行

```bash
# 1. 进入 Web 层
cd pro/website

# 2. （推荐）创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量（复制模板后按需修改）
cp config/.env.example config/.env
# 关键变量：APP_ENV=dev / test / prod；DB_PATH；REDIS_URL；企微相关密钥

# 5. 启动（首次启动自动建表）
APP_ENV=dev python runserver.py
# 或：uvicorn app.main:app --reload --port 8000
```

- `website/app/__init__.py` 会自动把**项目根目录**（`website/` 的上一级）加入
  `sys.path`，因此 `tasks` 与 `website` 须保持**兄弟目录**关系（即本仓库结构）。
- 数据库文件默认位于 `tasks/runtime/dywork.db`，首次访问自动建表（幂等）。

## 测试

```bash
cd pro/website
APP_ENV=test DB_PATH=/tmp/test.db python -m pytest tests -q
```

- Web 层测试：`website/tests/`
- 业务层测试：`tasks/tests/`（在仓库根执行：`PYTHONPATH=. python -m pytest tasks/tests -q`）
- 当前回归基线：Web 层 129 passed / 5 failed / 1 skipped（5 个为预存历史差异）；
  业务层 14 passed / 3 failed / 7 skipped（3 个失败在分层重构前的同一命令下同样失败）。

## 部署

双机部署（云端 + 台式机），部署目录 `/opt/school_pro/`：

```
/opt/school_pro/
├── tasks/    ← 对应本仓库 pro/tasks
├── website/  ← 对应本仓库 pro/website
├── tools/    ← 对应本仓库 pro/tools
├── runtime/  ← SQLite 数据库（运行时生成，不入 git）
├── logs/     ← 日志（运行时生成，不入 git）
└── htw.env   ← 环境变量（含密钥，不入 git）
```

详细配置见 `deploy/`：
- `deploy/htw.env.example`：环境变量模板
- `deploy/systemd/`：`htw-website` / `htw-worker` / `htw-redis` 服务文件
- `deploy/nginx/htw.conf`：Nginx 反向代理

> 台式机经跳板机访问：`ssh -J root@124.221.26.96 fc@10.66.0.4`

### 升级到分层结构时的数据迁移（重要）

线上旧版本的 SQLite 数据库位于 `tasks/head_teacher_workbench/runtime/dywork.db`，
新结构该目录不再存在。升级前须先迁移数据，否则会以空库启动：

```bash
# 在目标服务器上，停服务后执行
systemctl stop htw-website htw-worker
mkdir -p /opt/school_pro/runtime
mv /opt/school_pro/tasks/head_teacher_workbench/runtime/dywork.db /opt/school_pro/runtime/dywork.db
# 同步修改 /opt/school_pro/htw.env 中的 DB_PATH（见 deploy/htw.env.example）
systemctl daemon-reload && systemctl start htw-website htw-worker
```

worker 的启动模块也已变更：`python -m tasks.worker` → `python -m tasks.interfaces.worker`。
部署时须同步更新 `htw-worker.service`（`deploy/systemd/` 中已更新）。

## 开发流程与规范

1. **变更先写 Spec**：较大改动在 `.trae/specs/<change-id>/` 下写 spec.md 与任务清单，
   明确验收标准后再实施（历史 spec 见开发工作区 `.trae/specs/`）。
2. **分层归位**：新增业务模块先判断所属层——业务规则进 `tasks/domain/`，
   角色专属功能进 `tasks/modules/<角色>/`，进程/传输入口进 `tasks/interfaces/`，
   配置与外部适配进 `tasks/shared/`。依赖方向只能 `interfaces → modules → domain → shared`。
   角色模块之间不直接依赖。
3. **绝对导入**：`from tasks.shared import db`、`from tasks.domain.identity import org`、
   `from tasks.modules.head_teacher import roster`。
4. **回归验证**：改动后必须跑 `pytest`，确保不引入新失败；涉及前端静态资源
   （CSS/JS）改动时须更新 `templates/*/index.html` 中的 `?v=` 缓存破坏版本号。
5. **密钥不入仓**：`.env`、`htw.env`、`*.db`、日志等运行时文件已在 `.gitignore` 排除。

## 技术栈

- **后端**：Python 3.11+ / FastAPI / Uvicorn / Gunicorn
- **数据库**：SQLite（单文件，`tasks/runtime/dywork.db`）
- **缓存/队列**：Redis（可选，worker 与推送用）
- **前端**：Jinja2 模板 + 原生 JavaScript + Bootstrap / jQuery（**无前端构建步骤**）
- **部署**：systemd + Nginx，双机（云端 / 台式机）
