# RobinCop

RobinCop 是一个 Robinhood Chain 钱包发现与跟单回测项目。它从 GMGN 获取钱包交易，使用确定性规则重放交易并评分，再把合格钱包发布到排行榜和管理后台。

## 项目结构

```text
.
├── copybot/                 核心计算引擎：数据标准化、回测、指标与报告
├── apps/
│   ├── api/                 FastAPI 公共接口、管理接口和数据库模型
│   ├── worker/              Celery worker 镜像入口
│   └── web/                 公开网站和中文管理后台
├── scripts/                 数据快照等辅助脚本
├── tests/                   核心计算单元测试
├── docs/                    技术与架构文档
├── gitbook/                 面向用户的产品文档
├── deploy/                  服务器部署配置
├── run_robinhood.py         单钱包分析命令行入口
├── build_standalone.py      生成单文件分析程序
└── docker-compose.yml       本地完整服务编排
```

详细的组件关系和数据流见 [`docs/architecture.md`](docs/architecture.md)，回测规则见 [`docs/copy-backtest-algorithm.md`](docs/copy-backtest-algorithm.md)。

## 快速开始

1. 创建本地配置：

   ```bash
   cp .env.example .env
   ```

2. 至少设置 `GMGN_API_KEY` 和一个安全的 `ADMIN_API_KEY`。

3. 启动完整服务：

   ```bash
   make up
   ```

公开网站默认位于 <http://localhost:3000>，API 位于 <http://localhost:8000>，管理后台位于 <http://localhost:3000/admin>。

生产环境中，公开站由服务器 `8222` 端口提供，管理后台由带独立登录保护的 HTTPS `8223` 端口提供；`RobinCop.com` 的 80/443 流量反向代理到公开站。

## 常用命令

```bash
make help              # 查看所有项目命令
make test              # 运行 Python 单元测试
make web-build         # 检查网站生产构建
make build-standalone  # 重新生成单文件分析程序
make clean             # 清理缓存和可再生成的构建产物
```

更多本地配置与运行说明见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。

## 代码边界

- `copybot/` 不依赖 Web 或数据库，保持计算结果可复现、可单测。
- `apps/api/` 负责编排计算、持久化结果并提供接口。
- `apps/worker/` 只负责异步执行 API 包中的任务，不重复实现业务逻辑。
- `apps/web/app/admin/` 与公开网站共用前端工程，但通过管理 API 和密钥隔离权限。
- `.cache/`、`reports/` 和网站构建目录都是运行产物，不应作为源码提交。
