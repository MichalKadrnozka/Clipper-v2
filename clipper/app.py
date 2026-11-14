"""Early desktop interface for the media library."""
import os
import json
import queue
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QObject, QThread, QTimer, Qt, QUrl, QMimeData, QSize, QRect, QRectF, QFileSystemWatcher, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QColor, QImage, QPixmap, QPainter, QPainterPath, QPen, QShortcut, QKeySequence
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QListView, QMainWindow, QMessageBox,
    QPushButton, QDoubleSpinBox, QVBoxLayout, QGridLayout, QWidget, QGroupBox, QComboBox, QSpinBox, QTreeWidget, QTreeWidgetItem, QCheckBox, QMenu, QAbstractItemView, QSystemTrayIcon, QStyle, QHeaderView, QColorDialog, QStyledItemDelegate, QStyleOptionViewItem, QScrollArea, QTabWidget, QStackedWidget, QSplitter, QFrame)
from .library import Library, group_clips
from .media import duration, export, probe, trim, first_track_is_named_mix, Cancellation, MediaCancelled
from .obs import OBSClient
from .obs_setup import OBSSettings, configure_windows, device_options, set_devices, PROFILE, COLLECTION, ExtraAudioSource
from .recorder import CaptureSettings, GSRRecorder, audio_sources, active_window_name, name_saved_replay
from .hotkeys import WindowsHotkeys, parse_hotkey
from .startup import set_start_on_login, starts_on_login
from .secrets import protect, unprotect
from .thumbnails import Thumbnails
from .gallery_preview import GalleryPreview
from .migration import import_legacy
from .obs_process import launch_obs, wait_until_connected
from . import linux_identity
from .scaling import data_directory, valid_scale, apply_saved_scale

class TagDelegate(QStyledItemDelegate):
    """Draw the saved tag colors as compact labels in the library."""
    def paint(self, painter, option, index):
        tags = index.data(Qt.ItemDataRole.UserRole + 1) or []
        clean = QStyleOptionViewItem(option); self.initStyleOption(clean, index); clean.text = ''
        style = clean.widget.style() if clean.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, clean, painter, clean.widget)
        painter.save(); painter.setClipRect(option.rect)
        x = option.rect.left() + 5
        metrics = painter.fontMetrics()
        for name, color_name in tags:
            width = metrics.horizontalAdvance(name) + 16
            if x + width > option.rect.right(): break
            color = QColor(color_name)
            if not color.isValid(): color = QColor('#ff7300')
            height = min(24, option.rect.height() - 4)
            rect = option.rect.adjusted(0, 0, 0, 0)
            rect.setLeft(x); rect.setWidth(width); rect.setTop(option.rect.center().y() - height // 2); rect.setHeight(height)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(color); painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QColor('#111111') if color.lightness() > 145 else QColor('#ffffff'))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)
            x += width + 5
        painter.restore()
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        tags = index.data(Qt.ItemDataRole.UserRole + 1) or []
        width = sum(option.fontMetrics.horizontalAdvance(name) + 21 for name, _ in tags) + 5
        size.setWidth(min(500, max(size.width(), width)))
        return size

def ui_icon_path(name):
    return str(Path(__file__).resolve().parent / 'assets' / 'icons' / name)

class ClipCardDelegate(QStyledItemDelegate):
    """Draw the original Clipper card: wide 16:9 preview, top overlays, title bar."""
    def sizeHint(self, option, index):
        view = self.parent()
        size = view.gridSize() if isinstance(view, QListView) else QSize(300, 205)
        return size if size.isValid() and not size.isEmpty() else QSize(300, 205)
    def paint(self, painter, option, index):
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = option.rect.adjusted(0, 0, -10, -10)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        border = QColor('#ff7300') if selected else QColor('#555555') if hovered else QColor('#222222')
        painter.setPen(QPen(border, 5 if selected else 1)); painter.setBrush(QColor('#222222')); painter.drawRect(outer)
        thumb = outer.adjusted(3, 3, -3, -35); thumb.setHeight(min(thumb.width() * 9 // 16, outer.height() - 40))
        painter.fillRect(thumb, QColor('#000000'))
        preview = getattr(self.parent(), 'hover_preview', None)
        image = preview.pixmap_for(index) if preview else QPixmap()
        if image.isNull():
            image_path = index.data(Qt.ItemDataRole.UserRole + 4) or ''
            image = QPixmap(image_path) if image_path else QPixmap()
        if not image.isNull():
            scaled = image.scaled(thumb.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - thumb.width()) // 2; y = (scaled.height() - thumb.height()) // 2
            painter.drawPixmap(thumb, scaled, QRect(x, y, thumb.width(), thumb.height()))
        else:
            painter.setPen(QColor('#666666')); painter.drawText(thumb, Qt.AlignmentFlag.AlignCenter, 'Náhled není dostupný' if index.data(Qt.ItemDataRole.UserRole + 5) else 'Načítání…')
        # Tag labels sit on the image, like the original card overlay.
        x = thumb.left() + 6
        tags = index.data(Qt.ItemDataRole.UserRole + 1) or []
        metrics = painter.fontMetrics()
        for tag, color in tags[:4]:
            text = tag[:12] + ('…' if len(tag) > 12 else '')
            width = min(112, metrics.horizontalAdvance(text) + 24)
            pill = QRectF(x, thumb.top() + 6, width, 23)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(0, 0, 0, 210)); painter.drawRoundedRect(pill, 5, 5)
            dot = QRectF(x + 6, thumb.top() + 12, 10, 10)
            painter.setBrush(QColor(color)); painter.drawEllipse(dot)
            painter.setPen(QColor('#ffffff')); painter.drawText(QRectF(x + 20, thumb.top() + 5, width - 22, 24), Qt.AlignmentFlag.AlignVCenter, text)
            x += width + 4
        versions = index.data(Qt.ItemDataRole.UserRole + 2) or {}
        badges = [('icons8-trim-96.png', bool(versions.get('trim'))), ('icons8-export-96.png', bool(versions.get('export')))]
        bx = thumb.right() - 25
        for icon, enabled in badges:
            if enabled:
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(0, 0, 0, 190)); painter.drawEllipse(QRectF(bx, thumb.top()+6, 22, 22))
                pixmap = QPixmap(ui_icon_path(icon)).scaled(15, 15, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(int(bx + 3), thumb.top() + 9, pixmap)
            bx -= 25
        title_bar = QRectF(outer.left()+1, outer.bottom()-31, outer.width()-2, 30)
        painter.fillRect(title_bar, QColor('#222222'))
        name_rect = QRectF(title_bar.left()+8, title_bar.top(), title_bar.width()-16, title_bar.height())
        painter.setPen(QColor('#ffffff')); painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter, painter.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole) or '', Qt.TextElideMode.ElideRight, int(name_rect.width())))
        painter.restore()

class ScreenPreviewJob(QThread):
    frame = pyqtSignal(bytes)
    failed = pyqtSignal(str)
    backendUsed = pyqtSignal(str)
    def __init__(self, output, screen_name, parent=None, *, backend='auto', screen_geometry=None, desktop_geometry=None, uniform_scale=True):
        super().__init__(parent); self.output = Path(output); self.screen_name = screen_name
        self.backend = backend; self.screen_geometry = screen_geometry; self.desktop_geometry = desktop_geometry; self.uniform_scale = uniform_scale
    def run(self):
        errors = []
        try:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            backends = ['spectacle', 'grim'] if self.backend == 'spectacle' else ['grim', 'spectacle']
            for backend in backends:
                self.output.unlink(missing_ok=True)
                command = (['grim', '-o', self.screen_name, '-s', '0.5', '-t', 'png', '-l', '1', str(self.output)] if backend == 'grim'
                    else ['spectacle', '--background', '--nonotify', '--fullscreen', '--output', str(self.output)])
                try:
                    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=8 if backend == 'spectacle' else 3)
                    if result.returncode or not self.output.is_file():
                        errors.append(result.stderr.decode(errors='replace').strip() or f'{backend}: snímek není dostupný'); continue
                    if backend == 'spectacle' and self.screen_geometry and self.desktop_geometry and self.screen_geometry != self.desktop_geometry:
                        image = QImage(str(self.output)); desktop = self.desktop_geometry; screen = self.screen_geometry
                        sx = image.width() / desktop.width(); sy = image.height() / desktop.height()
                        if image.isNull() or not self.uniform_scale or abs(sx - sy) > 0.02:
                            errors.append('Náhled více monitorů s rozdílným měřítkem není dostupný'); continue
                        area = QRect(round((screen.x()-desktop.x())*sx), round((screen.y()-desktop.y())*sy), round(screen.width()*sx), round(screen.height()*sy))
                        if not image.rect().contains(area) or not image.copy(area).save(str(self.output), 'PNG'):
                            errors.append('Vybraný monitor se nepodařilo vyříznout'); continue
                    # A full-desktop Spectacle capture can be several megabytes at 4K.
                    # Decode and resize in this worker so the GUI never has to decode
                    # a full-resolution screenshot every time the preview refreshes.
                    image = QImage(str(self.output))
                    if image.isNull():
                        errors.append(f'{backend}: snímek se nepodařilo dekódovat'); continue
                    if image.width() > 1280 or image.height() > 720:
                        image = image.scaled(1280, 720, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if not image.save(str(self.output), 'PNG'):
                            errors.append(f'{backend}: náhled se nepodařilo připravit'); continue
                    self.backendUsed.emit(backend); self.frame.emit(self.output.read_bytes()); return
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(str(exc))
            self.failed.emit('; '.join(errors)[-180:] or 'snímek obrazovky není dostupný')
        except OSError as exc:
            self.failed.emit(str(exc)[:180])
        finally:
            try: self.output.unlink(missing_ok=True)
            except OSError: pass

class TransientStatusLabel(QLabel):
    """Keep the original uncluttered screen while showing operation feedback briefly."""
    def __init__(self, parent=None):
        super().__init__(parent); self.hide_timer = QTimer(self); self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_when_idle)
    def setText(self, value):
        super().setText(value)
        row = self.parentWidget()
        if value and row:
            row.show(); self.hide_timer.start(4500)
    def _hide_when_idle(self):
        window = self.window()
        cancel = getattr(window, 'cancel_button', None)
        if cancel and cancel.isEnabled():
            self.hide_timer.start(1500); return
        for name in ('thread', 'capture_thread'):
            worker = getattr(window, name, None)
            if worker and worker.isRunning():
                self.hide_timer.start(1500); return
        if self.parentWidget(): self.parentWidget().hide()

