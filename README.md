# 脐橙浏览器

一个基于 Python 的桌面浏览器控制台，支持代理配置、指纹参数同步、会话批量启动与内置 Chromium 内核便携分发。

## 功能概览

- 多会话启动与停止管理
- 代理配置（http/https/socks5）
- 自动指纹参数同步（语言/时区）
- 本地 GUI + API 服务
- 便携版打包（PyInstaller + Chromium 内核）

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

## GitHub 上传前建议

- 不要提交 `.venv/`、`.playwright/`、`dist/`、`build/`、`final_exe/`
- 保留 `pyproject.toml`、`uv.lock`、`.python-version` 用于复现环境

## License

暂未指定（上传仓库时请补充 `LICENSE`）。
