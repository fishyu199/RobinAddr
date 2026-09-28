# Architecture

RobinCop 采用单项目、多服务结构。核心计算只有一份实现，由命令行、API 和后台任务共同调用。

## 组件

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 计算引擎 | `copybot/` | GMGN 数据标准化、现货跟单回测、统计、评分和 Telegram 报告 |
| 命令行入口 | `run_robinhood.py` | 获取单个钱包数据并调用计算引擎 |
| API | `apps/api/robincop_api/` | 公共及管理接口、数据库读写、计算任务编排 |
| Worker | `apps/worker/` | 运行 Celery 分析、采集和定时任务 |
| 网站 | `apps/web/app/` | 排行榜和钱包详情 |
| 管理后台 | `apps/web/app/admin/` | 候选钱包、任务、采集和系统设置管理 |

## 数据流

```text
GMGN
  │
  ▼
发现任务 ──► 候选钱包 ──► Celery 分析任务
                              │
                              ▼
                  run_robinhood.py
                              │
                              ▼
                         copybot 引擎
                              │
                              ▼
                         PostgreSQL
                          │       │
                  公共 API       管理 API
                          │       │
                          ▼       ▼
                       网站     管理后台
```

Redis 同时作为 Celery broker、结果后端和计算并发槽位存储。Celery Beat 定期检查采集和重新分析任务是否到期。

## 依赖方向

允许的主要依赖方向为：

```text
web ──HTTP──► api ──► run_robinhood ──► copybot
                    └─► database
worker ─────────────► api tasks
```

`copybot/` 不应导入 `apps/` 下的模块。计算规则修改后，应先补充或更新 `tests/`，再由 API 和页面消费新的输出字段。

## 运行单元

本地 `docker-compose.yml` 启动：

- PostgreSQL：持久化候选钱包、公开钱包、运行记录和设置；
- Redis：任务队列与并发控制；
- API：FastAPI 服务并自动执行 Alembic migration；
- Worker：执行分析和发现任务；
- Scheduler：运行周期性任务；
- Web：公开页面及管理后台。

服务器配置位于 `deploy/docker-compose.server.yml`，将分析、串行分析和采集拆成不同队列，以便独立控制并发。

## 生成内容

以下目录或文件不属于手写源码：

- `.cache/`：GMGN 请求缓存；
- `reports/`：本地生成的分析报告；
- `run_robinhood_standalone.py`：由 `build_standalone.py` 生成的分发文件；
- `apps/web/node_modules/`：Node.js 依赖；
- `apps/web/.next/`、`.vinext/`、`dist/`、`.wrangler/`：网站构建和部署产物；
- `__pycache__/`、`.pytest_cache/`：Python 缓存。

