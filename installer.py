import os
import shutil
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "PocketBoleFloat"
DISPLAY_NAME = "精灵培养计算"


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def default_install_dir():
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return str(Path(root) / APP_NAME)


def create_shortcut(target_dir):
    try:
        import win32com.client

        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        shortcut_path = desktop / f"{DISPLAY_NAME}.lnk"
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(target_dir / f"{APP_NAME}.exe")
        shortcut.WorkingDirectory = str(target_dir)
        icon_path = target_dir / "assets" / "app.ico"
        shortcut.IconLocation = str(icon_path if icon_path.exists() else target_dir / f"{APP_NAME}.exe")
        shortcut.save()
    except Exception:
        pass


class InstallerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle(f"{DISPLAY_NAME} 安装器")
        self.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
        self.setMinimumSize(560, 260)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon = QLabel()
        pixmap = QPixmap(str(resource_path("assets/app_ball.png")))
        if not pixmap.isNull():
            icon.setPixmap(pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_box = QVBoxLayout()
        title = QLabel(DISPLAY_NAME)
        title.setObjectName("title")
        subtitle = QLabel("选择安装目录后安装。自定义方案会保存在安装目录的 data 文件夹。")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addWidget(icon)
        header.addLayout(title_box, 1)
        root.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(default_install_dir())
        browse = QPushButton("选择目录")
        browse.clicked.connect(self.choose_dir)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        card_layout.addLayout(row)

        self.status = QLabel("准备安装")
        self.status.setObjectName("muted")
        card_layout.addWidget(self.status)
        root.addWidget(card)

        actions = QHBoxLayout()
        actions.addStretch(1)
        install = QPushButton("安装")
        install.clicked.connect(self.install)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        actions.addWidget(install)
        actions.addWidget(close)
        root.addLayout(actions)

    def choose_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择安装目录", self.path_edit.text() or default_install_dir())
        if directory:
            self.path_edit.setText(directory)

    def install(self):
        target_dir = Path(self.path_edit.text().strip()).expanduser()
        if not target_dir:
            QMessageBox.warning(self, "安装失败", "请选择安装目录。")
            return
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "data").mkdir(parents=True, exist_ok=True)
            exe_src = resource_path(f"payload/{APP_NAME}.exe")
            if not exe_src.exists():
                raise FileNotFoundError(f"缺少安装载荷：{exe_src}")
            shutil.copy2(exe_src, target_dir / f"{APP_NAME}.exe")

            assets_src = resource_path("assets")
            assets_dst = target_dir / "assets"
            if assets_dst.exists():
                shutil.rmtree(assets_dst)
            shutil.copytree(assets_src, assets_dst)

            pet_data = resource_path("data/pet_plans.json")
            if pet_data.exists():
                shutil.copy2(pet_data, target_dir / "data" / "pet_plans.json")

            create_shortcut(target_dir)
            self.status.setText(f"安装完成：{target_dir}")
            QMessageBox.information(self, "安装完成", f"已安装到：\n{target_dir}\n\n桌面快捷方式已创建。")
        except PermissionError as error:
            QMessageBox.critical(self, "安装失败", f"没有写入权限，请选择其他目录。\n\n{error}")
        except Exception as error:
            QMessageBox.critical(self, "安装失败", str(error))


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path("assets/app.ico"))))
    app.setStyleSheet("""
        QWidget { font-family: "Microsoft YaHei UI"; color: #f4f0e5; background: #181b1d; }
        #title { font-size: 18px; font-weight: 700; }
        #muted { color: #a4aaa7; font-size: 11px; }
        #card { background: #202326; border: 1px solid #34383b; border-radius: 10px; }
        QLineEdit { background: #181b1d; border: 1px solid #383d40; border-radius: 8px; padding: 8px; color: #f4f0e5; }
        QLineEdit:focus { border-color: #20b894; }
        QPushButton { background: #24282b; border: 1px solid #383d40; border-radius: 8px; padding: 8px 12px; color: #f4f0e5; font-weight: 700; }
        QPushButton:hover { background: #2c3134; border-color: #495054; }
    """)
    window = InstallerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
