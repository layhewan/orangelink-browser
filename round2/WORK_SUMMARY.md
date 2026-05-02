# 脐橙浏览器（Orangelink Browser）工作总结

## 项目概述

基于 Chromium 的便携式多配置浏览器，支持 SOCKS5/HTTP/HTTPS 代理、浏览器指纹伪装、时区/语言自动匹配。用户通过 PySide6 图形界面管理多个浏览器环境，每个环境可独立配置代理、指纹、时区。

---

## 一、总体工作思路

**问题驱动 + 分层修复：**

整个开发过程围绕真实使用场景中遇到的问题展开，按层次递进修复：

1. **网络层** — 确保代理通信正确，地理探测准确
2. **指纹层** — 确保浏览器特征与代理出口一致，不被检测
3. **UI 层** — 确保操作流畅、直观、反馈充分
4. **打包层** — 确保分发产物可直接运行，无外部依赖

每次修改先定位根因，再针对性修复，最后验证测试。

---

## 二、详细工作内容

### 1. 网络后端：地理探测（Geo Probe）重写

#### 问题
浏览器指纹网站的时区检测不匹配：`browserscan.org` 检测到 IP 时区与浏览器时区不一致。

#### 根因
- 原有探测只单一依赖 `ip-api.com`，且通过代理直连 geo 供应商
- Clash 代理的域名路由规则将 geo 供应商流量导向 Cloudflare 边缘节点，获取到错误的出口 IP
- 不同 geo 数据库（ip-api 与 MaxMind）对同一 IP 的归属地判定不一致

#### 解决
**两级探测架构：**
1. 通过代理访问 `httpbin.org/ip` 获取真实出口 IP
2. 用该 IP 直连（不经过代理）查询多个 geo 供应商

**多供应商支持：**
- 支持 `ip-api.com`、`ipapi.co`、`ipwho.is`、`ipinfo.io`
- 一级探测使用 IP 直查路径，支持 HTTPS
- 二级回退走代理路由

**HTTP 响应解析：**
- 原始实现简单分割 `\r\n\r\n` 提取 body
- 重写为支持 `Content-Length` 头的正确解析
- 直连使用 `urllib` 替代原始 socket（支持 HTTPS 重定向）

**动态国家-语言映射：**
- 从硬编码 11 个国家扩展到 150+ 国家
- 自动合成 `zh-HK`、`nl-NL` 等 BCP 47 语言标签
- 未知国家码动态尝试派生语言标签

### 2. 浏览器指纹伪装增强

#### 问题
`browserscan.org` 检测出 `Language mismatch`（网页语言与系统语言不匹配）和 `Timezone mismatch`。

#### 根因
- 指纹脚本覆盖不够全面，缺少 `navigator.webdriver`、`chrome.runtime` 等属性
- `Intl` 构造器修补不完整，导致 `Intl.Locale` 等泄露真实语言
- 时区空值时仍然设置 `Emulation.setTimezoneOverride("UTC")`，产生人为痕迹

#### 解决
**增强的 JavaScript 注入脚本：**
- 覆盖 `navigator.webdriver = false` 隐藏自动化标记
- 清理 `window.cdc_*` Chromium 自动化痕迹属性
- 覆盖 `chrome.runtime` API（`onInstalled`、`onStartup`）
- 覆盖 `screen` 属性（分辨率、色深）
- 拦截 `navigator.permissions.query` 隐藏推送通知权限

**完整的 Intl 修补：**
- 从修补 7 个 `Intl` 构造器扩展到 11 个（含 `DisplayNames`、`DurationFormat`、`Locale`）
- 使用 `WeakSet` 跟踪默认语言实例，确保 `resolvedOptions()` 返回正确的语言标签

**时区策略优化：**
- 当无法获取有效时区时（空值或 `"UTC"`），跳过 `Emulation.setTimezoneOverride`
- 避免人为设置 UTC 暴露自动化特征

**语言头优化：**
- `--accept-lang` 和 CDP `acceptLanguage` 不再附加 `;q=0.9`，让 Chrome 内部自动处理

### 3. GUI 界面重设计

#### 问题
原始界面暗黑风格配色不佳，按钮无交互反馈，操作卡顿。

#### 解决
**配色方案（三版迭代）：**

| 版本 | 主题 | 结果 |
|------|------|------|
| v1 | iOS 蓝白扁平风格 | 用户反馈文字可读性差 |
| v2 | 浅绿/草绿 + 白色 | 确认通过，但按钮按下无反馈 |
| v3 | v2 + 所有按钮按下状态 | 最终确认 |

**交互改进：**
- 所有按钮增加 `:pressed` 和 `:disabled` 伪类样式
- 删除操作增加 `QMessageBox` 确认弹窗
- 运行中配置无法删除时弹出警告对话框
- 已保存配置支持双击直接启动

