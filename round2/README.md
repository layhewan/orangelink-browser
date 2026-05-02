<div align="center">
  <img src="app/assets/favicon.ico" alt="Orangelink Browser Icon" width="96" />
  <h1>脐橙浏览器 / Orangelink Browser</h1>
</div>

---

> **免责声明 / Disclaimer**
>
> 本软件按「原样」提供，不附带任何明示或暗示的保证。使用者应自行承担使用风险。开发者不对因使用本软件而产生的任何直接或间接损失负责。本软件仅供合法用途，使用者须遵守所在地法律法规。
>
> This software is provided "as is", without warranty of any kind. Users assume all risks. The developers shall not be held liable for any damages arising from its use. This software is intended for lawful purposes only. Users must comply with all applicable laws.

---

## 中文

### 简介

多配置浏览器环境管理器，支持代理自动地理探测、浏览器指纹伪装、多会话独立管理。基于 Chromium/Chrome 内核，可便携打包。

### 功能

- **多环境管理** — 保存多个浏览器配置（代理、指纹、时区、语言），独立启动
- **代理支持** — HTTP/HTTPS/SOCKS5，出口 IP 自动探测时区与语言
- **指纹伪装** — 隐藏 `webdriver`、自动化标记、修补 `Intl API`，降低指纹检测率
- **便携打包** — 携带正式版 Chrome，下载即用
- **桌面 GUI** — PySide6 界面，双击启动配置，实时查看运行状态

### 快速开始

```powershell
# 安装依赖
pip install PySide6

# 运行 GUI（开发模式）
python scripts/desktop_gui.py
```

### 运行测试

```powershell
python -m pytest tests/ -q
```

### 便携版打包

```powershell
# 自动检测系统 Chrome 并打包
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_portable.ps1 -OutputDir my_build
```

### 项目结构

```
app/                          # Python 源代码
  assets/favicon.ico          # 图标
  desktop/                    # PySide6 GUI
  runtime/                    # 运行时（启动器、指纹、探测）
scripts/                      # 构建/运行脚本
relay/src/main.rs             # Rust 代理转发
tests/                        # pytest 测试
```

### 许可证

MIT

---

## English

### Overview

A multi-profile browser environment manager with automatic proxy geo-detection, browser fingerprint evasion, and independent session management. Built on Chromium/Chrome, packaged as a portable distribution.

### Features

- **Multi-profile management** — Save and launch multiple browser configurations independently
- **Proxy support** — HTTP/HTTPS/SOCKS5 with automatic timezone and language detection from egress IP
- **Fingerprint evasion** — Hides `webdriver`, automation traces, patches `Intl API` to reduce fingerprint detection rate
- **Portable packaging** — Bundles official Chrome, ready to run after extraction
- **Desktop GUI** — PySide6 interface, double-click to launch, real-time session monitoring

### Quick Start

```powershell
# Install dependencies
pip install PySide6

# Launch GUI (development mode)
python scripts/desktop_gui.py
```

### Run Tests

```powershell
python -m pytest tests/ -q
```

### Build Portable Package

```powershell
# Auto-detects system Chrome and packages everything
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_portable.ps1 -OutputDir my_build
```

### Project Structure

```
app/                          # Python source code
  assets/favicon.ico          # Application icon
  desktop/                    # PySide6 GUI
  runtime/                    # Runtime (launcher, fingerprint, geo probe)
scripts/                      # Build/run scripts
relay/src/main.rs             # Rust proxy relay
tests/                        # pytest test suite
```

### License

MIT
