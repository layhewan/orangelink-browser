# 脐橙浏览器

<p align="center">
  <img src="app/assets/favicon.ico" alt="脐橙浏览器 Icon" width="96" />
</p>

一个基于 Python 的桌面浏览器控制台，支持代理配置、指纹参数同步、会话批量启动，以及内置 Chromium 内核的便携分发。

## 功能概览

- 多会话管理：
  - 支持同时启动多个浏览会话，并在桌面端集中查看运行状态、日志和停止控制。
  - 每个会话独立运行，便于批量测试与隔离排查。
- 代理接入能力：
  - 支持 `http`、`https`、`socks5` 三种代理协议。
  - 可按配置快速切换代理主机、端口与启动地址，适配不同网络环境。
- 指纹参数联动：
  - 支持自动同步会话的语言与时区参数，减少手工配置成本。
  - 可按需切换为手动模式，针对特定场景精细控制。
- GUI + API 双入口：
  - 提供桌面 GUI 作为主操作面板，适合日常可视化管理。
  - 同时提供本地 API 服务，便于后续脚本化接入和扩展集成。
- 便携打包分发：
  - 使用 PyInstaller 生成可分发目录，降低环境安装门槛。
  - 打包时可一并携带 Chromium 内核，下载后可直接运行。

## 环境要求

- Windows PowerShell
- Python 3.12（推荐通过 `uv` 管理）
- `uv`（https://docs.astral.sh/uv/）

## 快速开始

```powershell
uv venv .venv --python 3.12
uv sync
uv run pbf-run
```

默认地址：`http://127.0.0.1:8088/`

## 新机器一键克隆环境

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clone_env.ps1
```

仅安装运行时依赖（不含 dev 组）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clone_env.ps1 -AllGroups $false
```

## 便携版打包

1. 安装 Chromium 内核：

```powershell
uv run playwright install chromium
```

2. 执行打包：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

可选参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -AppName "脐橙浏览器" -OutputDir "final_exe"
```

说明：
- 图标默认路径：`app/assets/favicon.ico`
- 输出目录默认：`final_exe`

## 项目结构

```text
app/                    # 应用主代码
  core/                 # 核心配置与契约
  gui/                  # Web GUI
  services/             # 服务层
  supervisor/           # 调度管理
  worker/               # 浏览器执行单元
  assets/               # 静态资源（含图标）
scripts/                # 运行、验证、打包脚本
```

## 常用命令

```powershell
uv run pytest -q
uv run ruff check app tests
```

## License

MIT（见 `LICENSE` 文件）。