**性能优化：**
- 浏览器启动从同步阻塞改为后台线程 + `QTimer` 轮询
- 保存配置也从后台线程执行 geo 探测
- 快速代理可用性检测（1s 超时），不可达时跳过探测
- 点击启动后界面立即响应，不再卡顿

### 4. 打包与分发

#### 问题
- 打包后的 exe 图标系统默认图标
- 内置 Chromium 为 Chrome for Testing，有警告提示
- 硬编码系统 Chrome 绝对路径，无法跨机器

#### 解决
**自动获取正式版 Chrome：**
- 构建脚本自动检测 `C:\Program Files\Google\Chrome\Application`
- 复制到 `chrome-win64/` 覆盖 Chrome for Testing
- Python 代码只使用相对路径，不写死系统路径

**图标修复：**
- `PyInstaller --icon` 嵌入到 exe
- 运行时从打包的 `app/assets/favicon.ico` 加载
- `SetCurrentProcessExplicitAppUserModelID` 确保任务栏图标正确

**构建脚本改进：**
- 添加文件锁定重试机制（解决 Windows Defender 扫描导致的构建失败）
- 隐藏子进程窗口（`CREATE_NO_WINDOW`）
- 启动时清理 Chromium 单例锁文件

---

## 三、关键技术决策

### 1. QThread vs threading.Thread + QTimer
- **QThread + Signal 方案：** 测试无法通过（offline 模式无事件循环）
- **threading.Thread + join 检测：** 主线程 `join(0.01)` 快速检测，非阻塞下用 `QTimer` 轮询
- 最终选择了后者，兼容测试和运行双模式

### 2. 代理探测超时策略
- 短超时（1s）预检测，避免长时间 socket 等待
- 有 mock 时（测试）跳过检测，直接返回
- 生产环境下 `geo_probe is None` 才执行完整检测

### 3. 二级地理探测 vs 直接代理探测
- 直接代理探测容易被 Clash 等代理工具的域名路由干扰
- 先获取出口 IP，再直连查询，避免中间人干扰
- 回退路径保留原始代理探测确保容错

---

## 四、遗留问题与注意事项

### 1. Geo 数据库不一致
`browserscan.org`（MaxMind）与 `ip-api.com` 等免费供应商对同一 IP 的归属地判定可能不一致。代码层面无法解决，用户可手动设置时区。

### 2. 构建环境 Windows Defender 干扰
构建脚本的 `robocopy` / `Copy-Item` 阶段经常因 Defender 扫描而失败。
**当前变通方案：** 手动复制（`xcopy /E /I /Y`）+ `Start-Sleep` 等待。

### 3. 测试环境
所有测试在 `QT_QPA_PLATFORM=offscreen` 模式下运行，无事件循环。异步代码需兼容同步模式。

### 4. Chrome 版本更新
构建时会自动复制系统 Chrome，若系统 Chrome 版本更新需重新打包。

---

## 五、项目结构说明

```
round2/
├── app/
│   ├── assets/
│   │   └── favicon.ico          # 应用程序图标
│   ├── desktop/
│   │   ├── main.py              # 桌面入口，AppUserModelID
│   │   ├── models.py            # LaunchConfigForm 表单模型
│   │   ├── state_store.py       # 配置持久化存储
│   │   └── window.py            # 主窗口 UI + 事件处理
│   └── runtime/
│       ├── chromium_launcher.py # Chromium 启动参数构建
│       ├── config.py            # LaunchConfig 数据模型
│       ├── fingerprint.py       # 浏览器指纹注入脚本
│       ├── fingerprint_controller.py
│       ├── proxy_geo.py         # 地理探测（二级探测）
│       └── profiles.py          # 配置文件管理
├── relay/
│   └── src/main.rs              # Rust 代理转发（SOCKS5 → HTTP CONNECT）
├── scripts/
│   ├── build_portable.ps1       # 便携版打包脚本
│   └── desktop_gui.py           # GUI 入口脚本
├── tests/                       # pytest 测试
│   ├── desktop/
│   └── runtime/
├── pyproject.toml
└── WORK_SUMMARY.md              # 本文件
```

---

## 六、关键命令

```bash
# 运行测试
pytest tests/ -q

# 构建打包
./scripts/build_portable.ps1 -OutputDir final_v3 -SkipVerification

# 直接 PyInstaller 构建
python -m PyInstaller --clean --noconfirm `
    --distpath build/pyinstaller-dist `
    --workpath build/pyinstaller `
    --specpath build/pyinstaller-spec `
    --add-data "D:\path\to\app;app" `
    --icon "D:\path\to\app\assets\favicon.ico" `
    --name orangelink-browser --onedir --windowed `
    scripts/desktop_gui.py
```
