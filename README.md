# Privacy Browser Framework

多进程隐私浏览器框架（Option B supervisor 架构），支持批量启动、多 profile 并发（上限 5）、模板合并、代理复用策略、worker 隔离、快照评分链路与可视化 API/GUI。

## 快速开始

1. 创建并安装环境（已在当前目录完成）：

```powershell
uv venv .venv --python 3.12
uv sync
```

2. 启动应用：

```powershell
uv run pbf-run
```

默认地址：`http://127.0.0.1:8088/`

## 核心能力

- 批次并发上限 `5`
- 失败条目跳过，批次继续
- 模板优先级：`defaults -> template -> profile_overrides`
- 代理复用策略（hybrid）：
  - 默认禁止活跃代理复用
  - 仅 profile `allow_proxy_reuse=true` 时允许复用
- worker 进程隔离与心跳监控
- 本地检测服务 `POST /detection/probe`
- SQLite 持久化：
  - `launch_batches`
  - `batch_items`
  - `profile_templates`
  - `profiles` 扩展
  - `runtime_processes` 扩展
  - `audit_events`
  - `detection_snapshots`

## 代理端口配置

- 默认：`127.0.0.1:7897`
- 支持切换任意合法端口（`1..65535`）
- Proxy 契约见 `app/core/schemas.py::ProxyConfigContract`
- 运行时时区策略：
  - worker 默认开启 `auto_timezone=true`
  - 会按当前 `proxy_server` 自动探测 IP 时区并缓存
  - 可通过 runtime 配置覆盖：
    - `timezone_id`
    - `auto_timezone`
    - `timezone_probe_url`
    - `timezone_probe_timeout_ms`

## BrowserScan 验收脚本

使用项目内核浏览器执行 BrowserScan 检查：

```powershell
uv run python scripts/browserscan_check.py --min-score 95 --proxy-port 7897 --auto-timezone --wait-ms 15000
```

示例：切换端口验证

```powershell
uv run python scripts/browserscan_check.py --proxy-port 10808 --auto-timezone --wait-ms 15000
uv run python scripts/browserscan_check.py --proxy-scheme socks5 --proxy-port 1080 --auto-timezone --wait-ms 15000
```

说明：BrowserScan 的最终分数与代理出口 DNS 策略强相关。浏览器侧参数会尽量抑制 DNS/WebRTC 泄漏，但不同代理软件/节点仍可能出现不同分数。

## 测试与检查

```powershell
uv run ruff check app tests
uv run pytest -q
```
