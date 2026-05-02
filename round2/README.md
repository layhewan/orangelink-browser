# 脐橙浏览器（Orangelink Browser）

一个基于 Chromium/Chrome 的便携式多配置浏览器环境管理器。

## 功能

- **多环境管理** — 保存多个浏览器配置（代理、指纹、时区、语言），独立启动
- **代理支持** — HTTP/HTTPS/SOCKS5，自动地理探测（时区+语言同步）
- **指纹伪装** — 隐藏 `webdriver`、自动化标记、修补 `Intl API`，减少指纹检测特征
- **便携打包** — 使用 PyInstaller 打包为单目录，携带正式版 Chrome
- **GUI 界面** — PySide6 桌面界面，双击即启动，实时查看运行状态

## 环境要求

- Windows 10/11
- Python >= 3.10
- 系统中已安装 Google Chrome（构建时自动获取）

## 快速开始

```powershell
# 安装依赖
pip install PySide6

# 运行 GUI（开发模式）
python scripts/desktop_gui.py

# 运行测试
python -m pytest tests/ -q
```

## 便携版打包

构建脚本会自动检测系统 Chrome 并打包到输出目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_portable.ps1 -OutputDir my_build
```

脚本会完成以下操作：
1. 编译 Rust 代理转发（proxy-relay）
2. 从 `C:\Program Files\Google\Chrome\Application` 复制正式版 Chrome
3. 运行 PyInstaller 打包 Python 代码
4. 组装最终目录结构

## 项目结构

```
round2/
├── app/
│   ├── assets/favicon.ico       # 程序图标
│   ├── desktop/                 # PySide6 GUI
│   │   ├── main.py              # 入口
│   │   ├── window.py            # 主窗口（UI + 事件）
│   │   ├── models.py            # 表单模型
│   │   └── state_store.py       # 配置持久化
│   └── runtime/                 # 运行时
│       ├── chromium_launcher.py # Chrome 启动
│       ├── fingerprint.py       # 指纹注入脚本
│       ├── proxy_geo.py         # 两级地理探测
│       └── config.py            # 配置模型
├── relay/src/main.rs            # Rust 代理转发
├── scripts/
│   ├── build_portable.ps1       # 打包脚本
│   └── desktop_gui.py           # GUI 入口
├── tests/                       # pytest 测试
├── pyproject.toml
└── WORK_SUMMARY.md              # 开发总结
```

## License

MIT
