# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from app_logging import setup_logging


LOG_FILE = setup_logging()
logger = logging.getLogger(__name__)
logger.info("Application bootstrap started. Log file: %s", LOG_FILE)

INTERACTIVE_PREVIEW_MAX_SIZE = 4096
DISPLAY_PREVIEW_MAX_SIDE = 8192
APP_ICON_PATH = Path(__file__).resolve().parent / "Logo.ico"


try:
    import numpy as np
    from PIL import Image
except Exception:
    logger.exception("Application startup failed while importing preview dependencies")
    raise

try:
    from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QImage, QPixmap, QTransform
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSlider,
        QSplitter,
        QSpinBox,
        QStyle,
        QTableWidget,
        QTableWidgetItem,
        QToolBar,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except Exception:
    logger.exception("Application startup failed while importing PySide6")
    raise

try:
    from inkcalc import DEFAULT_DPI, DEFAULT_OUTPUT_ROOT, CoverageResult, calculate_sources_coverage, first_supported_file_near_script, terminate_active_ghostscript_processes
    from halftone import (
        DEFAULT_SCREEN_FREQUENCY,
        SCREEN_MODE_AM,
        SCREEN_MODE_FM,
        SCREEN_MODE_HYBRID,
        SCREEN_MODE_FLEXO,
        SCREEN_MODE_ERROR_DIFFUSION,
        SCREEN_MODE_NONE,
        default_screen_angle,
    )
    from gpu_halftone import compute_backend_name
    from ppd_profiles import PpdProfile, discover_ppd_profiles, parse_ppd
    from rip_core import layers_from_dicts, render_preview
except Exception:
    logger.exception("Application startup failed while importing calculation modules")
    raise


class CalculationWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, source_paths: list[Path], dpi: int, output_root: Path) -> None:
        super().__init__()
        self.source_paths = source_paths
        self.dpi = dpi
        self.output_root = output_root

    def run(self) -> None:
        try:
            logger.info("Worker started: sources=%s dpi=%s output_root=%s", self.source_paths, self.dpi, self.output_root)
            result = calculate_sources_coverage(
                self.source_paths,
                dpi=self.dpi,
                output_root=self.output_root,
                progress=self.progress.emit,
            )
        except Exception as exc:
            logger.exception("Worker failed during calculation")
            self.failed.emit(str(exc))
            return
        logger.info("Worker finished successfully")
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Color Separation Workstation")
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1280, 800)

        self.thread: QThread | None = None
        self.worker: CalculationWorker | None = None
        self.last_result: CoverageResult | None = None
        self.preview_layers: list[dict[str, object]] = []
        self.layer_checkboxes: list[QCheckBox] = []
        self.preview_zoom = 1.0
        self.preview_pixmap: QPixmap | None = None
        self.preview_rotation = 0
        self.ppd_profiles = discover_ppd_profiles(Path(__file__).resolve().parent)
        self.profile_sync_in_progress = False
        self.preview_render_pending = False
        self.preview_render_timer = QTimer(self)
        self.preview_render_timer.setSingleShot(True)
        self.preview_render_timer.timeout.connect(self.render_preview)

        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Выберите PDF, PS или EPS. Для нескольких файлов используйте кнопку Обзор...")

        default_source = first_supported_file_near_script()
        if default_source:
            self.source_input.setText(str(default_source))
            logger.info("Default input file selected on startup: %s", default_source)

        self.output_input = QLineEdit(str(DEFAULT_OUTPUT_ROOT))
        self.dpi_input = QSpinBox()
        self.dpi_input.setRange(72, 4800)
        self.dpi_input.setSingleStep(50)
        self.dpi_input.setAccelerated(True)
        self.dpi_input.setMinimumWidth(110)
        self.dpi_input.setValue(DEFAULT_DPI)

        self.status_label = QLabel("Готово")
        self.status_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.status_label.setMinimumHeight(24)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Канал", "Покрытие, %"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self.on_layer_changed)
        self.layer_list.setMinimumHeight(150)

        self.move_layer_up_button = QPushButton("▲")
        self.move_layer_up_button.setToolTip("Поднять канал")
        self.move_layer_up_button.clicked.connect(self.move_selected_layer_up)
        self.move_layer_down_button = QPushButton("▼")
        self.move_layer_down_button.setToolTip("Опустить канал")
        self.move_layer_down_button.clicked.connect(self.move_selected_layer_down)

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.clicked.connect(self.zoom_out_preview)
        self.zoom_reset_button = QPushButton("100%")
        self.zoom_reset_button.clicked.connect(self.reset_preview_zoom)
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.clicked.connect(self.zoom_in_preview)

        self.screen_mode_input = QComboBox()
        self.screen_mode_input.addItem("Без растра", SCREEN_MODE_NONE)
        self.screen_mode_input.addItem("Офсетный AM", SCREEN_MODE_AM)
        self.screen_mode_input.addItem("Флексо AM", SCREEN_MODE_FLEXO)
        self.screen_mode_input.addItem("Стохастика FM", SCREEN_MODE_FM)
        self.screen_mode_input.addItem("Error diffusion", SCREEN_MODE_ERROR_DIFFUSION)
        self.screen_mode_input.addItem("Гибридный XM", SCREEN_MODE_HYBRID)
        self.screen_mode_input.currentIndexChanged.connect(lambda _index: self.schedule_render_preview())

        self.profile_input = QComboBox()
        self.profile_input.addItem("Вручную", None)
        for profile in self.ppd_profiles:
            self.profile_input.addItem(profile.name, profile)
        self.profile_input.currentIndexChanged.connect(self.on_profile_changed)

        self.load_profile_button = QPushButton("…")
        self.load_profile_button.setToolTip("Загрузить PPD")
        self.load_profile_button.clicked.connect(self.choose_ppd_profile)

        self.spot_shape_input = QComboBox()
        self._set_default_spot_shapes()
        self.spot_shape_input.currentIndexChanged.connect(lambda _index: self.schedule_render_preview())

        self.screen_frequency_input = QSpinBox()
        self.screen_frequency_input.setRange(20, 400)
        self.screen_frequency_input.setSingleStep(5)
        self.screen_frequency_input.setAccelerated(True)
        self.screen_frequency_input.setMinimumWidth(110)
        self.screen_frequency_input.setValue(DEFAULT_SCREEN_FREQUENCY)
        self.screen_frequency_input.valueChanged.connect(self.on_screen_settings_changed)
        self.dpi_input.valueChanged.connect(self.on_screen_settings_changed)
        self.compute_backend_label = QLabel(compute_backend_name())

        self.preview_label = QLabel("Предпросмотр появится после расчёта")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_label.setStyleSheet("background: #ffffff;")

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setObjectName("canvasScroll")
        self.preview_scroll.setWidget(self.preview_label)

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.clicked.connect(self.start_calculation)

        self.open_output_button = QPushButton("Открыть папку")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_dir)

        self._build_layout()
        self._build_toolbar()
        self._apply_style()
        logger.info("Main window initialized")

    def _build_layout(self) -> None:
        root = QWidget()
        root.setObjectName("workspaceRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setHandleWidth(1)

        canvas_panel = QWidget()
        canvas_panel.setObjectName("canvasPanel")
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        canvas_layout.addWidget(self.preview_scroll, 1)

        right_scroll = QScrollArea()
        right_scroll.setObjectName("inspectorScroll")
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_panel = QWidget()
        right_panel.setObjectName("inspectorPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 8)
        right_layout.setSpacing(6)

        navigator_group = QGroupBox("Навигатор")
        navigator_layout = QVBoxLayout(navigator_group)
        navigator_layout.setContentsMargins(6, 8, 6, 6)
        self.navigator_label = QLabel("Нет документа")
        self.navigator_label.setObjectName("navigatorPreview")
        self.navigator_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.navigator_label.setFixedHeight(150)
        navigator_layout.addWidget(self.navigator_label)
        navigator_zoom = QHBoxLayout()
        self.navigator_zoom_out = self._icon_button("−", "Уменьшить", self.zoom_out_preview)
        self.navigator_zoom_in = self._icon_button("+", "Увеличить", self.zoom_in_preview)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 600)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(lambda value: self.set_preview_zoom(value / 100.0, sync_slider=False))
        self.zoom_percent_label = QLabel("100%")
        self.zoom_percent_label.setFixedWidth(44)
        self.zoom_percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        navigator_zoom.addWidget(self.navigator_zoom_out)
        navigator_zoom.addWidget(self.zoom_slider, 1)
        navigator_zoom.addWidget(self.navigator_zoom_in)
        navigator_zoom.addWidget(self.zoom_percent_label)
        navigator_layout.addLayout(navigator_zoom)

        view_group = QGroupBox("Вид")
        view_layout = QHBoxLayout(view_group)
        view_layout.setContentsMargins(6, 8, 6, 6)
        view_layout.addWidget(self._icon_button("□", "Вписать страницу", self.fit_preview))
        view_layout.addWidget(self._icon_button("1:1", "Масштаб 100%", self.reset_preview_zoom))
        view_layout.addWidget(self._icon_button("↶", "Повернуть влево", self.rotate_preview_left))
        view_layout.addWidget(self._icon_button("↷", "Повернуть вправо", self.rotate_preview_right))
        view_layout.addStretch(1)

        channels_group = QGroupBox("Каналы")
        channels_layout = QVBoxLayout(channels_group)
        channels_layout.setContentsMargins(6, 8, 6, 6)
        channel_tools = QHBoxLayout()
        channel_tools.addWidget(self.move_layer_up_button)
        channel_tools.addWidget(self.move_layer_down_button)
        channel_tools.addStretch(1)
        channels_layout.addLayout(channel_tools)
        channels_layout.addWidget(self.layer_list)

        screening_group = QGroupBox("Растрирование")
        screening_form = QFormLayout(screening_group)
        screening_form.setContentsMargins(6, 10, 6, 6)
        screening_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.profile_input, 1)
        profile_row.addWidget(self.load_profile_button)
        screening_form.addRow("Профиль", profile_row)
        screening_form.addRow("Алгоритм", self.screen_mode_input)
        screening_form.addRow("Точка", self.spot_shape_input)
        screening_form.addRow("Линиатура", self.screen_frequency_input)
        screening_form.addRow("DPI", self.dpi_input)
        screening_form.addRow("Backend", self.compute_backend_label)

        job_group = QGroupBox("Задание")
        job_layout = QGridLayout(job_group)
        job_layout.setContentsMargins(6, 10, 6, 6)
        browse_source_button = self._icon_button("…", "Выбрать PDF, PS или EPS", self.choose_sources)
        browse_output_button = self._icon_button("…", "Выбрать папку вывода", self.choose_output_root)
        job_layout.addWidget(QLabel("Файл"), 0, 0)
        job_layout.addWidget(self.source_input, 0, 1)
        job_layout.addWidget(browse_source_button, 0, 2)
        job_layout.addWidget(QLabel("Вывод"), 1, 0)
        job_layout.addWidget(self.output_input, 1, 1)
        job_layout.addWidget(browse_output_button, 1, 2)
        job_actions = QHBoxLayout()
        job_actions.addWidget(self.open_output_button)
        job_actions.addStretch(1)
        job_actions.addWidget(self.calculate_button)
        job_layout.addLayout(job_actions, 2, 0, 1, 3)

        coverage_group = QGroupBox("Покрытие")
        coverage_layout = QVBoxLayout(coverage_group)
        coverage_layout.setContentsMargins(4, 8, 4, 4)
        self.table.setMinimumHeight(130)
        coverage_layout.addWidget(self.table)

        info_group = QGroupBox("Информация")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(8, 10, 8, 8)
        self.document_info_label = QLabel("Документ не рассчитан")
        self.document_info_label.setWordWrap(True)
        info_layout.addWidget(self.document_info_label)

        right_layout.addWidget(navigator_group)
        right_layout.addWidget(view_group)
        right_layout.addWidget(channels_group)
        right_layout.addWidget(screening_group)
        right_layout.addWidget(job_group)
        right_layout.addWidget(coverage_group)
        right_layout.addWidget(info_group)
        right_layout.addStretch(1)
        right_scroll.setWidget(right_panel)

        workspace.addWidget(canvas_panel)
        workspace.addWidget(right_scroll)
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 0)
        workspace.setSizes([1100, 330])
        right_scroll.setMinimumWidth(310)
        right_scroll.setMaximumWidth(390)

        root_layout.addWidget(workspace, 1)
        root_layout.addWidget(self.status_label)
        self.setCentralWidget(root)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Инструменты", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        style = self.style()
        actions = (
            (QStyle.StandardPixmap.SP_DialogOpenButton, "Открыть файл", self.choose_sources),
            (QStyle.StandardPixmap.SP_MediaPlay, "Рассчитать", self.start_calculation),
            (None, None, None),
            (QStyle.StandardPixmap.SP_ArrowDown, "Уменьшить", self.zoom_out_preview),
            (QStyle.StandardPixmap.SP_ArrowUp, "Увеличить", self.zoom_in_preview),
            (QStyle.StandardPixmap.SP_BrowserReload, "Вписать страницу", self.fit_preview),
            (None, None, None),
            (QStyle.StandardPixmap.SP_ArrowBack, "Повернуть влево", self.rotate_preview_left),
            (QStyle.StandardPixmap.SP_ArrowForward, "Повернуть вправо", self.rotate_preview_right),
            (None, None, None),
            (QStyle.StandardPixmap.SP_DialogApplyButton, "Открыть папку вывода", self.open_output_dir),
        )
        for icon_id, tooltip, callback in actions:
            if icon_id is None:
                toolbar.addSeparator()
                continue
            action = QAction(style.standardIcon(icon_id), tooltip, self)
            action.setToolTip(tooltip)
            action.triggered.connect(callback)
            toolbar.addAction(action)

    def _icon_button(self, text: str, tooltip: str, callback: object) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFixedSize(28, 26)
        button.clicked.connect(callback)
        return button
    def _apply_style(self) -> None:
        self.setFont(QFont("Segoe UI", 9))
        self.setStyleSheet(
            """
            QMainWindow, #workspaceRoot { background: #ececec; }
            QToolBar#mainToolbar {
                background: #f7f7f7;
                border: 0;
                border-bottom: 1px solid #b9b9b9;
                spacing: 2px;
                padding: 3px 6px;
            }
            QToolBar#mainToolbar QToolButton {
                width: 28px;
                height: 26px;
                border: 1px solid transparent;
                border-radius: 2px;
                padding: 1px;
            }
            QToolBar#mainToolbar QToolButton:hover { background: #e2edf6; border-color: #9cb8ce; }
            #canvasPanel, QScrollArea#canvasScroll, QScrollArea#canvasScroll > QWidget > QWidget {
                background: #55585b;
                border: 0;
            }
            QLabel#canvasImage { background: #ffffff; border: 1px solid #8d8d8d; }
            QScrollArea#inspectorScroll { background: #efefef; border: 0; border-left: 1px solid #b8b8b8; }
            QWidget#inspectorPanel { background: #efefef; }
            QGroupBox {
                background: #f8f8f8;
                border: 1px solid #bfc3c7;
                border-radius: 0;
                margin-top: 17px;
                padding-top: 4px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 0;
                top: 0;
                padding: 2px 7px;
                background: #dfe2e5;
                border-bottom: 1px solid #bfc3c7;
                width: 100%;
            }
            QLabel#navigatorPreview { background: #d2d4d6; border: 1px solid #aeb3b8; color: #666666; }
            QLineEdit, QSpinBox, QComboBox {
                min-height: 23px;
                border: 1px solid #aeb4ba;
                border-radius: 1px;
                padding: 1px 4px;
                background: #ffffff;
            }
            QPushButton {
                min-height: 25px;
                border: 1px solid #aeb4ba;
                border-radius: 2px;
                padding: 2px 8px;
                background: #f7f7f7;
            }
            QPushButton:hover, QToolButton:hover { background: #e4eef6; border-color: #8eafc7; }
            QPushButton:disabled { color: #999999; background: #e6e6e6; }
            QToolButton { border: 1px solid #adb3b8; background: #f9f9f9; border-radius: 1px; }
            QListWidget, QTableWidget {
                background: #ffffff;
                border: 1px solid #b8bdc2;
                gridline-color: #d7dade;
                selection-background-color: #cce7f6;
                selection-color: #151515;
            }
            QListWidget::item { min-height: 28px; border-bottom: 1px solid #e3e3e3; }
            QCheckBox { spacing: 7px; }
            QCheckBox::indicator { width: 15px; height: 15px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 22px; border-left: 1px solid #aeb5bb; background: #f5f7f8; }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e3eef7; }
            QHeaderView::section { background: #e2e5e8; border: 0; border-right: 1px solid #c3c7ca; padding: 3px; }
            QSlider::groove:horizontal { height: 3px; background: #c1c5c8; }
            QSlider::handle:horizontal { width: 10px; margin: -5px 0; background: #8e969d; border: 1px solid #6f777d; }
            QLabel { color: #24282b; }
            """
        )
    def _set_default_spot_shapes(self) -> None:
        self.spot_shape_input.blockSignals(True)
        self.spot_shape_input.clear()
        self.spot_shape_input.addItem("Круглая", "circle")
        self.spot_shape_input.addItem("Эллиптическая", "ellipse")
        self.spot_shape_input.addItem("Квадратная", "square")
        self.spot_shape_input.addItem("Линейная", "line")
        self.spot_shape_input.blockSignals(False)

    def choose_ppd_profile(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Загрузить профиль RIP", "", "PPD (*.ppd *.PPD)")
        if not file_name:
            return
        try:
            profile = parse_ppd(Path(file_name))
        except Exception as exc:
            logger.exception("User PPD profile could not be loaded: %s", file_name)
            QMessageBox.critical(self, "Ошибка PPD", str(exc))
            return
        self.ppd_profiles.append(profile)
        self.profile_input.addItem(profile.name, profile)
        self.profile_input.setCurrentIndex(self.profile_input.count() - 1)
        logger.info("User loaded PPD profile: %s", file_name)

    def current_ppd_profile(self) -> PpdProfile | None:
        profile = self.profile_input.currentData()
        return profile if isinstance(profile, PpdProfile) else None

    def on_profile_changed(self, _value: int = 0) -> None:
        profile = self.current_ppd_profile()
        self.profile_sync_in_progress = True
        try:
            self.spot_shape_input.blockSignals(True)
            self.spot_shape_input.clear()
            if profile is None:
                for label, code in (("Круглая", "circle"), ("Эллиптическая", "ellipse"), ("Квадратная", "square"), ("Линейная", "line")):
                    self.spot_shape_input.addItem(label, code)
            else:
                for _ppd_code, label, engine_code in profile.dot_shapes:
                    self.spot_shape_input.addItem(label, engine_code)
                if profile.default_resolution:
                    self.dpi_input.setValue(profile.default_resolution)
                frequencies = profile.frequencies_for_dpi(self.dpi_input.value())
                if frequencies:
                    self.screen_frequency_input.setValue(int(min(frequencies, key=lambda value: abs(value - self.screen_frequency_input.value()))))
            self.spot_shape_input.blockSignals(False)
            self.apply_profile_screens()
        finally:
            self.profile_sync_in_progress = False
        logger.info("RIP profile selected: %s", profile.name if profile else "manual")
        self.schedule_render_preview()

    def on_screen_settings_changed(self, _value: int = 0) -> None:
        if self.profile_sync_in_progress:
            return
        profile = self.current_ppd_profile()
        if profile is not None:
            frequencies = profile.frequencies_for_dpi(self.dpi_input.value())
            if frequencies and self.screen_frequency_input.value() not in frequencies:
                self.profile_sync_in_progress = True
                self.screen_frequency_input.setValue(int(min(frequencies, key=lambda value: abs(value - self.screen_frequency_input.value()))))
                self.profile_sync_in_progress = False
            self.apply_profile_screens()
        self.schedule_render_preview()

    def apply_profile_screens(self) -> None:
        profile = self.current_ppd_profile()
        if profile is None:
            for layer in self.preview_layers:
                layer["frequency_lpi"] = layer.get("source_frequency_lpi")
                layer["angle_deg"] = layer.get("source_angle_deg")
        else:
            specs = profile.screen_specs(self.dpi_input.value(), float(self.screen_frequency_input.value()))
            for layer in self.preview_layers:
                plate_name = str(layer["name"]).strip().upper()
                plate_key = {
                    "CYAN": "C",
                    "MAGENTA": "M",
                    "YELLOW": "Y",
                    "BLACK": "K",
                }.get(plate_name, plate_name)
                spec = specs.get(plate_key) or specs.get("Spot")
                if spec is not None:
                    layer["frequency_lpi"] = spec.frequency_lpi
                    layer["angle_deg"] = spec.angle_deg
        self.refresh_layer_labels()

    def refresh_layer_labels(self) -> None:
        for row, layer in enumerate(self.preview_layers):
            if row < len(self.layer_checkboxes):
                self.layer_checkboxes[row].setText(f"{layer['name']}  {float(layer.get('angle_deg') or 0):g}°")
            item = self.layer_list.item(row)
            if item is not None:
                item.setData(Qt.ItemDataRole.DisplayRole, f"{layer['name']}  {float(layer.get('angle_deg') or 0):g}°")

    def choose_sources(self) -> None:
        logger.info("User opened input file chooser")
        file_names, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите PDF, PS или EPS",
            "",
            "PDF/PostScript (*.pdf *.ps *.eps);;PDF (*.pdf);;PostScript (*.ps *.eps)",
        )
        if file_names:
            self.source_input.setText("; ".join(file_names))
            logger.info("User selected input files: %s", file_names)
        else:
            logger.info("User cancelled input file chooser")

    def choose_output_root(self) -> None:
        logger.info("User opened output directory chooser")
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку вывода", self.output_input.text())
        if directory:
            self.output_input.setText(directory)
            logger.info("User selected output directory: %s", directory)
        else:
            logger.info("User cancelled output directory chooser")

    def start_calculation(self) -> None:
        source_paths = self.parse_source_paths()
        output_root = Path(self.output_input.text().strip())
        dpi = self.dpi_input.value()
        logger.info("User started calculation: sources=%s dpi=%s output_root=%s", source_paths, dpi, output_root)

        if not source_paths:
            logger.warning("Calculation blocked: no input files selected")
            QMessageBox.warning(self, "Файлы не выбраны", "Выберите хотя бы один PDF, PS или EPS.")
            return

        missing_paths = [path for path in source_paths if not path.exists()]
        if missing_paths:
            logger.warning("Calculation blocked: selected input files do not exist: %s", missing_paths)
            QMessageBox.warning(self, "Файл не найден", f"Файл не найден:\n{missing_paths[0]}")
            return

        self.set_busy(True)
        self.table.setRowCount(0)
        self.status_label.setText("Запуск расчёта...")

        self.thread = QThread(self)
        self.worker = CalculationWorker(source_paths, dpi, output_root)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_worker)
        self.thread.start()

    def on_finished(self, result: CoverageResult) -> None:
        logger.info(
            "Calculation completed in GUI: sources=%s output_dir=%s plates=%s",
            result.source_paths,
            result.output_dir,
            {plate.name: round(plate.percent, 4) for plate in result.plates},
        )
        self.last_result = result
        self.table.setRowCount(len(result.plates))
        for row, plate in enumerate(result.plates):
            name_item = QTableWidgetItem(plate.name)
            percent_item = QTableWidgetItem(f"{plate.percent:.2f}")
            percent_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, percent_item)
        self.setup_preview_layers(result)
        self.status_label.setText(f"Готово. Файлы цветоделения: {result.output_dir}")
        self.open_output_button.setEnabled(True)
        self.set_busy(False)

    def on_failed(self, message: str) -> None:
        logger.error("Calculation failed in GUI: %s", message)
        self.status_label.setText("Ошибка")
        self.set_busy(False)
        QMessageBox.critical(self, "Ошибка расчёта", message)

    def cleanup_worker(self) -> None:
        logger.info("Cleaning up worker thread")
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def closeEvent(self, event: object) -> None:
        logger.info("Application window closing; terminating active Ghostscript processes")
        terminate_active_ghostscript_processes()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(event)

    def set_busy(self, busy: bool) -> None:
        self.calculate_button.setEnabled(not busy)
        self.source_input.setEnabled(not busy)
        self.output_input.setEnabled(not busy)
        self.dpi_input.setEnabled(not busy)
        self.layer_list.setEnabled(not busy)
        self.move_layer_up_button.setEnabled(not busy)
        self.move_layer_down_button.setEnabled(not busy)
        self.zoom_out_button.setEnabled(not busy)
        self.zoom_reset_button.setEnabled(not busy)
        self.zoom_in_button.setEnabled(not busy)
        self.screen_mode_input.setEnabled(not busy)
        self.screen_frequency_input.setEnabled(not busy)
        self.profile_input.setEnabled(not busy)
        self.load_profile_button.setEnabled(not busy)
        self.spot_shape_input.setEnabled(not busy)

    def open_output_dir(self) -> None:
        if self.last_result:
            logger.info("User opened output directory: %s", self.last_result.output_dir)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result.output_dir)))
        else:
            logger.warning("User tried to open output directory before calculation result exists")

    def parse_source_paths(self) -> list[Path]:
        raw_value = self.source_input.text().strip()
        if not raw_value:
            return []
        return [Path(item.strip().strip('"')) for item in raw_value.split(";") if item.strip()]

    def setup_preview_layers(self, result: CoverageResult) -> None:
        self.preview_layers = []
        for plate in result.plates:
            if not plate.tiff_path or not plate.tiff_path.exists():
                logger.warning("Preview layer skipped because TIFF is missing: %s", plate)
                continue
            screen_spec = result.screen_specs.get(plate.name)
            frequency = screen_spec.frequency_lpi if screen_spec else None
            angle = screen_spec.angle_deg if screen_spec else default_screen_angle(plate.name)
            layer = {
                "name": plate.name,
                "path": plate.tiff_path,
                "enabled": True,
                "frequency_lpi": frequency,
                "angle_deg": angle,
                "source_frequency_lpi": frequency,
                "source_angle_deg": angle,
            }
            self.preview_layers.append(layer)
        self.rebuild_layer_list()
        self.preview_zoom = 1.0
        self.render_preview()
        self.fit_preview()

    def rebuild_layer_list(self) -> None:
        self.layer_checkboxes = []
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for row, layer in enumerate(self.preview_layers):
            angle = float(layer.get("angle_deg") or 0)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.DisplayRole, f"{layer['name']}  {angle:g}°")
            item.setSizeHint(QSize(240, 28))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.layer_list.addItem(item)
            self.layer_list.setItemWidget(item, self.create_layer_widget(row))
        self.layer_list.blockSignals(False)

    def create_layer_widget(self, row: int) -> QWidget:
        layer = self.preview_layers[row]
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(6)

        checkbox = QCheckBox(f"{layer['name']}  {float(layer.get('angle_deg') or 0):g}°")
        checkbox.setChecked(bool(layer.get("enabled", True)))
        checkbox.toggled.connect(lambda checked, cb=checkbox: self.on_layer_checkbox_toggled(cb, checked))
        self.layer_checkboxes.append(checkbox)

        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        color = QColor(*preview_ink_rgb(str(layer["name"])))
        swatch.setStyleSheet(f"background: {color.name()}; border: 1px solid #7e858b;")

        layout.addWidget(checkbox, 1)
        layout.addWidget(swatch)
        return widget

    def on_layer_checkbox_toggled(self, checkbox: QCheckBox, checked: bool) -> None:
        try:
            row = self.layer_checkboxes.index(checkbox)
        except ValueError:
            return
        self.layer_list.setCurrentRow(row)
        if 0 <= row < len(self.preview_layers):
            self.preview_layers[row]["enabled"] = checked
            logger.info("Preview layer toggled: %s enabled=%s", self.preview_layers[row]["name"], checked)
            self.schedule_render_preview()

    def on_layer_changed(self, item: QListWidgetItem) -> None:
        row = self.layer_list.row(item)
        if 0 <= row < len(self.preview_layers):
            self.schedule_render_preview()

    def move_selected_layer_up(self) -> None:
        self.move_selected_layer(-1)

    def move_selected_layer_down(self) -> None:
        self.move_selected_layer(1)

    def move_selected_layer(self, direction: int) -> None:
        row = self.layer_list.currentRow()
        new_row = row + direction
        if row < 0 or new_row < 0 or new_row >= len(self.preview_layers):
            return
        self.preview_layers[row], self.preview_layers[new_row] = self.preview_layers[new_row], self.preview_layers[row]
        self.rebuild_layer_list()
        self.layer_list.setCurrentRow(new_row)
        logger.info("Preview layer moved: from=%s to=%s", row, new_row)
        self.schedule_render_preview()

    def zoom_in_preview(self) -> None:
        self.set_preview_zoom(self.preview_zoom * 1.25)

    def zoom_out_preview(self) -> None:
        self.set_preview_zoom(self.preview_zoom / 1.25)

    def reset_preview_zoom(self) -> None:
        self.set_preview_zoom(1.0)

    def set_preview_zoom(self, zoom: float, sync_slider: bool = True) -> None:
        max_zoom = 6.0
        if self.preview_pixmap is not None and not self.preview_pixmap.isNull():
            if self.preview_rotation % 180:
                max_side = max(self.preview_pixmap.height(), self.preview_pixmap.width())
            else:
                max_side = max(self.preview_pixmap.width(), self.preview_pixmap.height())
            if max_side > 0:
                max_zoom = min(max_zoom, max(0.1, DISPLAY_PREVIEW_MAX_SIDE / max_side))
        self.preview_zoom = min(max_zoom, max(0.1, zoom))
        percent = int(round(self.preview_zoom * 100))
        self.zoom_reset_button.setText(f"{percent}%")
        if hasattr(self, "zoom_percent_label"):
            self.zoom_percent_label.setText(f"{percent}%")
        if sync_slider and hasattr(self, "zoom_slider"):
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(percent)
            self.zoom_slider.blockSignals(False)
        logger.info("Preview zoom changed: %.2f", self.preview_zoom)
        self.apply_preview_zoom()

    def fit_preview(self) -> None:
        if self.preview_pixmap is None:
            return
        source_size = self.preview_pixmap.size()
        if self.preview_rotation % 180:
            source_width, source_height = source_size.height(), source_size.width()
        else:
            source_width, source_height = source_size.width(), source_size.height()
        viewport = self.preview_scroll.viewport().size()
        zoom = min((viewport.width() - 28) / source_width, (viewport.height() - 28) / source_height)
        self.set_preview_zoom(min(1.0, zoom))

    def rotate_preview_left(self) -> None:
        self.preview_rotation = (self.preview_rotation - 90) % 360
        self.apply_preview_zoom()

    def rotate_preview_right(self) -> None:
        self.preview_rotation = (self.preview_rotation + 90) % 360
        self.apply_preview_zoom()

    def update_navigator(self, pixmap: QPixmap | None = None) -> None:
        if not hasattr(self, "navigator_label"):
            return
        source = pixmap or self.preview_pixmap
        if source is None or source.isNull():
            self.navigator_label.setText("Нет документа")
            self.navigator_label.setPixmap(QPixmap())
            return
        thumbnail = source.scaled(
            self.navigator_label.size() - QSize(12, 12),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.navigator_label.setText("")
        self.navigator_label.setPixmap(thumbnail)

    def update_document_info(self, result: CoverageResult) -> None:
        dimensions = "Размер: —"
        first_tiff = next((plate.tiff_path for plate in result.plates if plate.tiff_path and plate.tiff_path.exists()), None)
        if first_tiff:
            with Image.open(first_tiff) as image:
                width_mm = image.width / self.dpi_input.value() * 25.4
                height_mm = image.height / self.dpi_input.value() * 25.4
                dimensions = f"Размер: {width_mm:.2f} × {height_mm:.2f} мм"
        self.document_info_label.setText(
            f"{dimensions}\nРазрешение: {self.dpi_input.value()} dpi\n"
            f"Каналов: {len(result.plates)}\nФайл: {result.source_paths[0].name}"
        )


    def schedule_render_preview(self, delay_ms: int = 250) -> None:
        if not self.preview_layers:
            return
        self.preview_render_pending = True
        self.status_label.setText("Обновление предпросмотра...")
        self.preview_render_timer.start(delay_ms)

    def render_preview(self) -> None:
        self.preview_render_pending = False
        enabled_layers = [layer for layer in self.preview_layers if layer.get("enabled")]
        if not enabled_layers:
            self.preview_label.setText("Все каналы выключены")
            self.preview_label.setPixmap(QPixmap())
            self.preview_pixmap = None
            return

        try:
            preview = build_preview_image(
                enabled_layers,
                max_size=INTERACTIVE_PREVIEW_MAX_SIZE,
                dpi=self.dpi_input.value(),
                screen_mode=str(self.screen_mode_input.currentData()),
                fallback_frequency_lpi=float(self.screen_frequency_input.value()),
                spot_shape=str(self.spot_shape_input.currentData()),
            )
        except Exception:
            logger.exception("Failed to render separation preview")
            self.preview_label.setText("Не удалось построить предпросмотр")
            self.preview_label.setPixmap(QPixmap())
            self.preview_pixmap = None
            return

        qimage = pil_image_to_qimage(preview)
        self.preview_pixmap = QPixmap.fromImage(qimage)
        self.apply_preview_zoom()
        if self.last_result:
            self.status_label.setText(f"Готово. Файлы цветоделения: {self.last_result.output_dir}")

    def apply_preview_zoom(self) -> None:
        if self.preview_pixmap is None:
            return
        displayed = self.preview_pixmap
        if self.preview_rotation:
            displayed = displayed.transformed(
                QTransform().rotate(self.preview_rotation),
                Qt.TransformationMode.SmoothTransformation,
            )
        target_size = QSize(
            max(1, int(displayed.width() * self.preview_zoom)),
            max(1, int(displayed.height() * self.preview_zoom)),
        )
        scaled = displayed.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation
            if self.screen_mode_input.currentData() != SCREEN_MODE_NONE
            else Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())
        self.update_navigator(displayed)


