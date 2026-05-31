import ctypes
import ctypes.wintypes
import json
import re
import sys
import threading
import time
from pathlib import Path

import win32con
from PyQt6.QtCore import QObject, QRect, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QKeySequenceEdit,
)

SCREEN_STAT_ORDER = ["生命", "物攻", "魔攻", "物防", "魔防", "速度"]
def resource_path(relative_path):
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).resolve().parent
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / relative_path


def local_data_path(relative_path):
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).resolve().parent
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / relative_path


def load_settings():
    path = local_data_path("data/settings.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings):
    path = local_data_path("data/settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(settings)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def configure_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PetAnalyzer")
    except Exception:
        pass


def is_running_as_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def show_app_warning(parent, title, message):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
    box.setStyleSheet(
        """
        QMessageBox {
            background-color: #202326;
            color: #f4f0e5;
            font-family: "Microsoft YaHei UI";
        }
        QMessageBox QLabel {
            background: transparent;
            color: #f4f0e5;
            font-size: 12px;
        }
        QMessageBox QPushButton {
            background: #24282b;
            border: 1px solid #383d40;
            border-radius: 8px;
            padding: 7px 18px;
            color: #f4f0e5;
            font-weight: 700;
            min-width: 72px;
        }
        QMessageBox QPushButton:hover {
            background: #2c3134;
            border-color: #495054;
        }
        """
    )
    ok_button = box.button(QMessageBox.StandardButton.Ok)
    if ok_button:
        ok_button.setText("确定")
    box.exec()


def load_custom_plans():
    path = local_data_path("data/custom_plans.json")
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_custom_plans(plans):
    path = local_data_path("data/custom_plans.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_plan_text(value):
    text = re.sub(r"\s+", "", str(value or ""))
    for old, new in (("，", "、"), (",", "、"), ("|", "、"), (";", "、"), ("；", "、"), ("／", "/")):
        text = text.replace(old, new)
    text = re.sub(r"、+", "、", text)
    return text.strip("、")


def plan_key(pet, stats, natures):
    return (
        normalize_plan_text(pet),
        normalize_plan_text(stats),
        normalize_plan_text(natures),
    )


def format_stat_groups(groups):
    return "、".join("/".join(group) for group in groups if group)


def display_stat_text(variant):
    text = str(variant.get("statText") or "").strip()
    return text or format_stat_groups(variant.get("statGroups") or [])


def display_nature_text(nature):
    if not nature:
        return "无"
    return f"{nature.get('name', '无')}（+{nature.get('plus', '?')} / -{nature.get('minus', '?')}）"


class EngineLoader(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            from pet_float_app import DATA_PATH, PetData, Recognizer

            pet_data = PetData(DATA_PATH)
            recognizer = Recognizer(pet_data, compute_best_plan=False)
            recognizer.warm_up()
            self.ready.emit((recognizer, pet_data))
        except Exception as error:
            self.failed.emit(str(error))


class RecognitionWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, recognizer):
        super().__init__()
        self.recognizer = recognizer

    def run(self):
        try:
            self.done.emit(self.recognizer.recognize())
        except Exception as error:
            self.failed.emit(str(error))


class HotkeyBridge(QObject):
    hotkey = pyqtSignal()
    failed = pyqtSignal(str)


class HotkeyThread(threading.Thread):
    def __init__(self, modifiers, key, label, bridge):
        super().__init__(daemon=True)
        self.modifiers = modifiers
        self.key = key
        self.label = label
        self.bridge = bridge
        self.stop_event = threading.Event()
        self.error = None

    def run(self):
        user32 = ctypes.windll.user32
        hotkey_id = 43167
        if not user32.RegisterHotKey(None, hotkey_id, self.modifiers, self.key):
            if "+" not in self.label:
                self.error = f"全局快捷键注册失败：{self.label}。单键快捷键需要以管理员身份运行。"
            else:
                self.error = f"全局快捷键注册失败：{self.label}"
            self.bridge.failed.emit(self.error)
            return
        msg = ctypes.wintypes.MSG()
        try:
            while not self.stop_event.is_set():
                result = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if result and msg.message == win32con.WM_HOTKEY and msg.wParam == hotkey_id:
                    self.bridge.hotkey.emit()
                time.sleep(0.03)
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    def stop(self):
        self.stop_event.set()


class BallWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.drag_start = None
        self.moved = False
        self.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(64, 64)
        self.move(80, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.icon = QLabel()
        self.icon.setObjectName("ballIcon")
        self.icon.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(resource_path("assets/app_ball.png")))
        if pixmap.isNull():
            pixmap = QPixmap(str(resource_path("assets/app.png")))
        self.icon.setPixmap(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self.icon)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.moved = False
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_start is None:
            return
        pos = event.globalPosition().toPoint() - self.drag_start
        if (pos - self.pos()).manhattanLength() > 4:
            self.moved = True
        self.move(pos)
        if self.app.panel.isVisible():
            self.app.panel.move(self.x() + 72, max(20, self.y() - 40))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.moved:
            self.app.toggle_panel()
        self.drag_start = None
        event.accept()


class TrayPopup(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Popup
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(226)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.shell = QFrame()
        self.shell.setObjectName("trayMenuShell")
        outer.addWidget(self.shell)

        layout = QVBoxLayout(self.shell)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.show_btn = QPushButton("\u6253\u5f00\u4e3b\u754c\u9762")
        self.show_btn.setObjectName("trayMenuItem")
        self.show_btn.clicked.connect(self.open_main)
        layout.addWidget(self.show_btn)

        self.float_btn = QPushButton("\u542f\u52a8/\u5173\u95ed\u60ac\u6d6e\u7403")
        self.float_btn.setObjectName("trayMenuItem")
        self.float_btn.clicked.connect(self.toggle_float)
        layout.addWidget(self.float_btn)

        separator = QFrame()
        separator.setObjectName("trayMenuSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        self.quit_btn = QPushButton("\u9000\u51fa")
        self.quit_btn.setObjectName("trayMenuItem")
        self.quit_btn.clicked.connect(self.quit_app)
        layout.addWidget(self.quit_btn)

    def show_at_cursor(self):
        self.adjustSize()
        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        bounds = screen.availableGeometry() if screen else None
        width = self.width()
        height = self.height()
        x = pos.x() - width + 8
        y = pos.y() - height - 8
        if bounds:
            x = max(bounds.left() + 6, min(x, bounds.right() - width - 6))
            if y < bounds.top() + 6:
                y = min(pos.y() + 8, bounds.bottom() - height - 6)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def open_main(self):
        self.hide()
        self.app.show_main()

    def toggle_float(self):
        self.hide()
        self.app.toggle_float_ball()

    def quit_app(self):
        self.hide()
        self.app.quit_app()


REGION_STEPS = (
    ("name", "精灵名称", "框选右上角精灵名称文字，不要框选性别、属性图标。"),
    ("trait", "特性", "框选左下角特性文字，不要框选右侧性格文字。"),
    ("nature", "资质列表", "框选完整 6 行资质列表，需同时包含绿色/红色箭头和黄色 + 个体加成。"),
)

REGION_COLORS = {
    "name": QColor("#f2bd4d"),
    "trait": QColor("#20b894"),
    "nature": QColor("#ef6b66"),
}


class RegionCanvas(QWidget):
    def __init__(self, image, max_width, max_height):
        super().__init__()
        self.setObjectName("regionCanvas")
        self.image_h, self.image_w = image.shape[:2]
        self.scale = min(max_width / max(1, self.image_w), max_height / max(1, self.image_h), 1.0)
        self.display_w = max(1, int(self.image_w * self.scale))
        self.display_h = max(1, int(self.image_h * self.scale))
        rgb = image[:, :, ::-1].copy()
        qimage = QImage(rgb.data, self.image_w, self.image_h, self.image_w * 3, QImage.Format.Format_RGB888).copy()
        self.pixmap = QPixmap.fromImage(qimage).scaled(
            self.display_w,
            self.display_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setFixedSize(self.display_w, self.display_h)
        self.step_key = ""
        self.regions = {}
        self.current_rect = QRect()
        self.drag_start = None

    def set_step(self, key, regions):
        self.step_key = key
        self.regions = dict(regions or {})
        self.current_rect = self.rect_from_region(self.regions.get(key))
        self.update()

    def clear_current(self):
        self.current_rect = QRect()
        self.update()

    def rect_from_region(self, region):
        if not region or len(region) != 4:
            return QRect()
        x, y, w, h = [float(value) for value in region]
        return QRect(
            int(round(x * self.display_w)),
            int(round(y * self.display_h)),
            int(round(w * self.display_w)),
            int(round(h * self.display_h)),
        ).normalized()

    def current_region(self):
        rect = self.current_rect.normalized()
        if rect.width() < 6 or rect.height() < 6:
            return None
        return [
            round(rect.left() / self.display_w, 6),
            round(rect.top() / self.display_h, 6),
            round(rect.width() / self.display_w, 6),
            round(rect.height() / self.display_h, 6),
        ]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202326"))
        painter.drawPixmap(0, 0, self.pixmap)
        for key, label, _hint in REGION_STEPS:
            region = self.regions.get(key)
            if not region or key == self.step_key:
                continue
            pen = QPen(REGION_COLORS.get(key, QColor("#f2bd4d")), 2)
            painter.setPen(pen)
            draw_rect = self.rect_from_region(region)
            painter.drawRect(draw_rect)
            painter.drawText(draw_rect.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
        if not self.current_rect.isNull():
            pen = QPen(REGION_COLORS.get(self.step_key, QColor("#f2bd4d")), 3)
            painter.setPen(pen)
            painter.drawRect(self.current_rect.normalized())

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.drag_start = event.position().toPoint()
        self.current_rect = QRect(self.drag_start, self.drag_start)
        self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start is None:
            return
        pos = event.position().toPoint()
        pos.setX(max(0, min(self.display_w - 1, pos.x())))
        pos.setY(max(0, min(self.display_h - 1, pos.y())))
        self.current_rect = QRect(self.drag_start, pos).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None:
            self.mouseMoveEvent(event)
        self.drag_start = None


class RegionCalibrationDialog(QDialog):
    def __init__(self, image, existing_regions=None, parent=None):
        super().__init__(parent)
        self.setObjectName("regionDialog")
        self.setWindowTitle("框选识别位置")
        self.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.image_h, self.image_w = image.shape[:2]
        self.resolution_key = f"{self.image_w}x{self.image_h}"
        self.regions = dict(existing_regions or {})
        self.step_index = 0

        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        max_width = min(1120, (available.width() - 120) if available else 1120)
        max_height = min(680, (available.height() - 190) if available else 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)

        self.canvas = RegionCanvas(image, max_width, max_height)
        layout.addWidget(self.canvas)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.reset_btn = QPushButton("重选当前")
        self.reset_btn.clicked.connect(self.reset_current)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        self.next_btn = QPushButton("下一项")
        self.next_btn.clicked.connect(self.accept_step)
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.next_btn)
        layout.addLayout(buttons)
        self.refresh_step()

    def refresh_step(self):
        key, label, hint = REGION_STEPS[self.step_index]
        self.title.setText(f"{self.resolution_key}｜{self.step_index + 1}/{len(REGION_STEPS)}：{label}")
        self.hint.setText(hint)
        self.next_btn.setText("保存" if self.step_index == len(REGION_STEPS) - 1 else "下一项")
        self.canvas.set_step(key, self.regions)

    def reset_current(self):
        key, _label, _hint = REGION_STEPS[self.step_index]
        self.regions.pop(key, None)
        self.canvas.clear_current()

    def accept_step(self):
        key, label, _hint = REGION_STEPS[self.step_index]
        region = self.canvas.current_region()
        if region:
            self.regions[key] = region
        elif key not in self.regions:
            show_app_warning(self, "框选识别位置", f"请先框选“{label}”区域。")
            return
        if self.step_index < len(REGION_STEPS) - 1:
            self.step_index += 1
            self.refresh_step()
            return
        self.accept()


class PanelWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.drag_start = None
        self.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(390, 430)
        self.resize(430, 590)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.shell = QFrame()
        self.shell.setObjectName("shell")
        outer.addWidget(self.shell)
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 6, 8, 6)
        header_layout.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.title = QLabel("精灵鉴定器")
        self.title.setObjectName("title")
        self.status = QLabel("加载中")
        self.status.setObjectName("muted")
        title_box.addWidget(self.title)
        title_box.addWidget(self.status)
        header_layout.addLayout(title_box, 1)
        collapse = QPushButton("收起")
        collapse.clicked.connect(self.app.collapse)
        header_layout.addWidget(collapse)
        shell_layout.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body = QWidget()
        self.body.setObjectName("body")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 10, 10, 10)
        self.body_layout.setSpacing(8)
        self.scroll.setWidget(self.body)
        shell_layout.addWidget(self.scroll, 1)

        self.message = QLabel("点击鉴定后加载识别引擎，首次鉴定会稍慢。")
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        self.body_layout.addWidget(self.message)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.recognize_btn = QPushButton("鉴定")
        self.recognize_btn.setEnabled(False)
        self.recognize_btn.clicked.connect(self.app.recognize)
        controls.addWidget(self.recognize_btn)
        self.body_layout.addLayout(controls)

        identity_card = self.card("当前鉴定")
        identity_grid = QGridLayout()
        identity_grid.setSpacing(6)
        self.identity_labels = {}
        for col, (key, label, value, role) in enumerate((
            ("pet", "精灵名称", "未识别", "petValue"),
            ("plus", "性格增益", "+ -", "accentValue"),
            ("minus", "性格减益", "- -", "redValue"),
        )):
            box = QFrame()
            box.setObjectName("tile")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(7, 6, 7, 6)
            name = QLabel(label)
            name.setObjectName("muted")
            stat = QLabel(value)
            stat.setObjectName(role)
            stat.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.identity_labels[key] = stat
            box_layout.addWidget(name)
            box_layout.addWidget(stat)
            identity_grid.addWidget(box, 0, col)
        identity_card.layout().addLayout(identity_grid)
        self.body_layout.addWidget(identity_card)

        iv_card = self.card("个体加成")
        iv_grid = QGridLayout()
        iv_grid.setSpacing(4)
        self.iv_labels = {}
        for index, stat in enumerate(SCREEN_STAT_ORDER):
            box = QFrame()
            box.setObjectName("tile")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(7, 5, 7, 5)
            name = QLabel(stat)
            name.setObjectName("muted")
            value = QLabel("+0")
            value.setObjectName("goldValue")
            self.iv_labels[stat] = value
            box_layout.addWidget(name)
            box_layout.addWidget(value)
            iv_grid.addWidget(box, index // 3, index % 3)
        iv_card.layout().addLayout(iv_grid)
        self.body_layout.addWidget(iv_card)

        cost_card = self.card("推荐消耗")
        self.cost_container = QVBoxLayout()
        self.cost_container.setSpacing(4)
        self.cost_placeholder = QLabel("暂无匹配方案")
        self.cost_placeholder.setObjectName("muted")
        self.cost_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cost_container.addWidget(self.cost_placeholder)
        cost_card.layout().addLayout(self.cost_container)
        self.body_layout.addWidget(cost_card)

        plan_card = self.card("目标与步骤")
        self.target_label = QLabel("目标个体：-")
        self.target_label.setWordWrap(True)
        self.target_nature_label = QLabel("目标性格：-")
        self.target_nature_label.setObjectName("muted")
        self.target_label.setVisible(False)
        self.target_nature_label.setVisible(False)
        self.steps = QTextEdit()
        self.steps.setReadOnly(True)
        self.steps.setMinimumHeight(110)
        self.steps.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plan_card.layout().addWidget(self.target_label)
        plan_card.layout().addWidget(self.target_nature_label)
        plan_card.layout().addWidget(self.steps)
        self.body_layout.addWidget(plan_card, 1)

        self.grip = QSizeGrip(self.shell)
        self.grip.setObjectName("sizeGrip")
        self.grip.resize(14, 14)
        self.grip.raise_()
        QTimer.singleShot(0, self.fit_to_content)

    def card(self, title=None):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        if title:
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            layout.addWidget(label)
        return frame

    def fit_to_content(self):
        screen = QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 760
        available_width = screen.availableGeometry().width() if screen else 1280
        content_height = self.header.sizeHint().height() + self.body.sizeHint().height() + 22
        content_width = max(410, min(460, self.body.sizeHint().width() + 36))
        target_height = max(430, min(content_height, available_height - 80))
        target_width = min(content_width, available_width - 80)
        self.resize(target_width, target_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "grip"):
            self.grip.move(max(0, self.shell.width() - 20), max(0, self.shell.height() - 20))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.header.geometry().contains(event.position().toPoint()):
            self.drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.move(event.globalPosition().toPoint() - self.drag_start)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        event.accept()


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("mainWindow")
        self.setWindowTitle("精灵鉴定器")
        self.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.setMinimumSize(500, 620)
        self.resize(540, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        icon = QLabel()
        pixmap = QPixmap(str(resource_path("assets/app_ball.png")))
        if pixmap.isNull():
            pixmap = QPixmap(str(resource_path("assets/app.png")))
        icon.setPixmap(pixmap.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_box = QVBoxLayout()
        title = QLabel("精灵鉴定器")
        title.setObjectName("title")
        self.status = QLabel("就绪")
        self.status.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(self.status)
        header.addWidget(icon)
        header.addLayout(title_box, 1)
        root.addLayout(header)

        float_card = self.card("悬浮球")
        float_row = QHBoxLayout()
        self.float_btn = QPushButton("启动悬浮球")
        self.float_btn.clicked.connect(self.app.toggle_float_ball)
        self.float_state = QLabel("未启动")
        self.float_state.setObjectName("muted")
        float_row.addWidget(self.float_btn)
        float_row.addWidget(self.float_state, 1)
        float_card.layout().addLayout(float_row)
        root.addWidget(float_card)

        hotkey_card = self.card("快捷键")
        hotkey_grid = QGridLayout()
        hotkey_grid.setHorizontalSpacing(8)
        hotkey_grid.setVerticalSpacing(8)
        self.hotkey_edit = QKeySequenceEdit(QKeySequence(self.app.hotkey_text))
        self.hotkey_edit.setObjectName("hotkeyEdit")
        self.hotkey_edit.keySequenceChanged.connect(self.app.on_hotkey_changed)
        self.hotkey_btn = QPushButton("启动快捷键")
        self.hotkey_btn.clicked.connect(self.app.toggle_hotkey)
        self.hotkey_state = QLabel("未启动")
        self.hotkey_state.setObjectName("muted")
        self.hotkey_hint = QLabel("提示：单键快捷键需要以管理员身份运行；单修饰键（仅 Ctrl/Alt/Shift/Win）不可使用。")
        self.hotkey_hint.setObjectName("muted")
        self.hotkey_hint.setWordWrap(True)
        hotkey_grid.addWidget(self.hotkey_edit, 0, 0)
        hotkey_grid.addWidget(self.hotkey_btn, 0, 1)
        hotkey_grid.addWidget(self.hotkey_state, 1, 0, 1, 2)
        hotkey_grid.addWidget(self.hotkey_hint, 2, 0, 1, 2)
        hotkey_grid.setColumnStretch(0, 1)
        hotkey_card.layout().addLayout(hotkey_grid)
        root.addWidget(hotkey_card)

        region_card = self.card("识别位置")
        region_grid = QGridLayout()
        region_grid.setHorizontalSpacing(8)
        region_grid.setVerticalSpacing(8)
        self.region_btn = QPushButton("框选识别位置")
        self.region_btn.clicked.connect(self.app.calibrate_regions)
        self.region_select = QComboBox()
        self.region_select.setObjectName("regionSelect")
        self.delete_region_btn = QPushButton("删除选中分辨率")
        self.delete_region_btn.clicked.connect(self.app.delete_selected_regions)
        self.region_state = QLabel("未设置")
        self.region_state.setObjectName("muted")
        self.region_hint = QLabel("按游戏窗口分辨率保存：精灵名称、特性、资质列表区域。")
        self.region_hint.setObjectName("muted")
        self.region_hint.setWordWrap(True)
        region_grid.addWidget(self.region_btn, 0, 0)
        region_grid.addWidget(self.region_state, 0, 1)
        region_grid.addWidget(self.region_select, 1, 0)
        region_grid.addWidget(self.delete_region_btn, 1, 1)
        region_grid.addWidget(self.region_hint, 2, 0, 1, 2)
        region_grid.setColumnStretch(0, 1)
        region_card.layout().addLayout(region_grid)
        root.addWidget(region_card)

        custom_card = self.card("自定义培养方案")
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        self.plan_pet = QLineEdit()
        self.plan_pet.setPlaceholderText("精灵名称")
        self.plan_name = QLineEdit()
        self.plan_name.setPlaceholderText("方案名称")
        self.plan_stats = QLineEdit()
        self.plan_stats.setPlaceholderText("推荐个体值，例如：物攻/速度、魔攻")
        self.plan_natures = QLineEdit()
        self.plan_natures.setPlaceholderText("推荐性格，例如：固执、勇敢")
        self.save_plan_btn = QPushButton("保存方案")
        self.save_plan_btn.clicked.connect(self.app.save_custom_plan)
        self.plan_select = QComboBox()
        self.plan_select.setObjectName("planSelect")
        self.delete_plan_btn = QPushButton("删除选中方案")
        self.delete_plan_btn.clicked.connect(self.app.delete_custom_plan)
        form.addWidget(self.plan_pet, 0, 0)
        form.addWidget(self.plan_name, 0, 1)
        form.addWidget(self.plan_stats, 1, 0, 1, 2)
        form.addWidget(self.plan_natures, 2, 0, 1, 2)
        form.addWidget(self.save_plan_btn, 3, 0, 1, 2)
        form.addWidget(self.plan_select, 4, 0)
        form.addWidget(self.delete_plan_btn, 4, 1)
        custom_card.layout().addLayout(form)
        self.plan_list = QTextEdit()
        self.plan_list.setReadOnly(True)
        self.plan_list.setMinimumHeight(120)
        custom_card.layout().addWidget(self.plan_list)
        root.addWidget(custom_card, 1)

    def card(self, title=None):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            layout.addWidget(label)
        return frame

    def set_float_running(self, running):
        self.float_btn.setText("关闭悬浮球" if running else "启动悬浮球")
        self.float_state.setText("已启动" if running else "未启动")

    def set_hotkey_running(self, running, text=None):
        self.hotkey_btn.setText("关闭快捷键" if running else "启动快捷键")
        self.hotkey_state.setText(f"已启动：{text}" if running and text else "未启动")

    def refresh_plans(self, plans):
        self.plan_select.clear()
        if not plans:
            self.plan_select.addItem("暂无自定义方案", -1)
            self.delete_plan_btn.setEnabled(False)
            self.plan_list.setPlainText("暂无自定义方案。")
            return
        self.delete_plan_btn.setEnabled(True)
        lines = []
        for index, plan in enumerate(plans, 1):
            name = plan.get("name") or f"方案{index}"
            pet = plan.get("pet") or "-"
            stats = plan.get("stats") or "-"
            natures = plan.get("natures") or "-"
            self.plan_select.addItem(f"{index}. {pet}｜{name}", index - 1)
            lines.append(f"{index}. {pet}｜{name}\n   个体：{stats}\n   性格：{natures}")
        self.plan_list.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        if self.app.exiting:
            event.accept()
            return
        event.ignore()
        self.app.minimize_main_to_tray()


class FloatDesktopApp:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.pet_data = None
        self.recognizer = None
        self.worker = None
        self.loader = None
        self.engine_loading = False
        self.pending_recognition = False
        self.pending_calibration = False
        self.hotkey_thread = None
        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.hotkey.connect(self.on_hotkey)
        self.hotkey_bridge.failed.connect(self.on_hotkey_error)
        settings = load_settings()
        self.hotkey_text = settings.get("hotkey", "Ctrl+F")
        self.recognition_regions = settings.get("recognition_regions", {}) or {}
        self.hotkey_running = False
        self.custom_plans = load_custom_plans()
        self.float_running = False
        self.exiting = False
        self.shutdown_started = False
        self.tray_notified = False

        self.qt.setStyleSheet(self.stylesheet())
        self.main = MainWindow(self)
        self.ball = BallWindow(self)
        self.panel = PanelWindow(self)
        self.tray = self.build_tray()
        self.main.refresh_plans(self.custom_plans)
        self.update_region_state()
        self.main.show()
        self.panel.status.setText("就绪")
        self.panel.recognize_btn.setEnabled(True)
        self.clear_result("点击鉴定开始识别。游戏可在后台但不要最小化。")

    def build_tray(self):
        tray = QSystemTrayIcon(QIcon(str(resource_path("assets/app.ico"))), self.qt)
        tray.setToolTip("精灵鉴定器")
        self.tray_popup = TrayPopup(self)
        tray.activated.connect(self.on_tray_activated)
        tray.show()
        return tray

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.tray_popup.show_at_cursor()
            return
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main()

    def show_main(self):
        self.main.showNormal()
        self.main.raise_()
        self.main.activateWindow()

    def minimize_main_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.main.hide()
            if self.tray and self.tray.isVisible() and not self.tray_notified:
                self.tray.showMessage(
                    "精灵鉴定器",
                    "已最小化到系统托盘，双击托盘图标可恢复。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
                self.tray_notified = True
        else:
            self.main.showMinimized()

    def stylesheet(self):
        combo_arrow = resource_path("assets/combo_arrow.svg").as_posix()
        return """
        QWidget { font-family: "Microsoft YaHei UI"; color: #f4f0e5; background: transparent; }
        #mainWindow { background: #181b1d; }
        #regionDialog { background: #181b1d; }
        #regionCanvas { background: #202326; border: 1px solid #34383b; border-radius: 10px; }
        #ballIcon { background: transparent; border: 0; }
        #shell { background: #181b1d; border: 1px solid #34383b; border-radius: 16px; }
        #header { background: #181b1d; border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom: 1px solid #2b2f32; }
        #body { background: #181b1d; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }
        #title { font-size: 14px; font-weight: 700; }
        #muted, QLabel#muted { color: #a4aaa7; font-size: 10px; }
        #subtle { color: #7b8380; font-size: 10px; }
        #card { background: #202326; border: 1px solid #34383b; border-radius: 10px; }
        #tile { background: #24282b; border: 1px solid #383d40; border-radius: 8px; }
        #sectionTitle { font-size: 11px; font-weight: 700; color: #e7e1d4; }
        #petValue { color: #f4f0e5; font-size: 16px; font-weight: 700; }
        #goldValue { color: #f2bd4d; font-size: 18px; font-weight: 700; }
        #redValue { color: #ef6b66; font-size: 18px; font-weight: 700; }
        #accentValue { color: #20b894; font-size: 18px; font-weight: 700; }
        QPushButton { background: #24282b; border: 1px solid #383d40; border-radius: 8px; padding: 8px 10px; color: #f4f0e5; font-weight: 700; }
        QPushButton:hover { background: #2c3134; border-color: #495054; }
        QPushButton:disabled { color: #707774; background: #202326; border-color: #2f3437; }
        QPushButton:first-child { background: #20b894; border-color: #20b894; color: white; }
        #trayMenuShell { background: #202326; border: 1px solid #383d40; border-radius: 14px; }
        QPushButton#trayMenuItem { background: transparent; border: 0; border-radius: 8px; padding: 9px 16px; color: #f4f0e5; font-size: 13px; font-weight: 500; text-align: left; }
        QPushButton#trayMenuItem:hover { background: #2c3134; border: 0; color: #ffffff; }
        #trayMenuSeparator { background: #383d40; border: 0; margin: 6px 6px; }
        QMenu { background-color: #202326; color: #f4f0e5; border: 1px solid #383d40; border-radius: 10px; padding: 6px; margin: 0; }
        QMenu::item { background: transparent; padding: 8px 28px 8px 12px; border-radius: 6px; }
        QMenu::item:selected { background: #20b894; color: white; }
        QMenu::separator { height: 1px; background: #383d40; margin: 6px 4px; }
        QLineEdit, QComboBox, QKeySequenceEdit, QTextEdit { background: #202326; border: 1px solid #383d40; border-radius: 8px; padding: 7px; color: #f4f0e5; selection-background-color: #20b894; }
        QComboBox { padding: 7px 30px 7px 7px; }
        QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 28px; border: 0; background: transparent; margin: 1px 1px 1px 0; }
        QComboBox::down-arrow { image: url("__COMBO_ARROW__"); width: 10px; height: 6px; }
        QComboBox QAbstractItemView { background: #202326; border: 1px solid #383d40; outline: 0; selection-background-color: #20b894; color: #f4f0e5; }
        QLineEdit:focus, QComboBox:focus, QKeySequenceEdit:focus, QTextEdit:focus { border-color: #20b894; }
        QScrollArea { background: #181b1d; border: 0; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }
        QScrollBar:vertical { background: transparent; width: 5px; margin: 8px 0 8px 0; }
        QScrollBar::handle:vertical { background: #6a7470; border-radius: 2px; min-height: 28px; }
        QScrollBar::handle:vertical:hover { background: #20b894; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        #sizeGrip { background: transparent; width: 14px; height: 14px; }
        """.replace("__COMBO_ARROW__", combo_arrow)

    def load_engine(self):
        if self.exiting:
            return
        if self.engine_loading or self.recognizer:
            return
        self.engine_loading = True
        self.panel.status.setText("加载中")
        self.panel.message.setText("正在加载识别引擎，首次鉴定会稍慢...")
        self.panel.recognize_btn.setEnabled(False)
        self.loader = EngineLoader()
        self.loader.ready.connect(self.on_engine_ready)
        self.loader.failed.connect(self.on_error)
        self.loader.start()

    def on_engine_ready(self, payload):
        recognizer, pet_data = payload
        if self.exiting:
            try:
                recognizer.capture.stop()
            except Exception:
                pass
            return
        self.recognizer = recognizer
        self.pet_data = pet_data
        self.recognizer.set_manual_regions(self.recognition_regions)
        self.engine_loading = False
        self.panel.status.setText("就绪")
        self.panel.message.setText(f"RapidOCR 已加载，推荐表 {len(self.pet_data.names)} 只精灵。")
        self.main.status.setText(f"识别引擎已加载，推荐表 {len(self.pet_data.names)} 只精灵")
        self.panel.recognize_btn.setEnabled(True)
        if self.pending_recognition:
            self.pending_recognition = False
            QTimer.singleShot(0, self.recognize)
        if self.pending_calibration:
            self.pending_calibration = False
            QTimer.singleShot(0, self.calibrate_regions)

    def toggle_panel(self):
        if not self.float_running:
            self.toggle_float_ball()
        if self.panel.isVisible():
            self.collapse()
        else:
            self.expand()

    def toggle_float_ball(self):
        if self.float_running:
            self.panel.hide()
            self.ball.hide()
            self.float_running = False
        else:
            self.ball.show()
            self.ball.raise_()
            self.float_running = True
        self.main.set_float_running(self.float_running)

    def expand(self):
        self.panel.move(self.ball.x() + 72, max(20, self.ball.y() - 40))
        self.panel.show()
        self.panel.raise_()

    def collapse(self):
        self.panel.hide()

    def update_region_state(self, current_key=None):
        keys = sorted(self.recognition_regions.keys(), key=self.resolution_sort_key)
        selected = current_key or self.main.region_select.currentText()
        self.main.region_select.blockSignals(True)
        self.main.region_select.clear()
        if keys:
            self.main.region_select.addItems(keys)
            if selected in keys:
                self.main.region_select.setCurrentText(selected)
        else:
            self.main.region_select.addItem("暂无已设置分辨率")
        self.main.region_select.setEnabled(bool(keys))
        self.main.delete_region_btn.setEnabled(bool(keys))
        self.main.region_select.blockSignals(False)
        if current_key:
            self.main.region_state.setText(f"已保存：{current_key}")
        elif keys:
            self.main.region_state.setText(f"已设置 {len(keys)} 个分辨率")
        else:
            self.main.region_state.setText("未设置")

    def resolution_sort_key(self, key):
        match = re.fullmatch(r"(\d+)x(\d+)", str(key or ""))
        if not match:
            return (0, 0, str(key))
        width, height = int(match.group(1)), int(match.group(2))
        return (width * height, width, height)

    def calibrate_regions(self):
        if self.worker and self.worker.isRunning():
            show_app_warning(self.main, "框选识别位置", "正在鉴定中，请等待本次鉴定完成后再框选。")
            return
        if not self.recognizer:
            self.pending_calibration = True
            self.main.status.setText("正在加载识别引擎，加载完成后开始框选")
            self.load_engine()
            return
        try:
            image = self.recognizer.capture.frame()
        except Exception as error:
            show_app_warning(self.main, "框选识别位置", str(error))
            return
        h, w = image.shape[:2]
        key = f"{w}x{h}"
        dialog = RegionCalibrationDialog(image, self.recognition_regions.get(key, {}), self.main)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.recognition_regions[key] = dict(dialog.regions)
        save_settings({"recognition_regions": self.recognition_regions})
        if self.recognizer:
            self.recognizer.set_manual_regions(self.recognition_regions)
        self.update_region_state(key)
        self.main.status.setText(f"已保存 {key} 识别位置")

    def delete_selected_regions(self):
        key = self.main.region_select.currentText().strip()
        if not key or key == "暂无已设置分辨率":
            self.main.status.setText("没有可删除的识别位置")
            return
        if key not in self.recognition_regions:
            self.main.status.setText(f"{key} 没有手动识别位置")
            self.update_region_state()
            return
        self.recognition_regions.pop(key, None)
        save_settings({"recognition_regions": self.recognition_regions})
        if self.recognizer:
            self.recognizer.set_manual_regions(self.recognition_regions)
        self.update_region_state()
        self.main.status.setText(f"已清除 {key} 识别位置")

    def on_hotkey_changed(self, sequence):
        text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        if "," in text:
            text = text.split(",", 1)[0].strip()
        if not text:
            return
        try:
            self.hotkey_text = self.normalize_hotkey_text(text)
            save_settings({"hotkey": self.hotkey_text})
            self.main.hotkey_state.setText(f"待启动：{self.hotkey_text}" if not self.hotkey_running else f"已启动：{self.hotkey_text}")
        except ValueError:
            return

    def normalize_hotkey_text(self, value):
        aliases = {
            "CONTROL": "Ctrl",
            "CTRL": "Ctrl",
            "ALT": "Alt",
            "SHIFT": "Shift",
            "WIN": "Win",
            "META": "Win",
            "ESCAPE": "Esc",
            "ESC": "Esc",
            "SPACE": "Space",
            "RETURN": "Enter",
            "ENTER": "Enter",
            "BACKSPACE": "Backspace",
            "DELETE": "Delete",
            "INSERT": "Insert",
            "HOME": "Home",
            "END": "End",
            "TAB": "Tab",
            "PGUP": "PageUp",
            "PAGEUP": "PageUp",
            "PGDOWN": "PageDown",
            "PAGEDOWN": "PageDown",
            "UP": "Up",
            "DOWN": "Down",
            "LEFT": "Left",
            "RIGHT": "Right",
        }
        modifiers = []
        key = ""
        for part in [p.strip() for p in str(value or "").replace("Meta", "Win").split("+") if p.strip()]:
            upper = part.upper()
            normalized = aliases.get(upper)
            if not normalized:
                if upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24:
                    normalized = upper
                elif len(part) == 1:
                    normalized = part.upper()
                else:
                    normalized = part
            if normalized in {"Ctrl", "Alt", "Shift", "Win"}:
                if normalized not in modifiers:
                    modifiers.append(normalized)
            elif not key:
                key = normalized
        if not key:
            raise ValueError("快捷键需要一个主键，可以是单键或组合键；单修饰键不可使用")
        order = ["Ctrl", "Alt", "Shift", "Win"]
        modifiers.sort(key=lambda item: order.index(item))
        return "+".join([*modifiers, key] if modifiers else [key])

    def parse_hotkey(self, value):
        value = self.normalize_hotkey_text(value)
        self.hotkey_text = value
        modifiers = 0
        key = None
        key_map = {
            "ESC": 0x1B,
            "ESCAPE": 0x1B,
            "TAB": 0x09,
            "SPACE": 0x20,
            "ENTER": 0x0D,
            "RETURN": 0x0D,
            "BACKSPACE": 0x08,
            "DELETE": 0x2E,
            "INSERT": 0x2D,
            "HOME": 0x24,
            "END": 0x23,
            "PAGEUP": 0x21,
            "PAGEDOWN": 0x22,
            "UP": 0x26,
            "DOWN": 0x28,
            "LEFT": 0x25,
            "RIGHT": 0x27,
        }
        for part in [p.strip() for p in value.split("+") if p.strip()]:
            upper = part.upper()
            if upper in {"CTRL", "CONTROL"}:
                modifiers |= win32con.MOD_CONTROL
            elif upper == "ALT":
                modifiers |= win32con.MOD_ALT
            elif upper == "SHIFT":
                modifiers |= win32con.MOD_SHIFT
            elif upper in {"WIN", "WINDOWS", "META"}:
                modifiers |= win32con.MOD_WIN
            elif len(upper) == 1 and ("A" <= upper <= "Z" or "0" <= upper <= "9"):
                key = ord(upper)
            elif upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24:
                key = 0x70 + int(upper[1:]) - 1
            elif upper in key_map:
                key = key_map[upper]
        if key is None:
            raise ValueError("快捷键需要一个主键，可以是单键或组合键；单修饰键不可使用")
        return modifiers | 0x4000, key

    def toggle_hotkey(self):
        if self.hotkey_running:
            self.stop_hotkey()
            self.main.set_hotkey_running(False)
            self.panel.message.setText("全局快捷键已关闭。")
        else:
            self.start_hotkey()

    def start_hotkey(self):
        try:
            modifiers, key = self.parse_hotkey(self.hotkey_text)
        except Exception as error:
            self.panel.message.setText(str(error))
            return
        if "+" not in self.hotkey_text and not is_running_as_admin():
            message = f"单键快捷键 {self.hotkey_text} 需要以管理员身份运行后才能启动。"
            self.stop_hotkey()
            self.main.set_hotkey_running(False)
            self.panel.message.setText(message)
            self.main.hotkey_state.setText(message)
            show_app_warning(
                self.main,
                "快捷键启动失败",
                f"{message}\n\n请右键 PetAnalyzer，选择“以管理员身份运行”，然后重新启动快捷键。",
            )
            return
        self.stop_hotkey()
        self.hotkey_thread = HotkeyThread(modifiers, key, self.hotkey_text, self.hotkey_bridge)
        self.hotkey_thread.start()
        self.hotkey_running = True
        self.panel.message.setText(f"全局快捷键已启动：{self.hotkey_text}")
        self.main.set_hotkey_running(True, self.hotkey_text)

    def stop_hotkey(self):
        if self.hotkey_thread:
            self.hotkey_thread.stop()
            self.hotkey_thread.join(timeout=0.2)
        self.hotkey_thread = None
        self.hotkey_running = False

    def on_hotkey(self):
        if not self.float_running:
            self.toggle_float_ball()
        self.expand()
        if self.panel.recognize_btn.isEnabled():
            self.recognize()

    def on_hotkey_error(self, message):
        self.hotkey_running = False
        self.main.set_hotkey_running(False)
        self.panel.message.setText(message)
        self.main.hotkey_state.setText(message)
        if "管理员" in str(message):
            show_app_warning(
                self.main,
                "快捷键启动失败",
                f"{message}\n\n请右键 PetAnalyzer，选择“以管理员身份运行”，然后重新启动快捷键。",
            )

    def save_custom_plan(self):
        pet = self.main.plan_pet.text().strip()
        name = self.main.plan_name.text().strip() or "默认方案"
        stats = self.main.plan_stats.text().strip()
        natures = self.main.plan_natures.text().strip()
        if not pet:
            self.main.status.setText("请填写精灵名称")
            return
        if not stats and not natures:
            self.main.status.setText("请至少填写推荐个体值或推荐性格")
            return
        key = plan_key(pet, stats, natures)
        for plan in self.custom_plans:
            if plan_key(plan.get("pet"), plan.get("stats"), plan.get("natures")) == key:
                self.main.status.setText("已存在相同自定义方案，未重复添加")
                return
        if self.same_as_recommendation(pet, stats, natures):
            self.main.status.setText("该方案已存在于推荐表，未重复添加")
            return
        self.custom_plans.append({
            "pet": pet,
            "name": name,
            "stats": stats,
            "natures": natures,
        })
        save_custom_plans(self.custom_plans)
        self.main.refresh_plans(self.custom_plans)
        self.main.status.setText(f"已保存：{pet}｜{name}")
        self.main.plan_name.clear()
        self.main.plan_stats.clear()
        self.main.plan_natures.clear()
        self.reset_engine_after_plan_change()

    def delete_custom_plan(self):
        index = self.main.plan_select.currentData()
        if not isinstance(index, int) or index < 0 or index >= len(self.custom_plans):
            self.main.status.setText("没有可删除的自定义方案")
            return
        removed = self.custom_plans.pop(index)
        save_custom_plans(self.custom_plans)
        self.main.refresh_plans(self.custom_plans)
        self.main.status.setText(f"已删除：{removed.get('pet', '-') }｜{removed.get('name', '方案')}")
        self.reset_engine_after_plan_change()

    def reset_engine_after_plan_change(self):
        if self.recognizer:
            try:
                self.recognizer.capture.stop()
            except Exception:
                pass
            self.recognizer = None
            self.pet_data = None
            self.panel.message.setText("自定义方案已更新，下次鉴定会重新加载推荐表。")

    def same_as_recommendation(self, pet, stats, natures):
        try:
            if not self.pet_data:
                from pet_float_app import DATA_PATH, PetData

                pet_data = PetData(DATA_PATH)
            else:
                pet_data = self.pet_data
            target = plan_key(pet, stats, natures)
            for variant in pet_data.recommendation_variants(pet):
                if plan_key(pet, variant.get("statText"), variant.get("natureText")) == target:
                    return True
        except Exception:
            return False
        return False

    def recognize(self):
        if self.exiting:
            return
        if self.worker and self.worker.isRunning():
            return
        if not self.recognizer:
            self.pending_recognition = True
            self.load_engine()
            return
        self.panel.recognize_btn.setEnabled(False)
        self.panel.status.setText("鉴定中")
        self.panel.message.setText("正在捕获游戏窗口并鉴定...")
        self.worker = RecognitionWorker(self.recognizer)
        self.worker.done.connect(self.render_result)
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(lambda: self.panel.recognize_btn.setEnabled(True))
        self.worker.start()

    def clear_result(self, message):
        self.panel.identity_labels["pet"].setText("未识别")
        self.panel.identity_labels["plus"].setText("+ -")
        self.panel.identity_labels["minus"].setText("- -")
        for stat in SCREEN_STAT_ORDER:
            self.panel.iv_labels[stat].setText("+0")
        self._clear_cost_rows()
        self.panel.target_label.setText("目标个体：-")
        self.panel.target_nature_label.setText("目标性格：-")
        self.panel.target_label.setVisible(False)
        self.panel.target_nature_label.setVisible(False)
        self.panel.steps.setPlainText(message)
        QTimer.singleShot(0, self.panel.fit_to_content)

    def _clear_cost_rows(self):
        while self.panel.cost_container.count():
            child = self.panel.cost_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.panel.cost_placeholder = QLabel("暂无匹配方案")
        self.panel.cost_placeholder.setObjectName("muted")
        self.panel.cost_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.panel.cost_container.addWidget(self.panel.cost_placeholder)

    def _populate_cost_rows(self, plans):
        while self.panel.cost_container.count():
            child = self.panel.cost_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for idx, plan in enumerate(plans):
            row = QFrame()
            row.setObjectName("tile")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 5, 8, 5)
            target_label = QLabel()
            target_text = plan.get("selectedTargets") or plan.get("targetText") or "—"
            nature_text = display_nature_text(plan["nature"])
            target_label.setText(f"方案 {idx + 1}｜{target_text} · {nature_text}")
            target_label.setObjectName("muted")
            row_layout.addWidget(target_label)
            row_layout.addStretch(1)
            for key, label, role in (
                ("mirror", "残镜", "redValue"),
                ("fit", "适格", "accentValue"),
                ("ability", "能力", "goldValue"),
            ):
                seg = QHBoxLayout()
                seg.setSpacing(2)
                name = QLabel(label)
                name.setObjectName("muted")
                val = plan["iv"][key] if key != "mirror" else plan["mirror"]
                value = QLabel(str(val))
                value.setObjectName(role)
                seg.addWidget(name)
                seg.addWidget(value)
                row_layout.addLayout(seg)
                if key != "ability":
                    sep = QLabel("·")
                    sep.setObjectName("subtle")
                    row_layout.addWidget(sep)
            self.panel.cost_container.addWidget(row)

    def matching_display_plans(self, rec):
        from pet_float_app import NATURE_BY_NAME, compute_iv_plan, expand_groups

        if not self.pet_data:
            return []
        sources = []
        if rec.pet:
            for variant in self.pet_data.recommendation_variants(rec.pet):
                sources.append({"source": "推荐表", "name": rec.pet, "variant": variant})
        else:
            trait_pets = self.pet_data.find_pets_by_trait(rec.trait) if rec.trait else []
            for pet_entry in self.pet_data.unique_pets(trait_pets):
                pet_name = pet_entry.get("名字", "")
                for variant in self.pet_data.recommendation_variants(pet_name):
                    sources.append({"source": "推荐表", "name": pet_name, "variant": variant})
        if not sources:
            return []
        for plan in self.custom_plans:
            if normalize_plan_text(plan.get("pet")) != normalize_plan_text(rec.pet):
                continue
            sources.append({
                "source": "自定义",
                "name": plan.get("name") or "方案",
                "variant": {
                    "statGroups": self.pet_data.parse_stat_groups(plan.get("stats")),
                    "statText": plan.get("stats") or "",
                    "natures": self.pet_data.parse_natures(plan.get("natures")),
                    "natureText": plan.get("natures") or "",
                },
            })
        plans = []
        seen = set()
        for item in sources:
            variant = item["variant"]
            target_natures = []
            if variant["natures"]:
                for name in variant["natures"]:
                    nature = NATURE_BY_NAME.get(name)
                    if nature and nature["plus"] == rec.plus:
                        target_natures.append(nature)
                if not target_natures:
                    continue
            else:
                target_natures.append(None)
            combos = expand_groups(variant["statGroups"])
            if not combos:
                combos = [[]]
            for combo in combos:
                iv_plan = compute_iv_plan(combo, rec.ivs, rec.iv_multiplier)
                for target_nature in target_natures:
                    mirror = 0 if not target_nature or target_nature["minus"] == rec.minus else 1
                    key = (
                        item["source"],
                        item["name"],
                        normalize_plan_text(variant.get("statText")),
                        target_nature["name"] if target_nature else "",
                        tuple(iv_plan.get("targets", [])),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    plans.append({
                        "source": item["source"],
                        "name": item["name"],
                        "variant": variant,
                        "nature": target_nature,
                        "mirror": mirror,
                        "iv": iv_plan,
                        "targetText": display_stat_text(variant),
                        "total": mirror + iv_plan["total"],
                        "selectedTargets": "、".join(combo) if combo else "无",
                    })
        return plans

    def render_result(self, rec):
        from pet_float_app import nature_by_stats

        if self.exiting:
            return
        current_nature = nature_by_stats(rec.plus, rec.minus)
        self.panel.status.setText("完成")
        self.panel.identity_labels["pet"].setText(rec.pet or "未识别")
        self.panel.identity_labels["plus"].setText(f"+{rec.plus}" if rec.plus else "未识别")
        self.panel.identity_labels["minus"].setText(f"-{rec.minus}" if rec.minus else "未识别")
        nature_text = ""
        if current_nature:
            nature_text = f" 当前性格：{current_nature['name']}。"
        plans = self.matching_display_plans(rec)
        status_message = f"鉴定完成，匹配 {rec.pet_score:.2f}，耗时 {rec.elapsed_ms} ms。{nature_text}"
        if plans:
            status_message += f"共 {len(plans)} 个匹配方案。"
        else:
            status_message += rec.plan_error or "没有可用方案。"
        self.panel.message.setText(status_message)
        for stat in SCREEN_STAT_ORDER:
            display = rec.iv_displays.get(stat, 0)
            base = rec.ivs.get(stat, 0)
            self.panel.iv_labels[stat].setText(f"+{display or base}")
        if plans:
            self._populate_cost_rows(plans)
            self.panel.target_label.setText(f"匹配方案：{len(plans)} 个")
            self.panel.target_nature_label.setText("")
            self.panel.target_label.setVisible(True)
            self.panel.target_nature_label.setVisible(False)
            lines = []
            for index, plan in enumerate(plans, 1):
                title = f"方案 {index}｜{plan['source']}"
                if plan["name"]:
                    title += f"｜{plan['name']}"
                nature_name = display_nature_text(plan["nature"])
                targets = plan.get("targetText") or "、".join(plan["iv"]["targets"]) or "无"
                selected = plan.get("selectedTargets") or "、".join(plan["iv"]["targets"]) or "无"
                lines.append(title)
                lines.append(f"消耗：残缺魔镜 {plan['mirror']}，适格钥匙 {plan['iv']['fit']}，能力钥匙 {plan['iv']['ability']}")
                lines.append(f"目标个体：{targets}")
                if "/" in targets or targets != selected:
                    lines.append(f"本次选择：{selected}")
                lines.append(f"目标性格：{nature_name}")
                lines.extend(plan["iv"]["steps"] or ["无需调整个体值。"])
                lines.append("")
            self.panel.steps.setPlainText("\n".join(lines).strip())
        else:
            self._clear_cost_rows()
            self.panel.target_label.setText("目标个体：-")
            self.panel.target_nature_label.setText("目标性格：-")
            self.panel.target_label.setVisible(False)
            self.panel.target_nature_label.setVisible(False)
            self.panel.steps.setPlainText(rec.plan_error or "没有可显示的推荐方案。")
        QTimer.singleShot(0, self.panel.fit_to_content)

    def on_error(self, message):
        if self.exiting:
            return
        self.engine_loading = False
        self.pending_recognition = False
        self.panel.status.setText("错误")
        self.panel.message.setText(str(message))
        self.main.status.setText(str(message))
        self.panel.recognize_btn.setEnabled(True)
        self.clear_result(str(message))

    def quit_app(self):
        if self.shutdown_started:
            return
        self.shutdown_started = True
        self.exiting = True
        self.pending_recognition = False
        self.stop_hotkey()
        self.stop_recognition_threads()
        self.panel.hide()
        self.ball.hide()
        self.main.hide()
        if hasattr(self, "tray_popup") and self.tray_popup:
            self.tray_popup.hide()
        if self.tray:
            self.tray.hide()
        self.qt.quit()

    def stop_recognition_threads(self):
        if self.recognizer:
            try:
                self.recognizer.capture.stop()
            except Exception:
                pass
        for attr in ("worker", "loader"):
            thread = getattr(self, attr, None)
            if not thread:
                continue
            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
                    if not thread.wait(2500):
                        thread.terminate()
                        thread.wait(1000)
            except Exception:
                pass
            setattr(self, attr, None)

    def close(self):
        self.quit_app()

    def run(self):
        return self.qt.exec()


if __name__ == "__main__":
    configure_windows_app_id()
    app = FloatDesktopApp()
    sys.exit(app.run())
