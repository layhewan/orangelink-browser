from __future__ import annotations


MINIMUM_WINDOW_SIZE = (980, 680)
USES_SCROLL_AREA = True

MAIN_WINDOW_SECTIONS = (
    "configuration_editor",
    "launch_current_form",
    "saved_configurations",
    "running_sessions",
    "session_controls",
    "diagnostic_log",
    "portable_data_warning",
)

VISIBLE_CONTROL_KEYS = (
    "window_title",
    "configuration_editor",
    "config_name",
    "proxy_enabled",
    "proxy_protocol",
    "proxy_host",
    "proxy_port",
    "start_page",
    "language_mode",
    "timezone_mode",
    "os_fingerprint",
    "extension_support",
    "launch_current_form",
    "save_config",
    "saved_configurations",
    "running_sessions",
    "stop_selected",
    "stop_all",
    "diagnostic_log",
    "portable_data_warning",
)

ZH_UI_STRINGS = {
    "window_title": "脐橙浏览器",
    "configuration_editor": "配置编辑",
    "config_name": "配置名称",
    "proxy_enabled": "启用代理",
    "proxy_protocol": "代理协议",
    "proxy_host": "代理主机",
    "proxy_port": "代理端口",
    "start_page": "启动页面",
    "language_mode": "语言设置",
    "timezone_mode": "时区设置",
    "os_fingerprint": "系统指纹",
    "extension_support": "扩展支持",
    "launch_current_form": "启动当前配置",
    "save_config": "保存配置",
    "saved_configurations": "已保存配置",
    "running_sessions": "运行中的会话",
    "stop_selected": "停止选中会话",
    "stop_all": "停止全部会话",
    "diagnostic_log": "诊断日志",
    "portable_data_warning": "便携数据未加密，请妥善保管本文件夹。",
}


def create_main_window():
    from PySide6.QtWidgets import QLabel, QMainWindow, QScrollArea, QVBoxLayout, QWidget

    window = QMainWindow()
    window.setWindowTitle(ZH_UI_STRINGS["window_title"])
    window.setMinimumSize(*MINIMUM_WINDOW_SIZE)

    content = QWidget()
    layout = QVBoxLayout(content)
    for section in MAIN_WINDOW_SECTIONS:
        layout.addWidget(QLabel(ZH_UI_STRINGS[section]))

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    window.setCentralWidget(scroll)
    return window