class Job(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()
    def __init__(self, action, with_progress=False):
        super().__init__(); self.action = action; self.with_progress = with_progress
        self.cancellation = Cancellation() if with_progress else None
    def run(self):
        try:
            result = self.action(self.progress.emit, self.cancellation) if self.with_progress else self.action(); self.finished.emit(str(result) if result else 'Hotovo')
        except MediaCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(str(e))

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Clipper')
        self.resize(1320, 860); self.setMinimumSize(720, 480)
        self.setStyleSheet('''
            QWidget { background: #121212; color: #eeeeee; font-size: 13px; }
            QLabel, QCheckBox, QRadioButton { background: transparent; }
            QLineEdit, QTreeWidget, QComboBox, QSpinBox, QDoubleSpinBox { background: #1e1e1e; border: 1px solid #444444; border-radius: 6px; padding: 7px 9px; selection-background-color: #ff7300; }
            QPushButton { background: #1e1e1e; border: 1px solid #444444; border-radius: 6px; padding: 7px 12px; }
            QPushButton:hover { background: #ff7300; border-color: #ff9000; color: white; }
            QPushButton[primary="true"] { background: #ff7300; border-color: #ff7300; color: white; font-weight: bold; }
            QPushButton[primary="true"]:hover { background: #ff9000; }
            QPushButton:disabled { color: #777777; background: #252525; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666666; border-radius: 3px; background: #1e1e1e; }
            QCheckBox::indicator:hover { border-color: #ff7300; }
            QCheckBox::indicator:checked { background: #ff7300; border-color: #ff7300; }
            QTabWidget::pane { border: 0; top: 0; background: #121212; }
            QTabBar::tab { background: transparent; border: 0; border-bottom: 2px solid transparent; padding: 10px 16px 8px; margin: 0 2px; color: #aaaaaa; }
            QTabBar::tab:selected { background: transparent; color: #ffffff; border-bottom: 2px solid #ff7300; }
            QTabBar::tab:hover:!selected { color: #ffffff; border-bottom-color: #555555; }
            QGroupBox { background: transparent; border: 0; border-radius: 8px; margin-top: 18px; padding: 8px 4px 4px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 4px; padding: 0 6px; color: #eeeeee; }
            QHeaderView::section { background: #282e39; padding: 6px; border: 0; }
            QTreeWidget::item { padding: 3px; }
            QTreeWidget::item:selected { background: #9b4e23; }
            QTreeWidget::item:hover { background: #2a303c; }
            QTreeWidget::branch { background: #202530; }
            QScrollArea { border: 0; background: transparent; }
            QSplitter::handle { background: #333333; width: 1px; }
            QMenu { background: #2a2a2a; border: 1px solid #444444; }
            QMenu::item:selected { background: #ff7300; }
            QSlider::groove:horizontal { background: #333333; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ff7300; width: 14px; margin: -4px 0; border-radius: 7px; }
        ''')
        data = data_directory()
        data.mkdir(parents=True, exist_ok=True)
        self.data_path = data
        self.library = Library(data / 'library.sqlite3')
        self.thumbnails = Thumbnails(data / 'thumbnails', self); self.thumbnails.ready.connect(self.thumbnail_ready); self.thumbnails.failed.connect(self.thumbnail_failed)
        self.folder = self.library.setting('folder')
        self.watcher = QFileSystemWatcher(self)
        self.refresh_timer = QTimer(self); self.refresh_timer.setSingleShot(True); self.refresh_timer.setInterval(3000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _: self.refresh_timer.start())
        if self.folder and Path(self.folder).is_dir(): self.watcher.addPath(self.folder)
        self.thread = None
        self.capture_thread = None
        self.obs_health_thread = None; self.obs_health_worker = None
        self.obs_metadata_jobs = set()
        self.obs_finalizing_paths = set()
        self.obs_expected = False; self.obs_generation = 0; self.obs_failures = 0; self.obs_warned = False
        self.obs_health_connection = None; self.closing_after_health = False
        self.hotkeys = None
        self.portal_hotkeys = None
        self.obs_preview_worker = None; self.obs_preview_attempted = False
        self.obs_preview_retry_at = 0.; self.obs_preview_generation = 0
        self.screen_preview_worker = None
        self.screen_preview_backend = 'auto'
        self.quitting = False
        self.tray = None
        self.recorder = GSRRecorder()
        root = QWidget(); self.setCentralWidget(root); self.root_layout = QVBoxLayout(root)
        self.root_layout.setContentsMargins(0, 0, 0, 0); self.root_layout.setSpacing(0)
        self.active_editor = None
        self.tabs = QTabWidget(); self.root_layout.addWidget(self.tabs, 1)
        library_tab = QWidget(); self.tabs.addTab(library_tab, 'Knihovna')
        library_layout = QVBoxLayout(library_tab); library_layout.setContentsMargins(12, 4, 12, 8); library_layout.setSpacing(4)
        self.folder_label = QLabel(); self.folder_label.hide()
        # The original app put search and paging in the shared top bar, beside its three flat tabs.
        self.search = QLineEdit(); self.search.setPlaceholderText('Hledat klipy a tagy…'); self.search.setClearButtonEnabled(True); self.search.setFixedWidth(210); self.search.addAction(QIcon(ui_icon_path('icons8-search-96.png')), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.search_changed)
        self.search_shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
        self.search_shortcut.activated.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.library_count = QLabel('0 clips'); self.library_count.setStyleSheet('color:#aaaaaa;font-size:12px;font-weight:bold;')
        self.library_dates = QLabel(''); self.library_dates.setStyleSheet('color:#888888;font-size:12px;')
        self.page_prev = QPushButton(); self.page_prev.setIcon(QIcon(ui_icon_path('icons8-back-96.png'))); self.page_prev.setFixedSize(32, 30); self.page_prev.clicked.connect(lambda: self.change_page(-1))
        self.page_next = QPushButton(); self.page_next.setIcon(QIcon(ui_icon_path('icons8-forward-96.png'))); self.page_next.setFixedSize(32, 30); self.page_next.clicked.connect(lambda: self.change_page(1))
        top_controls = QWidget(); top_controls.setStyleSheet('background:transparent;')
        top_row = QHBoxLayout(top_controls); top_row.setContentsMargins(0, 0, 12, 0); top_row.setSpacing(8)
        top_row.addWidget(self.library_count); top_row.addSpacing(10); top_row.addWidget(self.library_dates)
        top_row.addSpacing(8); top_row.addWidget(self.page_prev); top_row.addWidget(self.page_next); top_row.addSpacing(10); top_row.addWidget(self.search)
        self.tabs.setCornerWidget(top_controls, Qt.Corner.TopRightCorner)
        self.browser_splitter = QSplitter(Qt.Orientation.Horizontal); library_layout.addWidget(self.browser_splitter, 1)
        browser = QWidget(); browser_layout = QVBoxLayout(browser); browser_layout.setContentsMargins(0, 6, 0, 0); browser_layout.setSpacing(0)
        self.list = QListWidget(); self.list.setViewMode(QListView.ViewMode.IconMode); self.list.setFlow(QListView.Flow.LeftToRight)
        self.gallery_preview = GalleryPreview(self.list, self.library, self)
        self.list.hover_preview = self.gallery_preview
        self.list.setResizeMode(QListView.ResizeMode.Adjust); self.list.setMovement(QListView.Movement.Static); self.list.setWrapping(True)
        self.list.setGridSize(QSize(300, 205)); self.list.setSpacing(0); self.list.setIconSize(QSize(280, 158)); self.list.setWordWrap(True)
        self.list.setItemDelegate(ClipCardDelegate(self.list)); self.list.itemDoubleClicked.connect(lambda *_: self.open_editor())
        placeholder = QPixmap(120, 68); placeholder.fill(Qt.GlobalColor.transparent)
        self.thumbnail_placeholder = QIcon(placeholder)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.list.customContextMenuRequested.connect(self.context_menu)
        self.list.setMinimumWidth(260); self.list.setSelectionRectVisible(True); self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setStyleSheet('QListWidget { background: transparent; border: none; outline: none; } QListWidget::item { background: transparent; }')
        self.list.setFlow(QListView.Flow.LeftToRight); self.list.setLayoutMode(QListView.LayoutMode.Batched); self.list.setBatchSize(80)
        self.list.setMovement(QListView.Movement.Static); self.list.setSpacing(0); self.list.setGridSize(QSize(300, 205))
        self.list.setSelectionRectVisible(False)
        self.list.setItemAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clear_selection_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.list)
        self.clear_selection_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.clear_selection_shortcut.activated.connect(self.list.clearSelection)
        self.list.currentItemChanged.connect(lambda current, previous: self.update_clip_details(current))
        self.list.itemSelectionChanged.connect(self.selection_details_changed)
        browser_layout.addWidget(self.list, 1)
        self.empty_state = QFrame(); self.empty_state.setObjectName('emptyState'); self.empty_state.setStyleSheet('#emptyState {background:#1d222c;border:1px dashed #465064;border-radius:12px;}')
        empty_layout = QVBoxLayout(self.empty_state); empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = QLabel('▤'); empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter); empty_icon.setStyleSheet('font-size:38px;color:#778398;'); empty_layout.addWidget(empty_icon)
        self.empty_title = QLabel('Knihovna čeká na klipy'); self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty_title.setStyleSheet('font-size:18px;font-weight:700;'); empty_layout.addWidget(self.empty_title)
        self.empty_message = QLabel('Vyber složku s videi, nebo začni nahrávat.'); self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty_message.setWordWrap(True); self.empty_message.setStyleSheet('color:#9da8ba;'); empty_layout.addWidget(self.empty_message)
        empty_choose = QPushButton('Vybrat složku klipů'); empty_choose.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)); empty_choose.setProperty('primary', True); empty_choose.clicked.connect(self.choose_folder); empty_layout.addWidget(empty_choose, 0, Qt.AlignmentFlag.AlignHCenter)
        browser_layout.addWidget(self.empty_state, 1)
        self.browser_splitter.addWidget(browser)
        self.details_panel = QFrame(library_tab); self.details_panel.hide()
        detail_layout = QVBoxLayout(self.details_panel); detail_layout.setContentsMargins(16, 16, 16, 16); detail_layout.setSpacing(11)
        self.detail_thumbnail = QLabel('Vyber klip'); self.detail_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); self.detail_thumbnail.setMinimumHeight(190); self.detail_thumbnail.setMaximumHeight(250); self.detail_thumbnail.setStyleSheet('background:#10141b;border:1px solid #343b49;border-radius:9px;color:#788397;font-size:16px;'); detail_layout.addWidget(self.detail_thumbnail)
        self.detail_title = QLabel('Žádný klip není vybraný'); self.detail_title.setWordWrap(True); self.detail_title.setStyleSheet('font-size:18px;font-weight:700;color:#f4f6fb;'); detail_layout.addWidget(self.detail_title)
        self.detail_version = QComboBox(); self.detail_version.setToolTip('Vyber, kterou verzi klipu chceš otevřít, stříhat nebo exportovat.')
        self.detail_version.currentIndexChanged.connect(self.detail_version_changed); detail_layout.addWidget(self.detail_version)
        self.detail_type = QLabel(''); self.detail_type.setStyleSheet('color:#f0925c;font-weight:600;'); detail_layout.addWidget(self.detail_type)
        self.detail_meta = QLabel('Kliknutím vyber klip. Dvojklik otevře editor.'); self.detail_meta.setWordWrap(True); self.detail_meta.setStyleSheet('color:#9da8ba;'); detail_layout.addWidget(self.detail_meta)
        self.detail_tags = QLabel(''); self.detail_tags.setWordWrap(True); self.detail_tags.setStyleSheet('color:#d6dcea;'); detail_layout.addWidget(self.detail_tags)
        detail_layout.addStretch(1)
        detail_play = QPushButton('Přehrát'); detail_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)); detail_play.clicked.connect(self.play); detail_layout.addWidget(detail_play)
        detail_editor = QPushButton('Otevřít editor'); detail_editor.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)); detail_editor.setProperty('primary', True); detail_editor.clicked.connect(self.open_editor); detail_layout.addWidget(detail_editor)
        detail_row = QHBoxLayout(); detail_layout.addLayout(detail_row)
        detail_trim = QPushButton('Uložit střih'); detail_trim.clicked.connect(self.make_trim); detail_row.addWidget(detail_trim)
        detail_export = QPushButton('Export'); detail_export.clicked.connect(self.make_export); detail_row.addWidget(detail_export)
        detail_location = QPushButton('Otevřít umístění'); detail_location.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)); detail_location.clicked.connect(self.open_location); detail_layout.addWidget(detail_location)
        self.details_panel.setMinimumWidth(240)
        self.browser_splitter.addWidget(self.details_panel)
        self.browser_splitter.setStretchFactor(0, 1)
        self.browser_splitter.setStretchFactor(1, 0)
        self.browser_splitter.setSizes([900, 360])
        self.browser_splitter.splitterMoved.connect(lambda *_: self.update_grid_size())
        self.page_size = 300; self.current_page = 0
        settings_tab = QWidget(); self.tabs.addTab(settings_tab, 'Nastavení')
        settings_outer = QVBoxLayout(settings_tab); settings_outer.setContentsMargins(12, 12, 12, 12)
        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True); settings_scroll.setMaximumWidth(1050); settings_outer.addWidget(settings_scroll, 1, Qt.AlignmentFlag.AlignHCenter)
        settings_content = QWidget(); settings_layout = QVBoxLayout(settings_content); settings_layout.setContentsMargins(10, 10, 10, 10); settings_layout.setSpacing(14); settings_scroll.setWidget(settings_content)
        settings_heading = QLabel('Nastavení aplikace'); settings_heading.setStyleSheet('font-size: 20px; font-weight: 700; color: #f4f6fb;'); settings_layout.addWidget(settings_heading)
        general = QGroupBox('Obecné'); settings_layout.addWidget(general)
        general_layout = QVBoxLayout(general)
        folder_row = QHBoxLayout(); general_layout.addLayout(folder_row)
        folder_row.addWidget(QLabel('Složka klipů:'))
        self.settings_folder = QLineEdit(self.folder or ''); self.settings_folder.setReadOnly(True); self.settings_folder.setMinimumHeight(34); folder_row.addWidget(self.settings_folder, 1)
        browse_folder = QPushButton('Vybrat složku…'); browse_folder.clicked.connect(self.choose_folder); folder_row.addWidget(browse_folder)
        general_actions = QHBoxLayout(); general_layout.addLayout(general_actions)
        import_button = QPushButton('Importovat původní nastavení…'); import_button.clicked.connect(self.import_old); general_actions.addWidget(import_button)
        check_button = QPushButton('Zkontrolovat aplikaci…'); check_button.clicked.connect(self.check_dependencies); general_actions.addWidget(check_button)
        tags_button = QPushButton('Spravovat tagy…'); tags_button.clicked.connect(self.manage_tags); general_actions.addWidget(tags_button)
        scale_row = QHBoxLayout(); general_layout.addLayout(scale_row)
        scale_row.addWidget(QLabel('Měřítko UI:'))
        self.ui_scale = QSpinBox(); self.ui_scale.setRange(50, 200); self.ui_scale.setSingleStep(10); self.ui_scale.setSuffix(' %'); self.ui_scale.setMaximumWidth(220)
        self.ui_scale.setToolTip('Změna se projeví po opětovném spuštění aplikace.')
        self.ui_scale.setValue(round((valid_scale(self.library.setting('ui_scale', '1')) or 1) * 100))
        self.ui_scale.valueChanged.connect(self.set_ui_scale); scale_row.addWidget(self.ui_scale); scale_row.addStretch(1)
        if sys.platform.startswith('linux'):
            capture_tab = QWidget(); self.tabs.insertTab(0, capture_tab, 'Nahrávání')
            capture_layout = QVBoxLayout(capture_tab); capture_layout.setContentsMargins(10, 6, 10, 8); capture_layout.setSpacing(6)
            backend_row = QHBoxLayout(); capture_layout.addLayout(backend_row)
            backend_row.addWidget(QLabel('Záznamový systém:'))
            self.backend_combo = QComboBox(); self.backend_combo.addItems(['GPU Screen Recorder', 'OBS Studio'])
            self.backend_combo.setCurrentIndex(max(0, min(1, int(self.library.setting('linux_backend', '0')))))
            backend_row.addWidget(self.backend_combo); backend_row.addStretch(1)
            capture_pages = QStackedWidget(); capture_layout.addWidget(capture_pages, 1)
            self.backend_combo.currentIndexChanged.connect(lambda index: capture_pages.setCurrentIndex(index))
            self.backend_combo.currentIndexChanged.connect(lambda index: self.library.set_setting('linux_backend', str(index)))
            self.backend_combo.currentIndexChanged.connect(self.backend_changed)
            gsr_page = QWidget(); capture_pages.addWidget(gsr_page)
            gsr_layout = QHBoxLayout(gsr_page); gsr_layout.setContentsMargins(12, 8, 12, 8); gsr_layout.setSpacing(16)
            native_scroll = QScrollArea(); native_scroll.setWidgetResizable(True); native_scroll.setMinimumWidth(260); gsr_layout.addWidget(native_scroll, 7)
            native = QGroupBox('Nastavení záznamu'); native_scroll.setWidget(native)
            native_box = QVBoxLayout(native); native_layout = QGridLayout(); native_box.addLayout(native_layout)
            native_layout.setHorizontalSpacing(10); native_layout.setVerticalSpacing(6)
            self.display = QComboBox(); self.display.setMinimumWidth(150)
            for screen in QApplication.screens(): self.display.addItem(screen.name())
            self.display.setCurrentText(self.library.setting('display', self.display.currentText()))
            self.seconds = QSpinBox(); self.seconds.setRange(1, 3600); self.seconds.setValue(int(self.library.setting('seconds', '60'))); self.seconds.setSuffix(' s')
            self.fps = QSpinBox(); self.fps.setRange(1, 240); self.fps.setValue(int(self.library.setting('fps', '60'))); self.fps.setSuffix(' FPS')
            self.codec = QComboBox(); self.codec.addItems(['h264', 'hevc', 'av1']); self.codec.setCurrentText(self.library.setting('codec', 'h264'))
            self.format = QComboBox(); self.format.addItems(['mkv', 'mp4']); self.format.setCurrentText(self.library.setting('format', 'mkv'))
            self.quality = QComboBox(); self.quality.addItems(['medium', 'high', 'very_high', 'ultra']); self.quality.setCurrentText(self.library.setting('quality', 'high'))
            self.resolution = QLineEdit(self.library.setting('resolution', '')); self.resolution.setPlaceholderText('Původní'); self.resolution.setToolTip('Ponechte prázdné pro nativní rozlišení obrazovky.')
            fields = [('Displej', self.display), ('Délka', self.seconds), ('Snímkování', self.fps), ('Kodek', self.codec), ('Kontejner', self.format), ('Kvalita', self.quality), ('Rozlišení', self.resolution)]
            for index, (caption, widget) in enumerate(fields):
                row, column = divmod(index, 2); column *= 2
                label = QLabel(caption); label.setStyleSheet('color: #aaaaaa; font-size: 11px;')
                label.setMaximumHeight(20); widget.setMaximumHeight(38)
                native_layout.addWidget(label, row * 2, column); native_layout.addWidget(widget, row * 2 + 1, column)
                native_layout.setColumnStretch(column + 1, 1)
            native_layout.setColumnStretch(0, 1); native_layout.setColumnStretch(2, 1)
            audio_row = QHBoxLayout(); native_box.addLayout(audio_row)
            audio_label = QLabel('Zvukové zdroje'); audio_label.setMinimumWidth(92); audio_label.setStyleSheet('color: #9da8ba; font-size: 11px;'); audio_row.addWidget(audio_label)
            self.audio_device = QLineEdit(self.library.setting('audio_device', '')); self.audio_device.setPlaceholderText('Zdroje PulseAudio / PipeWire'); self.audio_device.setToolTip('Více zařízení oddělte středníkem.'); audio_row.addWidget(self.audio_device, 1)
            choose_audio = QPushButton('Vybrat zdroje…'); choose_audio.clicked.connect(self.choose_audio_sources); audio_row.addWidget(choose_audio)
            native_box.setAlignment(Qt.AlignmentFlag.AlignTop)
            capture_controls = QWidget(); controls_layout = QVBoxLayout(capture_controls); controls_layout.setContentsMargins(0, 4, 0, 4); controls_layout.setSpacing(10)
            self.gsr_preview = QLabel('Živý náhled'); self.gsr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.gsr_preview.setMinimumSize(260, 150); self.gsr_preview.setStyleSheet('background:#000000;border:1px solid #333333;border-radius:8px;color:#888888;'); controls_layout.addWidget(self.gsr_preview, 1)
            self.gsr_state_label = QLabel('Stav: buffer zastaven'); self.gsr_state_label.setStyleSheet('color:#888888;font-family:monospace;'); controls_layout.addWidget(self.gsr_state_label)
            action_row = QHBoxLayout(); controls_layout.addLayout(action_row)
            self.gsr_start_button = QPushButton('Spustit nahrávání'); self.gsr_start_button.setProperty('primary', True); self.gsr_start_button.setMinimumHeight(45); self.gsr_start_button.clicked.connect(lambda: self.gsr_action('start')); action_row.addWidget(self.gsr_start_button, 1)
            self.gsr_save_button = QPushButton('Uložit klip'); self.gsr_save_button.setMinimumHeight(45); self.gsr_save_button.setEnabled(False); self.gsr_save_button.clicked.connect(lambda: self.gsr_action('save')); action_row.addWidget(self.gsr_save_button, 1)
            self.gsr_stop_button = QPushButton('Zastavit buffer'); self.gsr_stop_button.setEnabled(False); self.gsr_stop_button.clicked.connect(lambda: self.gsr_action('stop')); controls_layout.addWidget(self.gsr_stop_button)
            self.seconds.valueChanged.connect(lambda value: self.gsr_save_button.setText(f'Uložit posledních {value} s'))
            self.folder_hint = QLabel('Ukládání do: ' + (self.folder or 'Vyber složku klipů v Nastavení')); self.folder_hint.setWordWrap(True); self.folder_hint.setStyleSheet('color:#888888;font-size:11px;'); controls_layout.addWidget(self.folder_hint)
            gsr_layout.addWidget(capture_controls, 4)
        if sys.platform != 'linux':
            capture_tab = QWidget(); self.tabs.insertTab(0, capture_tab, 'Nahrávání')
            capture_layout = QVBoxLayout(capture_tab); capture_layout.setContentsMargins(10, 6, 10, 8); capture_layout.setSpacing(6)
            capture_pages = QStackedWidget(); capture_layout.addWidget(capture_pages, 1)
        if sys.platform.startswith('linux'):
            obs_page = QWidget(); capture_pages.addWidget(obs_page)
            obs_layout = QHBoxLayout(obs_page); obs_layout.setContentsMargins(12, 8, 12, 8); obs_layout.setSpacing(16)
        else:
            obs_page = QWidget(); capture_pages.addWidget(obs_page)
            obs_layout = QHBoxLayout(obs_page); obs_layout.setContentsMargins(12, 8, 12, 8); obs_layout.setSpacing(16)
        if sys.platform.startswith('linux'):
            capture_pages.setCurrentIndex(self.backend_combo.currentIndex())
        recording = QGroupBox('Připojení k OBS Studio'); obs_layout.addWidget(recording, 7)
        record_layout = QVBoxLayout(recording)
        connection_row = QHBoxLayout(); record_layout.addLayout(connection_row)
        self.obs_url = QLineEdit(self.library.setting('obs_url', 'ws://127.0.0.1:4455'))
        self.obs_url.textChanged.connect(self.reset_obs_preview)
        self.obs_url.setPlaceholderText('Adresa OBS WebSocket'); self.obs_url.setToolTip('Adresa WebSocket serveru v OBS Studio.'); connection_row.addWidget(self.obs_url, 2)
        self.password_error = ''
        self.obs_password = QLineEdit(); self.obs_password.setPlaceholderText('Heslo OBS')
        self.obs_password.textChanged.connect(self.reset_obs_preview)
        self.obs_password.setEchoMode(QLineEdit.EchoMode.Password); connection_row.addWidget(self.obs_password, 1)
        if sys.platform == 'win32':
            stored = self.library.setting('obs_secret')
            if stored:
                try: self.obs_password.setText(unprotect(stored))
                except Exception: self.password_error = 'Uložené heslo OBS se nepodařilo načíst. Zadej ho znovu.'
        preview_button = QPushButton('Náhled'); preview_button.clicked.connect(self.show_obs_preview); connection_row.addWidget(preview_button)
        if sys.platform == 'win32':
            setup_button = QPushButton('Nastavit OBS…'); setup_button.clicked.connect(self.configure_obs); connection_row.addWidget(setup_button)
            devices_button = QPushButton('Zdroje…'); devices_button.clicked.connect(self.choose_obs_devices); connection_row.addWidget(devices_button)
        obs_help = QLabel('Připoj OBS WebSocket. Nahrávací profil, samostatné audio stopy a replay buffer můžeš nakonfigurovat přes Nastavit OBS.'); obs_help.setWordWrap(True); obs_help.setStyleSheet('color:#9da8ba;padding:6px 2px;'); record_layout.addWidget(obs_help)
        record_layout.addStretch(1)
        obs_controls = QWidget(); obs_layout.addWidget(obs_controls, 4)
        obs_controls_layout = QVBoxLayout(obs_controls); obs_controls_layout.setContentsMargins(0, 4, 0, 4); obs_controls_layout.setSpacing(10)
        self.obs_preview = QLabel('Živý náhled'); self.obs_preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.obs_preview.setMinimumSize(260, 150); self.obs_preview.setStyleSheet('background:#000000;border:1px solid #333333;border-radius:8px;color:#888888;'); obs_controls_layout.addWidget(self.obs_preview, 1)
        self.obs_state_label = QLabel('Stav: OBS není připojeno'); self.obs_state_label.setStyleSheet('color:#888888;font-family:monospace;'); obs_controls_layout.addWidget(self.obs_state_label)
        obs_state_help = QLabel('Spusť buffer před hraním. Klip uloží poslední nastavený interval.'); obs_state_help.setAlignment(Qt.AlignmentFlag.AlignCenter); obs_state_help.setWordWrap(True); obs_state_help.setStyleSheet('color:#9da8ba;'); obs_controls_layout.addWidget(obs_state_help)
        recording_actions = QHBoxLayout(); obs_controls_layout.addLayout(recording_actions)
        for title, operation in [('Stav', 'status'), ('Spustit', 'start'), ('Uložit klip', 'save'), ('Zastavit', 'stop')]:
            button = QPushButton(title); button.clicked.connect(lambda checked=False, op=operation: self.obs_action(op)); button.setMinimumHeight(45)
            if operation == 'save': button.setProperty('primary', True)
            recording_actions.addWidget(button, 1)
        if sys.platform == 'win32':
            shortcut_group = QGroupBox('Globální klávesové zkratky'); settings_layout.addWidget(shortcut_group)
            shortcuts = QGridLayout(shortcut_group)
            self.save_key = QLineEdit(self.library.setting('save_key', 'F10')); self.save_key.setMaximumWidth(180)
            self.toggle_key = QLineEdit(self.library.setting('toggle_key', 'F9')); self.toggle_key.setMaximumWidth(180)
            shortcuts.addWidget(QLabel('Uložit poslední klip'), 0, 0); shortcuts.addWidget(self.save_key, 0, 1)
            shortcuts.addWidget(QLabel('Zapnout / vypnout buffer'), 1, 0); shortcuts.addWidget(self.toggle_key, 1, 1)
            apply_keys = QPushButton('Použít zkratky'); apply_keys.setProperty('primary', True); apply_keys.clicked.connect(self.apply_hotkeys); shortcuts.addWidget(apply_keys, 0, 2, 2, 1)
            startup_group = QGroupBox('Při spuštění'); settings_layout.addWidget(startup_group)
            startup_layout = QVBoxLayout(startup_group)
            self.login_checkbox = QCheckBox('Spustit Clipper po přihlášení do Windows')
            self.login_checkbox.setChecked(starts_on_login()); self.login_checkbox.toggled.connect(self.set_login_start); startup_layout.addWidget(self.login_checkbox)
            self.auto_buffer = QCheckBox('Automaticky spustit replay buffer po otevření Clipperu')
            self.auto_buffer.setChecked(self.library.setting('auto_buffer') == '1')
            self.auto_buffer.toggled.connect(lambda checked: self.library.set_setting('auto_buffer', '1' if checked else '0')); startup_layout.addWidget(self.auto_buffer)
            connection_group = QGroupBox('Připojení a spuštění OBS'); settings_layout.addWidget(connection_group)
            options = QVBoxLayout(connection_group)
            self.remember_secret = QCheckBox('Zapamatovat heslo OBS zabezpečené účtem Windows')
            self.remember_secret.setChecked(bool(self.library.setting('obs_secret')))
            self.remember_secret.toggled.connect(self.save_obs_secret)
            self.obs_password.editingFinished.connect(self.save_obs_secret)
            options.addWidget(self.remember_secret)
            self.auto_obs = QCheckBox('V případě potřeby spustit OBS')
            self.auto_obs.setChecked(self.library.setting('auto_obs') == '1')
            self.auto_obs.toggled.connect(lambda checked: self.library.set_setting('auto_obs', '1' if checked else '0')); options.addWidget(self.auto_obs)
            obs_path_button = QPushButton('Vybrat umístění OBS…'); obs_path_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)); obs_path_button.clicked.connect(self.select_obs_path); options.addWidget(obs_path_button, 0, Qt.AlignmentFlag.AlignLeft)
        if sys.platform.startswith('linux'):
            shortcut_group = QGroupBox('Globální klávesové zkratky'); settings_layout.addWidget(shortcut_group)
            shortcut_row = QHBoxLayout(shortcut_group)
            shortcut_row.addWidget(QLabel('Záznamový systém:'))
            self.shortcut_backend = QComboBox(); self.shortcut_backend.addItems(['GPU Screen Recorder', 'OBS Studio'])
            self.shortcut_backend.setCurrentIndex(int(self.library.setting('linux_backend', '0')))
            self.shortcut_backend.currentIndexChanged.connect(lambda i: self.library.set_setting('linux_backend', str(i)))
            if hasattr(self, 'backend_combo'):
                self.backend_combo.currentIndexChanged.connect(self.shortcut_backend.setCurrentIndex)
                self.shortcut_backend.currentIndexChanged.connect(self.backend_combo.setCurrentIndex)
            shortcut_row.addWidget(self.shortcut_backend, 1)
            shortcut_button = QPushButton('Nastavit zkratky systému…'); shortcut_button.clicked.connect(self.setup_portal_shortcuts); shortcut_row.addWidget(shortcut_button)
            startup_group = QGroupBox('Při spuštění'); settings_layout.addWidget(startup_group)
            startup_layout = QVBoxLayout(startup_group)
            self.linux_login = QCheckBox('Spustit po přihlášení'); self.linux_login.setChecked(linux_identity.starts_on_login())
            self.linux_login.toggled.connect(self.set_linux_login); startup_layout.addWidget(self.linux_login)
            self.linux_auto = QCheckBox('Spustit buffer při startu'); self.linux_auto.setChecked(self.library.setting('linux_auto') == '1')
            self.linux_auto.toggled.connect(lambda checked: self.library.set_setting('linux_auto', '1' if checked else '0')); startup_layout.addWidget(self.linux_auto)
            self.linux_auto_shortcuts = QCheckBox('Zkratky při startu'); self.linux_auto_shortcuts.setChecked(self.library.setting('linux_auto_shortcuts') == '1')
            self.linux_auto_shortcuts.setToolTip('Po přihlášení se pokusí automaticky registrovat zkratky na podporovaném desktopu.')
            self.linux_auto_shortcuts.toggled.connect(lambda checked: self.library.set_setting('linux_auto_shortcuts', '1' if checked else '0')); startup_layout.addWidget(self.linux_auto_shortcuts)
        settings_layout.addStretch(1)
        self.tabs.currentChanged.connect(lambda index: top_controls.setVisible(index == self.tabs.indexOf(library_tab)))
        self.tabs.setCurrentIndex(self.tabs.indexOf(library_tab))  # původní Clipper otevřel přímo galerii
        self.status_container = QWidget(); status_container = self.status_container; status_row = QHBoxLayout(status_container); status_row.setContentsMargins(10, 0, 10, 4)
        self.status = TransientStatusLabel(status_container); self.status.setStyleSheet('color:#888888;'); status_row.addWidget(self.status, 1)
        self.cancel_button = QPushButton('Zrušit zpracování'); self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_media); self.cancel_button.hide(); status_row.addWidget(self.cancel_button)
        self.root_layout.addWidget(status_container); status_container.hide()
        if sys.platform == 'win32': self.apply_hotkeys()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), self)
            tray_menu = QMenu(self)
            tray_menu.addAction('Otevřít Clipper', self.show_normal)
            tray_menu.addAction('Uložit klip', self.save_from_tray)
            tray_menu.addSeparator(); tray_menu.addAction('Ukončit', self.quit_app)
            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(lambda reason: self.show_normal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.setToolTip('Clipper'); self.tray.show()
        self.refresh()
        self.record_timer = QTimer(self); self.record_timer.setInterval(1000); self.record_timer.timeout.connect(self.check_native_recorder); self.record_timer.start()
        self.preview_timer = QTimer(self); self.preview_timer.setInterval(1000); self.preview_timer.timeout.connect(self.update_screen_preview); self.preview_timer.start()
        self.obs_health_timer = QTimer(self); self.obs_health_timer.setInterval(8000); self.obs_health_timer.timeout.connect(self.check_obs_health)
        if self.password_error: QTimer.singleShot(0, lambda: self.job_error(self.password_error))
        if sys.platform == 'win32' and self.auto_buffer.isChecked() and not self.password_error: QTimer.singleShot(500, lambda: self.obs_action('start'))
        if sys.platform.startswith('linux') and self.linux_auto.isChecked():
            QTimer.singleShot(500, lambda: self.gsr_action('start') if self.shortcut_backend.currentIndex() == 0 else self.obs_action('start'))
        if sys.platform.startswith('linux') and self.linux_auto_shortcuts.isChecked(): QTimer.singleShot(700, self.setup_portal_shortcuts)
    def backend_changed(self, index):
        self.reset_obs_preview()
        QTimer.singleShot(0, self.update_screen_preview)
    def reset_obs_preview(self, *_):
        self.obs_preview_generation += 1
        self.obs_preview_attempted = False
        self.obs_preview_retry_at = 0.
        if self.obs_preview_worker and self.obs_preview_worker.isRunning(): self.obs_preview_worker.requestInterruption()
        if hasattr(self, 'obs_preview') and self.obs_preview.isVisible():
            self.obs_preview.setPixmap(QPixmap()); self.obs_preview.setText('Připojuji náhled OBS…')
    def start_obs_inline_preview(self):
        if self.obs_preview_attempted or not hasattr(self, 'obs_preview'): return
        if time.monotonic() < self.obs_preview_retry_at: return
        if self.obs_preview_worker and self.obs_preview_worker.isRunning(): return
        self.obs_preview_attempted = True
        try:
            from .obs_preview import PreviewWorker
            worker = PreviewWorker(self.obs_url.text().strip(), self.obs_password.text(), self)
            self.obs_preview_worker = worker
            generation = self.obs_preview_generation
            worker.frame.connect(lambda data: self.set_obs_inline_frame(data) if generation == self.obs_preview_generation else None)
            worker.error.connect(lambda message: self.set_obs_inline_error(message) if generation == self.obs_preview_generation else None)
            worker.finished.connect(lambda: self.obs_inline_finished(worker))
            worker.start()
        except Exception as exc:
            self.obs_preview_attempted = False
            self.obs_preview_retry_at = time.monotonic() + 5
            self.set_obs_inline_error(str(exc))
    def obs_inline_finished(self, worker):
        if worker is self.obs_preview_worker:
            self.obs_preview_worker = None
            if self.obs_preview_attempted:
                self.obs_preview_attempted = False
                self.obs_preview_retry_at = time.monotonic() + 5
        worker.deleteLater()
    def set_obs_inline_frame(self, data):
        if not hasattr(self, 'obs_preview'): return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data): return
        self.obs_preview.setText('')
        self.obs_preview.setPixmap(pixmap.scaled(self.obs_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    def set_obs_inline_error(self, message):
        if not hasattr(self, 'obs_preview'): return
        self.obs_preview.setPixmap(QPixmap())
        self.obs_preview.setText('Náhled OBS není dostupný\n' + message[:180])
    def update_screen_preview(self):
        if not self.isVisible() or self.tabs.currentIndex() != 0 or self.active_editor is not None:
            if self.obs_preview_worker and self.obs_preview_worker.isRunning() and self.obs_preview_attempted:
                self.reset_obs_preview()
            return
        if sys.platform.startswith('linux') and getattr(self, 'backend_combo', None) and self.backend_combo.currentIndex() == 1:
            self.start_obs_inline_preview(); return
        if not sys.platform.startswith('linux'):
            self.start_obs_inline_preview(); return
        widget = getattr(self, 'gsr_preview', None)
        if widget is None or not widget.isVisible(): return
        screens = QApplication.screens()
        screen_index = self.display.currentIndex() if hasattr(self, 'display') else 0
        screen = screens[screen_index] if screens and 0 <= screen_index < len(screens) else QApplication.primaryScreen()
        if screen is None:
            widget.setText('Náhled obrazovky není dostupný'); return
        if QApplication.platformName().lower() == 'xcb':
            try: frame = screen.grabWindow(0)
            except Exception: frame = QPixmap()
            if not frame.isNull():
                widget.setText(''); widget.setPixmap(frame.scaled(widget.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); return
            widget.setPixmap(QPixmap()); widget.setText('Náhled obrazovky není dostupný'); return
        if self.screen_preview_worker and self.screen_preview_worker.isRunning(): return
        desktop = QRect(screen.geometry())
        for other in screens: desktop = desktop.united(other.geometry())
        uniform_scale = all(abs(other.devicePixelRatio() - screen.devicePixelRatio()) < 0.01 for other in screens)
        worker = ScreenPreviewJob(self.data_path / f'screen-preview-{uuid.uuid4().hex}.png', screen.name(), self,
            backend=self.screen_preview_backend, screen_geometry=QRect(screen.geometry()), desktop_geometry=desktop, uniform_scale=uniform_scale)
        self.screen_preview_worker = worker
        worker.backendUsed.connect(lambda backend: setattr(self, 'screen_preview_backend', backend))
        worker.frame.connect(self.set_screen_preview_frame)
        worker.failed.connect(lambda message: self.set_screen_preview_error(widget, message))
        worker.finished.connect(lambda: self.screen_preview_finished(worker))
        worker.start()
    def screen_preview_finished(self, worker):
        if self.screen_preview_worker is worker:
            self.screen_preview_worker = None
        worker.deleteLater()
    def set_screen_preview_frame(self, data):
        widget = getattr(self, 'gsr_preview', None)
        if not widget: return
        frame = QPixmap()
        if not frame.loadFromData(data):
            self.set_screen_preview_error(widget, 'obrazovku se nepodařilo dekódovat'); return
        widget.setText(''); widget.setPixmap(frame.scaled(widget.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    def set_screen_preview_error(self, widget, message):
        widget.setPixmap(QPixmap())
        detail = 'Náhled není dostupný; nahrávání může stále fungovat.'
        if message and QApplication.platformName().lower() != 'offscreen': detail += '\n' + message
        widget.setText(detail)
    def set_ui_scale(self, percent):
        self.library.set_setting('ui_scale', str(percent / 100))
        self.status.setText('Měřítko rozhraní se změní po opětovném spuštění aplikace.')
    def set_obs_expected(self, active, connection):
        self.obs_generation += 1
        self.obs_expected = active; self.obs_health_connection = connection
        self.obs_failures = 0; self.obs_warned = False
        if active: self.obs_health_timer.start()
        else: self.obs_health_timer.stop()
        if hasattr(self, 'obs_state_label'): self.obs_state_label.setText('Replay buffer běží' if active else 'Replay buffer zastaven')
    def check_obs_health(self):
        if not self.obs_expected or self.obs_health_thread or not self.obs_health_connection: return
        if self.capture_thread and self.capture_thread.isRunning(): return
        generation = self.obs_generation
        url, password = self.obs_health_connection
        thread = QThread(self)
        worker = Job(lambda: 'active' if OBSClient(url, password, timeout=2).status() else 'inactive')
        worker.moveToThread(thread)
        self.obs_health_thread = thread; self.obs_health_worker = worker
        def report(active, detail=''):
            if generation != self.obs_generation or not self.obs_expected: return
            if active:
                if self.obs_warned: self.status.setText('OBS replay buffer je znovu aktivní.')
                self.obs_failures = 0; self.obs_warned = False
                return
            self.obs_failures += 1
            if self.obs_failures >= 2 and not self.obs_warned:
                self.obs_warned = True
                message = 'OBS replay buffer neběží nebo není dostupný. Zkontroluj OBS a znovu spusť nahrávání.'
                self.status.setText(message)
                if self.tray: self.tray.showMessage('Clipper — nahrávání se zastavilo', message, QSystemTrayIcon.MessageIcon.Warning)
        worker.finished.connect(lambda state: report(state == 'active'))
        worker.failed.connect(lambda message: report(False, message))
        for signal in (worker.finished, worker.failed):
            signal.connect(worker.deleteLater); signal.connect(thread.quit)
        def cleanup():
            if self.obs_health_thread is thread:
                self.obs_health_thread = None; self.obs_health_worker = None
            thread.deleteLater()
        thread.finished.connect(cleanup); thread.started.connect(worker.run); thread.start()
    def check_native_recorder(self):
        if self.recorder.expect_running and not self.recorder.running:
            self.recorder.expect_running = False
            detail = '\n'.join(self.recorder.log)[-500:] or 'Nahrávací proces se neočekávaně ukončil.'
            self.status.setText('Nahrávání se zastavilo: ' + detail)
            if self.tray: self.tray.showMessage('Clipper — nahrávání se zastavilo', detail[:200], QSystemTrayIcon.MessageIcon.Warning)
        while True:
            try: saved = self.recorder.saved.get_nowait()
            except queue.Empty: break
            path = saved.path
            self.remember_tracks(path, saved.first_is_mix, saved.track_names)
            self.status.setText('Klip uložen: ' + path); self.refresh()
            if self.tray: self.tray.showMessage('Clipper', 'Klip uložen: ' + Path(path).name)
    def remember_mix(self, path, track_names=None):
        self.remember_tracks(path, True, track_names)
    def remember_tracks(self, path, first_is_mix, track_names=None):
        edit = self.library.edit_for(path)
        changed = False
        if 'mix_first' not in edit:
            edit['mix_first'] = bool(first_is_mix); changed = True
        if track_names and 'track_names' not in edit:
            edit['track_names'] = list(track_names); changed = True
        if changed: self.library.save_edit(path, edit)
    def set_linux_login(self, enabled):
        try: linux_identity.set_login_start(enabled)
        except OSError as exc:
            self.linux_login.blockSignals(True); self.linux_login.setChecked(not enabled); self.linux_login.blockSignals(False)
            QMessageBox.warning(self, 'Spouštění', str(exc))
    def save_from_tray(self):
        if sys.platform.startswith('linux') and self.shortcut_backend.currentIndex() == 0: self.gsr_action('save')
        else: self.obs_action('save')
    def setup_portal_shortcuts(self):
        if self.portal_hotkeys and self.portal_hotkeys.isRunning():
            self.status.setText('Globální zkratky již běží.'); return
        try:
            from .portal_hotkeys import PortalHotkeys
            self.portal_hotkeys = PortalHotkeys(self)
            self.portal_hotkeys.activated.connect(self.portal_action)
            self.portal_hotkeys.error.connect(lambda msg: self.status.setText(msg))
            self.portal_hotkeys.bound.connect(lambda: self.status.setText('Globální zkratky jsou aktivní.'))
            self.portal_hotkeys.start()
        except ImportError as exc: QMessageBox.warning(self, 'Zkratky', str(exc))
    def portal_action(self, action):
        if self.shortcut_backend.currentIndex() == 1:
            self.obs_action(action)
        elif action == 'save': self.gsr_action('save')
        else: self.gsr_action('stop' if self.recorder.running else 'start')
    def select_obs_path(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Vyber obs64.exe', self.library.setting('obs_path'), 'OBS (obs64.exe)')
        if path: self.library.set_setting('obs_path', path)
    def show_normal(self):
        self.showNormal(); self.raise_(); self.activateWindow()
    def quit_app(self):
        self.quitting = True; self.close()
    def set_login_start(self, enabled):
        try: set_start_on_login(enabled)
        except OSError as exc:
            self.login_checkbox.blockSignals(True); self.login_checkbox.setChecked(not enabled); self.login_checkbox.blockSignals(False)
            QMessageBox.warning(self, 'Spouštění', str(exc))
    def save_obs_secret(self, *args):
        try:
            password = self.obs_password.text()
            value = protect(password) if self.remember_secret.isChecked() and password else ''
            self.library.set_setting('obs_secret', value)
            return True
        except Exception as exc:
            QMessageBox.warning(self, 'Heslo OBS', str(exc))
            return False
    def apply_hotkeys(self):
        bindings = {'save': self.save_key.text().strip(), 'toggle': self.toggle_key.text().strip()}
        try:
            parsed = [parse_hotkey(v) for v in bindings.values()]
            if len(set(parsed)) != len(parsed): raise ValueError('Zkratky musí být různé.')
        except ValueError as exc:
            QMessageBox.warning(self, 'Zkratky', str(exc)); return
        previous = {'save': self.library.setting('save_key', 'F10'),
                    'toggle': self.library.setting('toggle_key', 'F9')}
        self.stop_hotkeys()
        self._register_hotkeys(bindings, previous if bindings != previous else None)
    def stop_hotkeys(self):
        worker = self.hotkeys
        if worker is None: return
        # Ignore queued signals from the old registration while it is stopped.
        self.hotkeys = None
        for signal in (worker.activated, worker.error, worker.registered, worker.finished):
            try: signal.disconnect()
            except (TypeError, RuntimeError): pass
        worker.requestInterruption(); worker.wait(); worker.deleteLater()
    def _register_hotkeys(self, bindings, rollback=None, restored=False):
        worker = WindowsHotkeys(bindings, self)
        self.hotkeys = worker
        failed = {'value': False}
        def registered():
            if self.hotkeys is not worker or self.quitting: return
            for key, value in bindings.items(): self.library.set_setting(key + '_key', value)
            self.save_key.setText(bindings['save']); self.toggle_key.setText(bindings['toggle'])
            self.status.setText('Nové zkratky se nepodařilo nastavit; předchozí zkratky byly obnoveny.' if restored else 'Globální zkratky jsou aktivní.')
        def error(message):
            if self.hotkeys is not worker or self.quitting: return
            failed['value'] = True
            self.status.setText(message)
            if self.tray:
                self.tray.showMessage('Clipper — zkratky nejsou aktivní', message, QSystemTrayIcon.MessageIcon.Warning)
        def finished():
            if self.hotkeys is not worker: return
            self.hotkeys = None
            worker.deleteLater()
            if failed['value'] and rollback and not self.quitting:
                self._register_hotkeys(rollback, restored=True)
        worker.activated.connect(self.obs_action)
        worker.error.connect(error)
        worker.registered.connect(registered)
        worker.finished.connect(finished)
        worker.start()
    def choose_audio_sources(self):
        try: sources = audio_sources()
        except Exception as exc:
            QMessageBox.warning(self, 'Zvukové zdroje', str(exc)); return
        dialog = QDialog(self); dialog.setWindowTitle('Zvukové zdroje'); dialog.resize(520, 560)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(20, 18, 20, 16); layout.setSpacing(12)
        heading = QLabel('Vyber zvukové zdroje'); heading.setStyleSheet('font-size:19px;font-weight:700;color:#f4f6fb;'); layout.addWidget(heading)
        intro = QLabel('Clipper nahrává vybrané vstupy do samostatných stop. Můžeš zvolit více zařízení.'); intro.setWordWrap(True); intro.setStyleSheet('color:#9da8ba;'); layout.addWidget(intro)
        current = {value.strip() for value in self.audio_device.text().split(';') if value.strip()}
        checks = {}
        content = QWidget(); choices = QVBoxLayout(content); choices.setContentsMargins(4, 4, 4, 4); choices.setSpacing(5)
        for source in sources:
            checkbox = QCheckBox(source); checkbox.setChecked(source in current); checkbox.setMinimumHeight(34); choices.addWidget(checkbox); checks[source] = checkbox
        if not checks:
            none = QLabel('Nebyly nalezeny žádné zdroje. Zkontroluj PulseAudio nebo PipeWire.'); none.setWordWrap(True); none.setStyleSheet('color:#9da8ba;padding:12px;'); choices.addWidget(none)
        choices.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); layout.addWidget(scroll, 1)
        select_row = QHBoxLayout(); layout.addLayout(select_row)
        select_row.addWidget(QLabel(f'Nalezeno zdrojů: {len(checks)}')); select_row.addStretch(1)
        all_button = QPushButton('Vybrat vše'); all_button.clicked.connect(lambda: [box.setChecked(True) for box in checks.values()]); select_row.addWidget(all_button)
        clear_button = QPushButton('Vymazat výběr'); clear_button.clicked.connect(lambda: [box.setChecked(False) for box in checks.values()]); select_row.addWidget(clear_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Použít výběr')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.audio_device.setText('; '.join(name for name, box in checks.items() if box.isChecked()))
    def gsr_action(self, operation):
        if operation == 'start':
            if not self.folder:
                QMessageBox.warning(self, 'Nahrávání', 'Nejprve vyber složku klipů.'); return
            self.library.set_setting('seconds', str(self.seconds.value()))
            self.library.set_setting('fps', str(self.fps.value()))
            self.library.set_setting('audio_device', self.audio_device.text())
            for key, value in [('display', self.display.currentText()), ('codec', self.codec.currentText()), ('format', self.format.currentText()), ('quality', self.quality.currentText()), ('resolution', self.resolution.text().strip())]: self.library.set_setting(key, value)
            settings = CaptureSettings(self.folder, self.display.currentText(), self.seconds.value(), self.fps.value(), self.codec.currentText(), self.format.currentText(), self.quality.currentText(), self.resolution.text().strip(), self.audio_device.text().split(';'))
            def action():
                self.recorder.start(settings); return 'Replay buffer spuštěn'
        elif operation == 'stop':
            def action():
                self.recorder.stop(); return 'Replay buffer zastaven'
        else:
            def action():
                self.recorder.save(); return 'Požadavek na uložení klipu odeslán'
        def completed(message):
            running = operation != 'stop'
            if operation == 'start': running = True
            if operation == 'stop': running = False
            self.gsr_state_label.setText('Replay buffer běží' if running else 'Buffer zastaven')
            self.gsr_start_button.setEnabled(not running); self.gsr_save_button.setEnabled(running); self.gsr_stop_button.setEnabled(running)
            self.job_done(message)
        def failed(message):
            if operation == 'start': self.gsr_state_label.setText('Buffer se nepodařilo spustit')
            self.job_error(message)
        return self.start_job(action, capture=True, on_done=completed, on_error=failed)
    def show_obs_preview(self):
        from .obs_preview import OBSPreview
        preview = OBSPreview(self.obs_url.text().strip(), self.obs_password.text(), self)
        preview.exec(); preview.deleteLater()
    def choose_obs_devices(self):
        url, password = self.obs_url.text().strip(), self.obs_password.text()
        def query(): return json.dumps(device_options(OBSClient(url, password)))
        def show_options(payload):
            options = json.loads(payload)
            if not options:
                QMessageBox.information(self, 'Zdroje', 'Nejprve vytvoř nastavení OBS.'); return
            dialog = QDialog(self); dialog.setWindowTitle('Zdroje záznamu'); form = QFormLayout(dialog)
            widgets = {}
            labels = {'Clipper Display': 'Obrazovka', 'Clipper Desktop Audio': 'Zvuk počítače', 'Clipper Microphone': 'Mikrofon'}
            for name, data in options.items():
                combo = QComboBox()
                for item in data['items']:
                    if item.get('itemEnabled', True): combo.addItem(str(item.get('itemName', '')), item.get('itemValue'))
                if not combo.count(): continue
                index = combo.findData(data['current'])
                if index >= 0: combo.setCurrentIndex(index)
                widgets[name] = combo; form.addRow(labels.get(name, name), combo)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Použít')
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Zrušit')
            buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            choices = {name: combo.currentData() for name, combo in widgets.items()}
            def apply():
                set_devices(OBSClient(url, password), choices); return 'Zdroje byly nastaveny.'
            QTimer.singleShot(0, lambda: self.start_job(apply, capture=True))
        self.start_job(query, capture=True, on_done=show_options)
    def configure_obs(self):
        if not self.folder:
            QMessageBox.warning(self, 'Nastavení OBS', 'Nejprve vyber složku klipů.'); return
        dialog = QDialog(self); dialog.setWindowTitle('Nastavení nahrávání OBS'); dialog.resize(820, 720)
        outer = QVBoxLayout(dialog); outer.setContentsMargins(18, 16, 18, 14); outer.setSpacing(12)
        heading = QLabel('Záznam přes OBS Studio'); heading.setStyleSheet('font-size:19px;font-weight:700;color:#f4f6fb;'); outer.addWidget(heading)
        scroll = QScrollArea(dialog); scroll.setWidgetResizable(True)
        content = QWidget(); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(4, 4, 4, 4); content_layout.setSpacing(12)
        video_group = QGroupBox('Video a replay buffer'); form = QFormLayout(video_group); content_layout.addWidget(video_group)
        audio_group = QGroupBox('Zvuk'); audio_form = QFormLayout(audio_group); content_layout.addWidget(audio_group)
        extra_group = QGroupBox('Další zvukové stopy OBS'); extra_form = QVBoxLayout(extra_group); content_layout.addWidget(extra_group)
        content_layout.addStretch(1); scroll.setWidget(content); outer.addWidget(scroll, 1)
        values = {}
        for key, label, low, high, default in [('width', 'Šířka', 16, 4096, 1920), ('height', 'Výška', 16, 4096, 1080), ('fps', 'FPS', 1, 240, 60), ('seconds', 'Délka replay bufferu (s)', 1, 3600, 60)]:
            spin = QSpinBox(); spin.setRange(low, high); spin.setValue(int(self.library.setting('obs_'+key, str(default))))
            values[key] = spin; form.addRow(label, spin)
        source = QComboBox(); source.addItem('Obrazovka', 'display'); source.addItem('Hra na celé obrazovce', 'game')
        source.setCurrentIndex(max(0, source.findData(self.library.setting('obs_capture_mode', 'display')))); form.addRow('Zdroj obrazu', source)
        container = QComboBox(); container.addItems(['mkv', 'mp4']); container.setCurrentText(self.library.setting('obs_container', 'mkv')); form.addRow('Formát', container)
        encoder = QComboBox()
        for label, value in [('Automaticky podle OBS', ''), ('Software H.264 (x264)', 'x264'), ('NVIDIA H.264', 'nvenc'), ('NVIDIA HEVC', 'nvenc_hevc'), ('NVIDIA AV1', 'nvenc_av1'), ('Intel H.264', 'qsv'), ('Intel AV1', 'qsv_av1'), ('AMD H.264', 'amd'), ('AMD HEVC', 'amd_hevc'), ('AMD AV1', 'amd_av1')]: encoder.addItem(label, value)
        previous_encoder = encoder.findData(self.library.setting('obs_encoder', '')); encoder.setCurrentIndex(max(0, previous_encoder)); form.addRow('Kodek / enkodér', encoder)
        quality = QComboBox(); quality.addItem('Vysoká', 'HQ'); quality.addItem('Menší soubor', 'Small'); quality.setCurrentIndex(max(0, quality.findData(self.library.setting('obs_quality', 'HQ')))); form.addRow('Kvalita', quality)
        desktop = QCheckBox('Nahrávat výchozí zvuk počítače'); desktop.setChecked(self.library.setting('obs_desktop', '1') == '1'); audio_form.addRow(desktop)
        mic = QCheckBox('Nahrávat výchozí mikrofon'); mic.setChecked(self.library.setting('obs_mic', '1') == '1'); audio_form.addRow(mic)
        desktop_gain = QSpinBox(); desktop_gain.setRange(0, 200); desktop_gain.setSuffix(' %'); desktop_gain.setValue(int(self.library.setting('obs_desktop_gain', '100'))); audio_form.addRow('Hlasitost počítače', desktop_gain)
        mic_gain = QSpinBox(); mic_gain.setRange(0, 200); mic_gain.setSuffix(' %'); mic_gain.setValue(int(self.library.setting('obs_mic_gain', '100'))); audio_form.addRow('Hlasitost mikrofonu', mic_gain)
        from .audio_sources_ui import ExtraAudioEditor
        try:
            saved_extra = json.loads(self.library.setting('obs_extra_audio', '[]'))
            if not isinstance(saved_extra, list): saved_extra = []
        except (ValueError, TypeError): saved_extra = []
        extra = ExtraAudioEditor(saved_extra, dialog)
        extra_form.addWidget(extra)
        load_devices = QPushButton('Načíst dostupná zvuková zařízení z OBS'); extra_form.addWidget(load_devices)
        def load_extra_devices():
            url, password = self.obs_url.text().strip(), self.obs_password.text()
            load_devices.setEnabled(False); buttons.setEnabled(False)
            def query(): return json.dumps(device_options(OBSClient(url, password)))
            def release_controls():
                if dialog.isVisible(): load_devices.setEnabled(True); buttons.setEnabled(True)
            def after_thread():
                thread = self.capture_thread
                if thread and thread.isRunning(): thread.finished.connect(release_controls)
                else: release_controls()
            def loaded(payload):
                if dialog.isVisible():
                    options = json.loads(payload); extra.set_devices(options)
                    if not any(name in options for name in ('Clipper Desktop Audio', 'Clipper Microphone')):
                        QMessageBox.information(dialog, 'Zvuková zařízení', 'Nejprve použij nastavení OBS; potom lze načíst nabídku zařízení.')
                after_thread()
            def failed(message):
                after_thread()
                if dialog.isVisible(): QMessageBox.warning(dialog, 'Zvuková zařízení', message)
            if not self.start_job(query, capture=True, on_done=loaded, on_error=failed): release_controls()
        load_devices.clicked.connect(load_extra_devices)
        setup_note = QLabel('Nastavení vytvoří a aktivuje profil a scénu „Clipper Capture“. Původní profil OBS zůstane zachovaný.'); setup_note.setWordWrap(True); setup_note.setStyleSheet('color:#9da8ba;'); extra_form.addWidget(setup_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Uložit nastavení')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Zrušit')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); outer.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        for key, widget in values.items(): self.library.set_setting('obs_'+key, str(widget.value()))
        self.library.set_setting('obs_capture_mode', source.currentData())
        self.library.set_setting('obs_container', container.currentText())
        self.library.set_setting('obs_encoder', encoder.currentData()); self.library.set_setting('obs_quality', quality.currentData())
        self.library.set_setting('obs_desktop_gain', str(desktop_gain.value())); self.library.set_setting('obs_mic_gain', str(mic_gain.value()))
        self.library.set_setting('obs_desktop', '1' if desktop.isChecked() else '0'); self.library.set_setting('obs_mic', '1' if mic.isChecked() else '0')
        extra_data = extra.values()
        self.library.set_setting('obs_extra_audio', json.dumps(extra_data, ensure_ascii=False))
        settings = OBSSettings(self.folder, values['fps'].value(), values['seconds'].value(), values['width'].value(), values['height'].value(), container.currentText(), desktop.isChecked(), mic.isChecked(), encoder.currentData(), quality.currentData(), desktop_gain.value()/100, mic_gain.value()/100, source.currentData(), tuple(ExtraAudioSource(**item) for item in extra_data))
        url, password = self.obs_url.text().strip(), self.obs_password.text()
        def action():
            configure_windows(OBSClient(url, password), settings)
            return 'Profil OBS nastaven. Před použitím ověř náhled a zvuk.'
        def configured(message):
            names = ['Mix', 'Zvuk počítače', 'Mikrofon'] + [item['name'] for item in extra_data]
            self.library.set_setting('obs_active_track_names', json.dumps(names, ensure_ascii=False))
            self.job_done(message)
        self.start_job(action, capture=True, on_done=configured)
    def obs_action(self, operation):
        url, password = self.obs_url.text().strip(), self.obs_password.text()
        clips_folder = self.folder
        auto_launch = sys.platform == 'win32' and self.auto_obs.isChecked() and operation in ('start', 'toggle')
        obs_path = self.library.setting('obs_path') if auto_launch else ''
        self.library.set_setting('obs_url', url)
        if sys.platform == 'win32' and not self.save_obs_secret(): return
        save_metadata = {}
        try: saved_track_names = json.loads(self.library.setting('obs_active_track_names', '[]'))
        except (TypeError, ValueError): saved_track_names = []
        if not isinstance(saved_track_names, list): saved_track_names = []
        def action():
            client = OBSClient(url, password)
            if auto_launch:
                try: client.request('GetVersion')
                except Exception:
                    launch_obs(obs_path)
                    wait_until_connected(client)
            result = getattr(client, operation)()
            if operation in ('start', 'stop', 'toggle', 'status'):
                save_metadata['active'] = bool(result) if operation in ('toggle', 'status') else operation == 'start'
            if operation == 'toggle': return 'Replay buffer zapnut' if result else 'Replay buffer vypnut'
            if operation == 'status': return 'Replay buffer běží' if result else 'Replay buffer neběží'
            if operation == 'save':
                save_metadata['path'] = result
                return 'Klip uložen: ' + result
            return {'start': 'Replay buffer spuštěn', 'stop': 'Replay buffer zastaven', 'save': 'Požadavek na uložení odeslán OBS'}[operation]
        def finished(message):
            if 'path' in save_metadata:
                self.read_obs_provenance(save_metadata['path'], saved_track_names, url, password, clips_folder)
                if hasattr(self, 'obs_state_label'): self.obs_state_label.setText('Klip uložen · buffer běží')
                self.status.setText('Dokončuji uložený klip…')
                return
            if 'active' in save_metadata: self.set_obs_expected(save_metadata['active'], (url, password))
            if operation == 'save' and hasattr(self, 'obs_state_label'): self.obs_state_label.setText('Klip uložen · buffer běží')
            self.job_done(message)
        def failed(message):
            if hasattr(self, 'obs_state_label'):
                self.obs_state_label.setText('OBS se nepodařilo připojit')
            self.job_error(message)
        previous_state = self.obs_state_label.text() if hasattr(self, 'obs_state_label') else None
        if previous_state is not None: self.obs_state_label.setText('Připojuji se k OBS…')
        started = self.start_job(action, capture=True, on_done=finished, on_error=failed)
        if started and operation in ('start', 'stop', 'toggle'):
            self.obs_generation += 1
        elif not started and previous_state is not None:
            self.obs_state_label.setText(previous_state)
    def read_obs_provenance(self, path, names, url, password, clips_folder=''):
        """Finish naming and check optional metadata without blocking the next save."""
        self.obs_finalizing_paths.add(str(Path(path).resolve()))
        thread = QThread(self)
        def query():
            try: title = active_window_name() if clips_folder else ''
            except Exception: title = ''
            is_clipper = False
            try:
                client = OBSClient(url, password, 2)
                profile = client.request('GetProfileList').get('currentProfileName')
                collection = client.request('GetSceneCollectionList').get('currentSceneCollectionName')
                is_clipper = profile == PROFILE and collection == COLLECTION
            except Exception:
                pass  # A metadata lookup failure cannot invalidate an already saved clip.
            return json.dumps({'title': title, 'clipper': is_clipper}, ensure_ascii=False)
        worker = Job(query); worker.moveToThread(thread)
        job = (thread, worker); self.obs_metadata_jobs.add(job)
        def expose(saved_path, is_clipper):
            self.obs_finalizing_paths.discard(str(Path(path).resolve()))
            if is_clipper and Path(saved_path).is_file(): self.remember_mix(saved_path, names)
            if self.status.text() == 'Dokončuji uložený klip…': self.status.setText('Klip uložen: ' + saved_path)
            self.refresh()
            if self.tray: self.tray.showMessage('Clipper', 'Klip uložen: ' + Path(saved_path).name)
        def received(result):
            data = json.loads(result)
            saved_path = name_saved_replay(path, clips_folder, data['title']) if clips_folder else path
            expose(saved_path, data['clipper'])
        worker.finished.connect(received)
        worker.failed.connect(lambda _: expose(path, False))
        # Metadata is optional; an unavailable OBS must not invalidate a saved clip.
        for signal in (worker.finished, worker.failed):
            signal.connect(worker.deleteLater); signal.connect(thread.quit)
        def cleanup():
            self.obs_metadata_jobs.discard(job); thread.deleteLater()
            if self.quitting and not self.obs_metadata_jobs: self.close()
        thread.finished.connect(cleanup); thread.started.connect(worker.run); thread.start()

    def check_dependencies(self):
        from .diagnostics import diagnose
        url, password = self.obs_url.text().strip(), self.obs_password.text()
        def action(): return json.dumps(diagnose(url, password))
        def show_result(payload):
            results = json.loads(payload)
            lines = [f"{'✓' if ok else '✕'}  {name}: {detail}" for name, ok, detail in results]
            QMessageBox.information(self, 'Kontrola aplikace', '\n'.join(lines))
            self.status.setText('Kontrola aplikace dokončena.')
        self.start_job(action, on_done=show_result)
    def import_old(self):
        if not self.folder:
            QMessageBox.information(self, 'Import', 'Nejprve vyber složku klipů.'); return
        path, _ = QFileDialog.getOpenFileName(self, 'Původní config.json', '', 'JSON (*.json)')
        if not path: return
        try:
            imported, missing = import_legacy(self.library, path, self.folder)
            scale = valid_scale(self.library.setting('ui_scale', '1')) or 1
            self.ui_scale.setValue(round(scale * 100))
            self.refresh(); QMessageBox.information(self, 'Import dokončen', f'Načteno klipů: {imported}. Nenalezeno souborů: {missing}. Změna měřítka se projeví po restartu aplikace.')
        except Exception as exc: QMessageBox.warning(self, 'Import selhal', str(exc))
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Složka klipů', self.folder)
        if folder:
            old = self.watcher.directories()
            if old: self.watcher.removePaths(old)
            self.folder = folder; self.watcher.addPath(folder)
            self.library.set_setting('folder', folder); self.refresh()
            if hasattr(self, 'folder_hint'): self.folder_hint.setText('Ukládání do\n' + folder)
            if hasattr(self, 'settings_folder'): self.settings_folder.setText(folder)
    def search_changed(self, _query=None):
        self.current_page = 0
        self.refresh()
    def refresh(self):
        self.gallery_preview.stop()
        self.folder_label.setText(self.folder or 'Nebyla vybrána složka')
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()}
        current = self.list.currentItem(); current_key = current.data(Qt.ItemDataRole.UserRole) if current else None
        current_version = self.detail_version.currentData() if current else None
        scroll = self.list.verticalScrollBar().value()
        restored_current = None
        self.list.clear()
        files = self.library.scan(self.folder) if self.folder else []
        files = [path for path in files if str(path.resolve()) not in self.obs_finalizing_paths]
        query = self.search.text().casefold().strip()
        tag_colors = {name.casefold(): color for name, color in self.library.tags()}
        for name, versions in group_clips(files, self.library.versions()).items():
            paths = versions['original'] + versions['trim'] + versions['export']
            if not paths: continue
            primary = (versions['original'] or versions['trim'] or versions['export'])[0]
            tags = sorted({tag for path in paths for tag in self.library.tags_for(path)})
            if query and not any(query in path.name.casefold() for path in paths) and not any(query in tag.casefold() for tag in tags): continue
            card = QListWidgetItem(name); card.setData(Qt.ItemDataRole.UserRole, str(primary))
            card.setData(Qt.ItemDataRole.UserRole + 1, [(tag, tag_colors.get(tag.casefold(), '#ff7300')) for tag in tags])
            card.setData(Qt.ItemDataRole.UserRole + 2, {kind: [str(path) for path in versions[kind]] for kind in ('original', 'trim', 'export')})
            card.setData(Qt.ItemDataRole.UserRole + 3, name)
            self.list.addItem(card)
            if str(primary) in selected: card.setSelected(True)
            if str(primary) == current_key: restored_current = card
            thumb = self.thumbnails.request(primary)
            if thumb: card.setData(Qt.ItemDataRole.UserRole + 4, str(thumb))
            elif self.thumbnails.unavailable(primary): card.setData(Qt.ItemDataRole.UserRole + 5, True)
        if restored_current:
            self.list.setCurrentItem(restored_current)
            if current_version:
                version_index = self.detail_version.findData(current_version)
                if version_index >= 0: self.detail_version.setCurrentIndex(version_index)
        count = self.list.count()
        self.current_page = min(self.current_page, max(0, (count - 1) // self.page_size))
        self.update_gallery_page()
        self.list.setVisible(count > 0); self.empty_state.setVisible(count == 0)
        if count == 0:
            if not self.folder:
                self.empty_title.setText('Vyber složku s klipy')
                self.empty_message.setText('Zvol existující složku s videi, nebo přejdi na Nahrávání a vytvoř první klip.')
            elif self.search.text().strip():
                self.empty_title.setText('Žádný klip neodpovídá hledání')
                self.empty_message.setText('Zkus kratší název, jiný tag nebo vymaž hledání.')
            else:
                self.empty_title.setText('Tahle knihovna je zatím prázdná')
                self.empty_message.setText('Do zvolené složky zatím nepřibyl žádný podporovaný videosoubor.')
        if not restored_current: self.update_clip_details(self.list.currentItem())
        self.list.verticalScrollBar().setValue(scroll)
        self.update_grid_size()
    def update_gallery_page(self):
        total = self.list.count(); pages = max(1, (total + self.page_size - 1) // self.page_size)
        self.current_page = max(0, min(self.current_page, pages - 1))
        first, last = self.current_page * self.page_size, min(total, (self.current_page + 1) * self.page_size)
        for index in range(total):
            self.list.item(index).setHidden(index < first or index >= last)
        self.library_count.setText(f'{total} klipů' if total != 1 else '1 klip')
        self.page_prev.setEnabled(self.current_page > 0); self.page_next.setEnabled(self.current_page + 1 < pages)
        timestamps = []
        for index in range(first, last):
            value = self.list.item(index).data(Qt.ItemDataRole.UserRole)
            try: timestamps.append(datetime.fromtimestamp(Path(value).stat().st_mtime))
            except (OSError, TypeError, ValueError): pass
        self.library_dates.setText('  ·  '.join((timestamps[0].strftime('%d.%m.%Y'), timestamps[-1].strftime('%d.%m.%Y'))) if timestamps else '')
    def change_page(self, amount):
        self.gallery_preview.stop()
        pages = max(1, (self.list.count() + self.page_size - 1) // self.page_size)
        target = max(0, min(pages - 1, self.current_page + amount))
        if target == self.current_page: return
        self.current_page = target; self.list.verticalScrollBar().setValue(0); self.list.clearSelection()
        self.update_gallery_page(); self.update_clip_details(None)
    def update_grid_size(self):
        if not hasattr(self, 'list'): return
        # The original gallery centered its responsive card grid. Reset the margins
        # before measuring so a short final/single row does not shrink on each resize.
        self.list.setViewportMargins(0, 0, 0, 0)
        # Use the view's own width: viewport geometry can still reflect the previous
        # splitter size during resize, briefly producing a zero-width gallery.
        width = max(1, self.list.width() - 2 * self.list.frameWidth())
        columns = max(1, min(5, (width + 40) // 320))
        card_width = max(200, (width - (columns + 1) * 15) // columns)
        card_height = int(card_width * 9 / 16) + 42
        self.list.setGridSize(QSize(card_width, card_height))
        self.list.setIconSize(QSize(card_width - 12, int((card_width - 12) * 9 / 16)))
        self.list.setSpacing(0)
        count = sum(not self.list.item(i).isHidden() for i in range(self.list.count()))
        if 0 < count < columns:
            margin = max(0, (width - count * card_width) // 2)
            self.list.setViewportMargins(margin, 0, margin, 0)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'library_dates'):
            self.library_dates.setVisible(event.size().width() >= 1000)
            self.search.setFixedWidth(150 if event.size().width() < 900 else 210)
        if hasattr(self, 'list'): QTimer.singleShot(0, self.update_grid_size)
    def open_card_on_click(self, item):
        # A single click selects and reveals the details/actions pane; opening the
        # editor is explicit through the button, context menu, or double click.
        return
    def selection_details_changed(self):
        selected = self.list.selectedItems()
        if not selected:
            self.update_clip_details(None)
            return
        current = self.list.currentItem()
        self.update_clip_details(current if current in selected else selected[0])
    def update_clip_details(self, item):
        if item is None:
            self.details_panel.hide()
            QTimer.singleShot(0, self.update_grid_size)
            self.detail_path = None; self.detail_title.setText('Žádný klip není vybraný')
            self.detail_type.setText(''); self.detail_meta.setText('Kliknutím vyber klip. Dvojklik otevře editor.')
            self.detail_tags.setText(''); self.detail_thumbnail.setPixmap(QPixmap()); self.detail_thumbnail.setText('Vyber klip')
            self.detail_version.blockSignals(True); self.detail_version.clear(); self.detail_version.blockSignals(False); return
        was_hidden = self.details_panel.isHidden()
        self.details_panel.show()
        if was_hidden:
            width = max(1, self.browser_splitter.width())
            def resize_details():
                self.browser_splitter.setSizes([int(width * .69), int(width * .31)])
                self.update_grid_size()
            QTimer.singleShot(0, resize_details)
        value = item.data(Qt.ItemDataRole.UserRole)
        if not value: return
        self.detail_title.setText(item.data(Qt.ItemDataRole.UserRole + 3) or Path(value).stem)
        versions = item.data(Qt.ItemDataRole.UserRole + 2) or {}
        previous = self.detail_version.currentData()
        labels = {'original': 'Originál', 'trim': 'Střih bez rekomprese', 'export': 'Komprimovaný export'}
        self.detail_version.blockSignals(True); self.detail_version.clear()
        for kind in ('original', 'trim', 'export'):
            for index, filepath in enumerate(versions.get(kind, [])):
                path = Path(filepath); label = labels[kind] + (f' {index + 1}' if len(versions[kind]) > 1 else '')
                self.detail_version.addItem(label, filepath)
                self.detail_version.setItemData(self.detail_version.count()-1, kind, Qt.ItemDataRole.UserRole + 1)
        selected_index = self.detail_version.findData(previous) if previous else -1
        self.detail_version.setCurrentIndex(selected_index if selected_index >= 0 else 0); self.detail_version.blockSignals(False)
        self.show_detail_version()
    def detail_version_changed(self, index):
        if index >= 0: self.show_detail_version()
    def show_detail_version(self):
        path_value = self.detail_version.currentData()
        if not path_value: return
        path = Path(path_value); self.detail_path = path
        kind = self.detail_version.currentData(Qt.ItemDataRole.UserRole + 1)
        labels = {'original': 'Originál', 'trim': 'Střih bez rekomprese', 'export': 'Komprimovaný export'}
        self.detail_type.setText(labels.get(kind, 'Klip'))
        try:
            size = path.stat().st_size
            size_text = f'{size / (1024 * 1024):,.1f} MB'.replace(',', ' ')
            modified = __import__('datetime').datetime.fromtimestamp(path.stat().st_mtime).strftime('%d. %m. %Y  %H:%M')
            self.detail_meta.setText(f'{path.suffix.upper().lstrip(".")}  ·  {size_text}\n{modified}')
        except OSError: self.detail_meta.setText(path.suffix.upper().lstrip('.'))
        tags = self.library.tags_for(path)
        self.detail_tags.setText('🏷  ' + ('   ·   '.join(tags) if tags else 'Bez tagů'))
        image = self.thumbnails.request(path)
        if image and image.is_file():
            self.detail_thumbnail.setPixmap(QPixmap(str(image)).scaled(self.detail_thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); self.detail_thumbnail.setText('')
        else:
            self.detail_thumbnail.setPixmap(QPixmap())
            self.detail_thumbnail.setText('Náhled není dostupný' if self.thumbnails.unavailable(path) else 'Náhled se připravuje…' if path.is_file() else 'Soubor už není dostupný')
    def thumbnail_ready(self, path, image):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setData(Qt.ItemDataRole.UserRole + 4, image); item.setData(Qt.ItemDataRole.UserRole + 5, False); self.list.viewport().update(self.list.visualItemRect(item))
        if getattr(self, 'detail_path', None) and str(self.detail_path) == path:
            self.detail_thumbnail.setPixmap(QPixmap(image).scaled(self.detail_thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)); self.detail_thumbnail.setText('')
    def thumbnail_failed(self, path):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setData(Qt.ItemDataRole.UserRole + 5, True); self.list.viewport().update(self.list.visualItemRect(item))
        if getattr(self, 'detail_path', None) and str(self.detail_path) == path:
            self.detail_thumbnail.setPixmap(QPixmap()); self.detail_thumbnail.setText('Náhled není dostupný')
    def selected(self):
        item = self.list.currentItem()
        if item is None or not item.isSelected():
            item = self.list.selectedItems()[0] if self.list.selectedItems() else None
        value = self.detail_version.currentData() if item is self.list.currentItem() and item else item.data(Qt.ItemDataRole.UserRole) if item else None
        return Path(value) if value else None
    def selected_paths(self):
        paths = set()
        for item in self.list.selectedItems():
            versions = item.data(Qt.ItemDataRole.UserRole + 2) or {}
            paths.update(Path(path) for values in versions.values() for path in values)
        return sorted(paths)
    def context_menu(self, position):
        clicked = self.list.itemAt(position)
        if clicked and not clicked.isSelected():
            self.list.clearSelection(); clicked.setSelected(True); self.list.setCurrentItem(clicked)
        if not self.selected_paths(): return
        menu = QMenu(self)
        targets = self.list.selectedItems(); single = len(targets) == 1
        if single:
            card = targets[0]; versions = card.data(Qt.ItemDataRole.UserRole + 2) or {}
            menu.addAction('Otevřít umístění souboru', self.open_location)
            labels = {'original': 'Upravit originál', 'trim': 'Upravit střih', 'export': 'Zobrazit export'}
            for kind in ('original', 'trim', 'export'):
                for path in versions.get(kind, []):
                    action = menu.addAction(labels[kind] + (f' {versions[kind].index(path)+1}' if len(versions.get(kind, [])) > 1 else ''))
                    action.triggered.connect(lambda checked=False, p=path: self.open_version(p))
            menu.addAction('Přehrát', self.play)
            menu.addAction('Uložit střih…', self.make_trim)
            menu.addAction('Komprimovaný export…', self.make_export)
            if versions.get('export'):
                menu.addAction('Kopírovat export', self.copy_exports)
            menu.addSeparator()
        else:
            menu.addAction(f'Vybráno klipů: {len(targets)}').setEnabled(False)
            menu.addAction('Otevřít umístění souborů', self.open_location)
            menu.addAction('Kopírovat soubory', self.copy_files)
            if self.selected_export_paths(): menu.addAction('Kopírovat exporty', self.copy_exports)
            menu.addSeparator()
        tags_menu = menu.addMenu('Tagy')
        paths = self.selected_paths()
        path_tags = [{tag.casefold() for tag in self.library.tags_for(path)} for path in paths]
        available_tags = self.library.tags()
        for name, color in available_tags:
            count = sum(name.casefold() in tags for tags in path_tags)
            label = name + (' (část výběru)' if 0 < count < len(paths) else '')
            action = tags_menu.addAction(label)
            action.setCheckable(True); action.setChecked(count == len(paths))
            dot = QPixmap(14, 14); dot.fill(Qt.GlobalColor.transparent)
            painter = QPainter(dot); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color)); painter.drawEllipse(1, 1, 12, 12); painter.end()
            action.setIcon(QIcon(dot))
            action.triggered.connect(lambda checked, tag=name, selected=tuple(paths): self.set_paths_tag(selected, tag, checked))
        if available_tags: tags_menu.addSeparator()
        tags_menu.addAction('Přidat tag…', self.tag_selection)
        tags_menu.addAction('Odebrat tag…', self.untag_selection)
        menu.addSeparator()
        menu.addAction('Smazat vybrané soubory…', self.delete_selection)
        if single:
            versions = targets[0].data(Qt.ItemDataRole.UserRole + 2) or {}
            if versions.get('original') and versions.get('trim'):
                menu.addAction('Smazat originál (ponechat střih)…', lambda: self.delete_version(versions['original'][0], versions['trim']))
            for export_path in versions.get('export', []):
                menu.addAction('Smazat export…', lambda checked=False, p=export_path: self.delete_version(p))
        else:
            if self.selected_version_paths('original', require_trim=True):
                menu.addAction('Smazat originály (ponechat střihy)…', lambda: self.delete_selected_versions('original'))
            if self.selected_version_paths('export'):
                menu.addAction('Smazat exporty…', lambda: self.delete_selected_versions('export'))
        menu.exec(self.list.viewport().mapToGlobal(position))
    def open_version(self, path):
        index = self.detail_version.findData(str(path))
        if index >= 0: self.detail_version.setCurrentIndex(index)
        self.open_editor()
    def delete_version(self, path, required_trims=None):
        path = Path(path)
        if QMessageBox.question(self, 'Smazat verzi klipu', f'Smazat soubor {path.name}?') != QMessageBox.StandardButton.Yes: return
        if required_trims is not None and not any(Path(trim).is_file() for trim in required_trims):
            QMessageBox.warning(self, 'Mazání se nezdařilo', 'Střih už není dostupný; originál zůstal zachovaný.')
            return
        self.gallery_preview.stop()
        try:
            path.unlink(); self.library.forget_paths([path]); self.refresh()
        except OSError as exc: QMessageBox.warning(self, 'Mazání se nezdařilo', str(exc))
    def open_location(self):
        selected = self.selected(); paths = [selected] if selected else self.selected_paths()
        if paths: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0].parent)))
    def copy_files(self):
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path)) for path in self.selected_paths()])
        QApplication.clipboard().setMimeData(mime)
    def selected_export_paths(self):
        """Prefer explicitly selected exports, otherwise use each group's newest export."""
        paths = set()
        for item in self.list.selectedItems():
            exports = (item.data(Qt.ItemDataRole.UserRole + 2) or {}).get('export', [])
            if exports: paths.add(Path(exports[-1]))
        return sorted(paths)
    def selected_version_paths(self, kind, require_trim=False):
        paths = set()
        for item in self.list.selectedItems():
            versions = item.data(Qt.ItemDataRole.UserRole + 2) or {}
            if require_trim and not any(Path(path).is_file() for path in versions.get('trim', [])): continue
            paths.update(Path(path) for path in versions.get(kind, []))
        return sorted(paths)
    def copy_exports(self):
        paths = self.selected_export_paths()
        if not paths: return
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        QApplication.clipboard().setMimeData(mime)

    def tag_selection(self):
        paths = self.selected_paths()
        tag, ok = QInputDialog.getText(self, 'Přidat tag', 'Název tagu:')
        if ok and tag.strip():
            tag = tag.strip(); self.library.ensure_tag(tag)
            self.set_paths_tag(paths, tag, True)
    def untag_selection(self):
        paths = self.selected_paths()
        available = sorted({tag for path in paths for tag in self.library.tags_for(path)})
        if not available: return
        tag, ok = QInputDialog.getItem(self, 'Odebrat tag', 'Tag:', available, 0, False)
        if ok:
            self.set_paths_tag(paths, tag, False)
    def set_paths_tag(self, paths, tag, enabled):
        self.library.tag_clips(paths, tag, enabled)
        self.refresh()
    def delete_selection(self):
        paths = self.selected_paths()
        if not paths: return
        answer = QMessageBox.question(self, 'Smazat soubory', f'Trvale smazat {len(paths)} vybraných souborů?')
        if answer != QMessageBox.StandardButton.Yes: return
        self.delete_paths(paths)
    def delete_selected_versions(self, kind):
        if kind not in ('original', 'export'): return
        paths = self.selected_version_paths(kind, require_trim=(kind == 'original'))
        if not paths: return
        message = (f'Trvale smazat {len(paths)} originálních souborů? Střihy zůstanou zachované.'
                   if kind == 'original' else f'Trvale smazat {len(paths)} exportů?')
        if QMessageBox.question(self, 'Smazat verze klipů', message) != QMessageBox.StandardButton.Yes: return
        if kind == 'original':
            eligible = set(self.selected_version_paths('original', require_trim=True))
            paths = [path for path in paths if path in eligible]
        self.delete_paths(paths)
    def delete_paths(self, paths):
        self.gallery_preview.stop()
        errors, deleted = [], []
        for path in paths:
            try: path.unlink(); deleted.append(path)
            except OSError as exc: errors.append(f'{path.name}: {exc}')
        self.library.forget_paths(deleted)
        self.refresh()
        if errors: QMessageBox.warning(self, 'Některé soubory se nepodařilo smazat', '\n'.join(errors))
    def probe_selected(self, callback):
        path = self.selected()
        if not path: return
        def loaded(payload):
            try: callback(path, json.loads(payload))
            except Exception as exc: QMessageBox.warning(self, 'Video', str(exc))
        self.start_job(lambda: json.dumps(probe(path)), on_done=loaded)
    def open_editor(self):
        self.probe_selected(self.show_editor)
    def show_editor(self, path, info, autoplay=False):
        if self.active_editor is not None: return
        self.gallery_preview.stop()
        try:
            from .editor import Editor
            editor = Editor(path, self, info=info)
            editor.setWindowFlags(Qt.WindowType.Widget)
            self.active_editor = editor
            self.root_layout.insertWidget(0, editor, 1)
            editor.finished.connect(lambda result, current=editor: self.finish_editor(current, result))
            self.tabs.hide(); self.status_container.hide(); editor.show()
            if autoplay: QTimer.singleShot(0, editor.request_autoplay)
        except Exception as exc:
            self.active_editor = None
            QMessageBox.warning(self, 'Editor', str(exc))
    def finish_editor(self, editor, result):
        if editor is not self.active_editor: return
        path = editor.path
        operation = editor.operation if result == QDialog.DialogCode.Accepted else None
        values = editor.result_values() if operation else None
        self.root_layout.removeWidget(editor)
        editor.hide(); editor.deleteLater(); self.active_editor = None
        self.tabs.show()
        if self.status.text() or self.cancel_button.isEnabled(): self.status_container.show()
        self.refresh()
        if not operation or not values: return
        start, end, volumes, mix_first = values
        is_export = operation == 'export'; size = 10.0
        if is_export:
            size, ok = QInputDialog.getDouble(self, 'Export', 'Maximální velikost v MB:', 10, .1, 10000, 1)
            if not ok: return
        name = path.stem
        for suffix in ('_trim', '_export'):
            if name.endswith(suffix): name = name[:-len(suffix)]
        dest, _ = QFileDialog.getSaveFileName(self, 'Uložit jako', str(path.with_name(name + ('_export.mp4' if is_export else '_trim.mp4'))))
        if not dest: return
        if is_export:
            self.start_media_job(lambda progress, cancel: export(path, dest, start, end, size, volumes, progress=progress, cancellation=cancel), path, dest, kind='export')
        else:
            self.start_media_job(lambda progress, cancel: trim(path, dest, start, end, volumes, mix_first=mix_first, progress=progress, cancellation=cancel), path, dest, mix_first=mix_first)
    def play(self):
        # The editor mixes independent audio tracks and handles legacy premixes.
        # A standalone ffplay window would play only one selected stream.
        self.probe_selected(lambda path, info: self.show_editor(path, info, autoplay=True))
    def manage_tags(self):
        dialog = QDialog(self); dialog.setWindowTitle('Správa tagů'); dialog.resize(400, 360)
        layout = QVBoxLayout(dialog); items = QListWidget(); layout.addWidget(items)
        def refresh_tags():
            items.clear()
            from PyQt6.QtGui import QColor
            for name, color in self.library.tags():
                items.addItem(name); items.item(items.count()-1).setForeground(QColor(color))
        def create():
            name, ok = QInputDialog.getText(dialog, 'Nový tag', 'Název:')
            if not ok or not name.strip(): return
            color = QColorDialog.getColor(parent=dialog, title='Barva tagu')
            if color.isValid(): self.library.add_tag(name.strip(), color.name()); refresh_tags()
        def change_color():
            item = items.currentItem()
            if not item: return
            color = QColorDialog.getColor(parent=dialog, title='Barva tagu')
            if color.isValid(): self.library.add_tag(item.text(), color.name()); refresh_tags()
        def remove():
            item = items.currentItem()
            if not item: return
            if QMessageBox.question(dialog, 'Smazat tag', f'Smazat tag „{item.text()}“ ze všech klipů?') == QMessageBox.StandardButton.Yes:
                self.library.delete_tag(item.text()); refresh_tags()
        row = QHBoxLayout(); layout.addLayout(row)
        for title, callback in [('Přidat', create), ('Změnit barvu', change_color), ('Smazat', remove)]:
            button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        close = QPushButton('Hotovo'); close.clicked.connect(dialog.accept); layout.addWidget(close)
        refresh_tags(); dialog.exec(); self.refresh()
    def add_tag(self):
        p = self.selected()
        if not p: return
        tag, ok = QInputDialog.getText(self, 'Tag', 'Název tagu:')
        if ok and tag.strip():
            self.library.ensure_tag(tag); self.library.tag_clip(p, tag.strip()); self.refresh()
    def selection(self, is_export, path=None, info=None):
        p = Path(path) if path is not None else self.selected()
        if not p: return None
        try:
            if info is None: info = probe(p)
            length = duration(info)
        except Exception as e:
            QMessageBox.warning(self, 'Video', str(e)); return None
        dialog = QDialog(self); dialog.setWindowTitle('Nastavení exportu' if is_export else 'Nastavení střihu'); dialog.resize(620, 640)
        outer = QVBoxLayout(dialog); outer.setContentsMargins(20, 18, 20, 16); outer.setSpacing(12)
        heading = QLabel('Připravit komprimovaný export' if is_export else 'Vytvořit střih bez rekomprese')
        heading.setStyleSheet('font-size:19px;font-weight:700;color:#f4f6fb;'); outer.addWidget(heading)
        intro = QLabel('Nastav časový rozsah a hlasitost jednotlivých stop. Originální soubor zůstane zachovaný.')
        intro.setWordWrap(True); intro.setStyleSheet('color:#9da8ba;'); outer.addWidget(intro)
        content = QWidget(); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(4, 4, 4, 4); content_layout.setSpacing(10)
        range_group = QGroupBox('Rozsah klipu'); range_form = QFormLayout(range_group); content_layout.addWidget(range_group)
        start, end, size = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (start, end): spin.setRange(0, length); spin.setDecimals(2); spin.setSingleStep(.1); spin.setSuffix(' s'); spin.setMinimumHeight(38)
        end.setValue(length); size.setRange(0.1, 10000); size.setValue(10); size.setSuffix(' MB')
        range_form.addRow('Začátek', start); range_form.addRow('Konec', end)
        if is_export:
            size.setMinimumHeight(38); range_form.addRow('Cílová maximální velikost', size)
            size_help = QLabel('Výsledný soubor se přizpůsobí limitu, například 10 MB pro Discord.'); size_help.setWordWrap(True); size_help.setStyleSheet('color:#9da8ba;'); range_form.addRow(size_help)
        else:
            note = QLabel('Uloží se samostatný oříznutý soubor ve stejné kvalitě; originál zůstane nedotčený.')
            note.setWordWrap(True); note.setStyleSheet('color:#9da8ba;'); range_form.addRow(note)
        audio = {}
        saved_names = self.library.edit_for(p).get('track_names', [])
        if not isinstance(saved_names, list): saved_names = []
        saved_names = [name if isinstance(name, str) else '' for name in saved_names]
        audio_group = QGroupBox('Hlasitost zvukových stop'); audio_form = QFormLayout(audio_group); content_layout.addWidget(audio_group)
        for stream in info['streams']:
            if stream.get('codec_type') != 'audio': continue
            index = stream['index']
            volume = QDoubleSpinBox(); volume.setRange(0, 4); volume.setSingleStep(.1); volume.setValue(1); volume.setSuffix('×'); volume.setMinimumHeight(36)
            title = (saved_names[len(audio)] if len(audio) < len(saved_names) else '') or stream.get('tags', {}).get('title') or stream.get('tags', {}).get('name') or f'Stopa {index}'
            audio_form.addRow(f'{title}  ·  {stream.get("codec_name", "audio")}', volume)
            audio[index] = volume
        if not audio:
            audio_group.hide()
        mix_first = QCheckBox('První stopa je mix ostatních stop')
        saved_mix = self.library.edit_for(p).get('mix_first', first_track_is_named_mix(info))
        mix_first.setChecked(bool(saved_mix))
        if len(audio) > 1:
            mix_first.setToolTip('Použij, pokud první stopa již obsahuje smíchaný zvuk ostatních stop.')
            audio_form.addRow(mix_first)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Pokračovat…')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Zrušit')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); outer.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return None
        if start.value() >= end.value(): QMessageBox.warning(self, 'Výběr', 'Konec musí být za začátkem.'); return None
        stem = p.stem
        for suffix in ('_trim', '_export'):
            if stem.casefold().endswith(suffix): stem = stem[:-len(suffix)]
        suggested = str(p.with_name(stem + ('_export.mp4' if is_export else '_trim.mp4')))
        destination, _ = QFileDialog.getSaveFileName(self, 'Uložit jako', suggested)
        if not destination: return None
        levels = {i: spin.value() for i, spin in audio.items()}
        if is_export and mix_first.isChecked() and len(levels) > 1:
            first = next(iter(levels)); master = levels[first]; levels[first] = 0
            for index in list(levels)[1:]: levels[index] *= master
        return p, destination, start.value(), end.value(), size.value(), levels, mix_first.isChecked() and len(levels) > 1
    def make_trim(self):
        self.probe_selected(lambda path, info: self.quick_operation(False, path, info))
    def make_export(self):
        self.probe_selected(lambda path, info: self.quick_operation(True, path, info))
    def quick_operation(self, is_export, path, info):
        args = self.selection(is_export, path, info)
        if not args: return
        if is_export:
            self.start_media_job(lambda progress, cancel: export(*args[:5], volumes=args[5], progress=progress, cancellation=cancel), args[0], args[1], kind='export')
        else:
            self.start_media_job(lambda progress, cancel: trim(*args[:4], volumes=args[5], mix_first=args[6], progress=progress, cancellation=cancel), args[0], args[1], mix_first=args[6])
    def start_media_job(self, action, source, destination, kind='trim', mix_first=None):
        source = Path(source)
        related = [source]
        group_name = source.stem
        for name, versions in group_clips(self.library.scan(source.parent), self.library.versions()).items():
            paths = versions['original'] + versions['trim'] + versions['export']
            if source in paths:
                related = paths; group_name = name; break
        tags = {tag for path in related for tag in self.library.tags_for(path)}
        def finished(message):
            try:
                # Replacing a version invalidates edits and tags for its old contents.
                edit = {'mix_first': bool(mix_first)} if kind == 'trim' and mix_first is not None else {}
                source_names = self.library.edit_for(source).get('track_names')
                if kind == 'trim' and isinstance(source_names, list): edit['track_names'] = source_names
                self.library.replace_version_metadata(destination, group_name, kind, edit, tags)
            except Exception as exc:
                self.job_error('Video bylo uloženo, ale nepodařilo se uložit jeho údaje v knihovně: ' + str(exc)); return
            self.job_done(message)
        self.start_job(action, on_done=finished, with_progress=True)
    def start_job(self, action, capture=False, on_done=None, with_progress=False, on_error=None):
        thread_attr = 'capture_thread' if capture else 'thread'
        worker_attr = 'capture_worker' if capture else 'worker'
        current = getattr(self, thread_attr)
        if current and current.isRunning():
            message = 'Předchozí operace ještě probíhá. Nový požadavek nebyl proveden.'
            self.status.setText(message)
            if capture and self.tray:
                self.tray.showMessage('Clipper — požadavek neproveden', message, QSystemTrayIcon.MessageIcon.Warning)
            return False
        self.status.setText('Pracuji…')
        if with_progress: self.cancel_button.setEnabled(True); self.cancel_button.show()
        thread = QThread(self); worker = Job(action, with_progress); worker.moveToThread(thread)
        worker.progress.connect(lambda value: self.status.setText(f'Zpracovávám video… {value} %'))
        setattr(self, thread_attr, thread); setattr(self, worker_attr, worker)
        thread.started.connect(worker.run)
        outcome = {}
        worker.finished.connect(lambda message: outcome.update(callback=on_done or self.job_done, value=message))
        worker.failed.connect(lambda message: outcome.update(callback=on_error or self.job_error, value=message))
        worker.cancelled.connect(lambda: outcome.update(callback=lambda _: self.status.setText('Zpracování bylo zrušeno.'), value=''))
        for signal in (worker.finished, worker.failed, worker.cancelled):
            signal.connect(worker.deleteLater); signal.connect(thread.quit)
        def cleanup():
            if getattr(self, thread_attr) is thread:
                setattr(self, thread_attr, None); setattr(self, worker_attr, None)
                if with_progress: self.cancel_button.setEnabled(False); self.cancel_button.hide()
            thread.deleteLater()
            if outcome:
                try: outcome['callback'](outcome['value'])
                except Exception as exc: self.job_error(str(exc))
        thread.finished.connect(cleanup)
        thread.start()
        return True
    def cancel_media(self):
        worker = getattr(self, 'worker', None)
        if worker and worker.cancellation and worker.cancellation.cancel():
            self.cancel_button.setEnabled(False); self.cancel_button.hide()
            self.status.setText('Ruším zpracování…')
    def job_done(self, message):
        self.status.setText(message); self.refresh()
        if self.tray and message.startswith('Klip uložen:'): self.tray.showMessage('Clipper', message)
    def job_error(self, message):
        self.status.setText('Operace selhala: ' + message)
        if self.tray and not self.isVisible(): self.tray.showMessage('Clipper — chyba', message[:200], QSystemTrayIcon.MessageIcon.Warning)
        else: QMessageBox.warning(self, 'Chyba', message)
    def closeEvent(self, event):
        if self.tray and self.tray.isVisible() and not self.quitting:
            self.hide(); event.ignore(); return
        if any(thread is not None for thread in (self.thread, self.capture_thread)):
            QMessageBox.information(self, 'Práce probíhá', 'Počkej na dokončení zpracování.'); event.ignore(); return
        if self.obs_metadata_jobs:
            self.quitting = True
            self.status.setText('Čekám na dokončení kontroly údajů klipů…'); event.ignore(); return
        self.preview_timer.stop()
        self.obs_health_timer.stop()
        if self.obs_preview_worker and self.obs_preview_worker.isRunning():
            self.obs_preview_worker.requestInterruption()
            if not getattr(self, 'closing_after_preview', False):
                self.closing_after_preview = True
                self.obs_preview_worker.finished.connect(self.close)
            self.status.setText('Ukončuji náhled OBS…'); event.ignore(); return
        if self.screen_preview_worker and self.screen_preview_worker.isRunning():
            if not getattr(self, 'closing_after_screen_preview', False):
                self.closing_after_screen_preview = True
                self.screen_preview_worker.finished.connect(self.close)
            self.status.setText('Ukončuji náhled obrazovky…'); event.ignore(); return
        if self.obs_health_thread is not None:
            if not self.closing_after_health:
                self.closing_after_health = True
                self.obs_health_thread.finished.connect(self.close)
            self.status.setText('Čekám na ukončení kontroly OBS…'); event.ignore(); return
        self.recorder.stop()
        self.stop_hotkeys()
        if self.portal_hotkeys:
            self.portal_hotkeys.requestInterruption()
            if not self.portal_hotkeys.wait(7000):
                self.status.setText('Čekám na ukončení systémových zkratek.'); event.ignore(); return
        if self.active_editor is not None:
            self.active_editor.reject()
        self.gallery_preview.stop()
        self.record_timer.stop(); self.refresh_timer.stop()
        if self.tray: self.tray.hide()
        self.thumbnails.shutdown()
        self.library.close(); event.accept()

def main():
    apply_saved_scale()
    app = QApplication(sys.argv); window = Window(); window.show(); return app.exec()
if __name__ == '__main__': sys.exit(main())
