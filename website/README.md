# website · 班主任工作台 Web 层

FastAPI 进程，只做三件事：页面与静态资源、72 条精确路由的 Redis 适配、进程存活信息。

后台业务位于 `../tasks/`（分层模块化单体：`shared` / `domain` / `modules` / `interfaces`），
单体模式下由本进程直接 import 调用，独立 worker 进程走 Redis 队列。

## 结构

```
app/
  main.py                 入口：页面、静态资源、中间件与路由注册
  api/
    default/ping.py       通用探针
    v1/head_teacher_workbench.py   72 条路由 -> Redis 请求
    exceptions.py responses.py status.py
  services/head_teacher_workbench.py   Redis 线协议客户端
  initializer/            配置、日志、Redis 客户端
  middleware/             请求 ID、异常与 CORS
  templates/head_teacher_workbench/index.html
  static/head_teacher_workbench/
config/
  app_dev.yaml app_prod.yaml app_test.yaml
requirements.txt
```

## 运行

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export APP_ENV=dev
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后台 worker 另起一个进程：

```bash
cd .. && python -m tasks.interfaces.worker
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `APP_ENV` | 选择 `config/app_<env>.yaml` |
| `HEAD_TEACHER_WORKBENCH_REDIS_URL` | 队列 Redis，需与 worker 一致 |
| `HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE` | 请求队列名 |
| `HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX` | 响应 key 前缀 |
| `HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS` | Web 等待上限，默认 5s |
| `HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS` | 响应 key 存活，默认 30s |

## 错误语义

| 情况 | 返回 |
| --- | --- |
| Redis 不可用 | 503 `redis_unavailable` |
| worker 超时 | 504 `worker_timeout` |
| 响应损坏或 request_id 不匹配 | 502 `bad_worker_response` |

写请求只投递一次，超时不自动重放。

## 测试

```bash
python -m pytest tests -q
```