def preview_ink_rgb(name: str) -> tuple[int, int, int]:
    process_colors = {
        "C": (0, 174, 239),
        "CYAN": (0, 174, 239),
        "M": (236, 0, 140),
        "MAGENTA": (236, 0, 140),
        "Y": (255, 221, 0),
        "YELLOW": (255, 221, 0),
        "K": (30, 30, 30),
        "BLACK": (30, 30, 30),
    }
    normalized = name.strip().upper()
    if normalized in process_colors:
        return process_colors[normalized]

    pantone_colors = {
        "PANTONE 281 C": (0, 32, 91),
        "PANTONE 349 C": (4, 106, 56),
        "PANTONE 354 C": (0, 177, 64),
        "PANTONE 485 C": (218, 41, 28),
        "PANTONE 7587 C": (146, 71, 42),
    }
    compact = re.sub(r"\s+", " ", normalized.replace("PMS", "PANTONE")).strip()
    compact = re.sub(r"^(PANTONE) (\d+)([A-Z])$", r"\1 \2 \3", compact)
    if compact in pantone_colors:
        return pantone_colors[compact]

    number_match = re.search(r"(?:PANTONE|PMS)\s*(\d+)", compact)
    if number_match:
        number = int(number_match.group(1))
        if 100 <= number <= 149:
            return (246, 218, 58)
        if 150 <= number <= 179:
            return (235, 132, 39)
        if 180 <= number <= 249:
            return (207, 38, 58)
        if 250 <= number <= 269:
            return (149, 72, 155)
        if 270 <= number <= 299:
            return (40, 84, 160)
        if 300 <= number <= 329:
            return (0, 130, 173)
        if 330 <= number <= 399:
            return (0, 135, 85)
        if 400 <= number <= 449:
            return (116, 107, 98)
        if 450 <= number <= 499:
            return (143, 78, 48)
        if 500 <= number <= 549:
            return (112, 88, 134)
        if 550 <= number <= 599:
            return (100, 148, 145)
        if 600 <= number <= 699:
            return (214, 116, 152)
        if 700 <= number <= 799:
            return (219, 97, 47)
        if 7400 <= number <= 7499:
            return (204, 151, 44)
        if 7500 <= number <= 7599:
            return (151, 91, 54)
        if 7600 <= number <= 7699:
            return (154, 64, 69)
        if 7700 <= number <= 7799:
            return (0, 134, 155)
        return (125, 125, 125)

    seed = sum(ord(ch) for ch in name)
    return ((seed * 37) % 156 + 50, (seed * 67) % 156 + 50, (seed * 97) % 156 + 50)


def build_preview_image(
    layers: list[dict[str, object]],
    max_size: int = 8192,
    dpi: int = DEFAULT_DPI,
    screen_mode: str = SCREEN_MODE_NONE,
    fallback_frequency_lpi: float = DEFAULT_SCREEN_FREQUENCY,
    spot_shape: str = "circle",
) -> Image.Image:
    return render_preview(
        layers_from_dicts(layers),
        color_resolver=preview_ink_rgb,
        max_size=max_size,
        dpi=dpi,
        screen_mode=screen_mode,
        fallback_frequency_lpi=fallback_frequency_lpi,
        spot_shape=spot_shape,
    )

def effective_preview_dpi(document_dpi: float, preview_scale: float) -> float:
    return max(1.0, float(document_dpi) * float(preview_scale))


def pil_image_to_qimage(image: Image.Image) -> QImage:
    rgb_image = image.convert("RGB")
    data = rgb_image.tobytes("raw", "RGB")
    qimage = QImage(data, rgb_image.width, rgb_image.height, rgb_image.width * 3, QImage.Format.Format_RGB888)
    return qimage.copy()


def main() -> int:
    logger.info("Application startup sequence entered")
    try:
        app = QApplication(sys.argv)
        logger.info("QApplication created")
        window = MainWindow()
        window.show()
        logger.info("Main window shown")
        exit_code = app.exec()
    except Exception:
        logger.exception("Application startup or event loop failed")
        raise
    logger.info("Application closed with exit code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
