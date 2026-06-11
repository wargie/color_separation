# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app_logging import setup_logging


LOG_FILE = setup_logging()
logger = logging.getLogger(__name__)
logger.info("Application bootstrap started. Log file: %s", LOG_FILE)

try:
    import numpy as np
    from PIL import Image
except Exception:
    logger.exception("Application startup failed while importing preview dependencies")
    raise

try:
    from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices, QFont, QImage, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
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
        QSplitter,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception:
    logger.exception("Application startup failed while importing PySide6")
    raise

try:
    from inkcalc import DEFAULT_DPI, DEFAULT_OUTPUT_ROOT, CoverageResult, calculate_sources_coverage, first_supported_file_near_script
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
        self.setWindowTitle("Калькулятор покрытия краской")
        self.resize(820, 520)

        self.thread: QThread | None = None
        self.worker: CalculationWorker | None = None
        self.last_result: CoverageResult | None = None
        self.preview_layers: list[dict[str, object]] = []

        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Выберите PDF, PS или EPS. Для нескольких файлов используйте кнопку Обзор...")

        default_source = first_supported_file_near_script()
        if default_source:
            self.source_input.setText(str(default_source))
            logger.info("Default input file selected on startup: %s", default_source)

        self.output_input = QLineEdit(str(DEFAULT_OUTPUT_ROOT))
        self.dpi_input = QSpinBox()
        self.dpi_input.setRange(72, 2400)
        self.dpi_input.setSingleStep(50)
        self.dpi_input.setValue(DEFAULT_DPI)

        self.status_label = QLabel("Готово")
        self.status_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.status_label.setMinimumHeight(32)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Канал", "Покрытие, %"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self.on_layer_changed)

        self.move_layer_up_button = QPushButton("Вверх")
        self.move_layer_up_button.clicked.connect(self.move_selected_layer_up)
        self.move_layer_down_button = QPushButton("Вниз")
        self.move_layer_down_button.clicked.connect(self.move_selected_layer_down)

        self.preview_label = QLabel("Предпросмотр появится после расчёта")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(360, 260)
        self.preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_label.setStyleSheet("background: #ffffff;")

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.clicked.connect(self.start_calculation)

        self.open_output_button = QPushButton("Открыть папку")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_dir)

        self._build_layout()
        self._apply_style()
        logger.info("Main window initialized")

    def _build_layout(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        file_group = QGroupBox("Файл и параметры")
        file_layout = QGridLayout(file_group)

        browse_source_button = QPushButton("Обзор...")
        browse_source_button.clicked.connect(self.choose_sources)
        browse_output_button = QPushButton("Обзор...")
        browse_output_button.clicked.connect(self.choose_output_root)

        file_layout.addWidget(QLabel("Файлы"), 0, 0)
        file_layout.addWidget(self.source_input, 0, 1)
        file_layout.addWidget(browse_source_button, 0, 2)
        file_layout.addWidget(QLabel("Папка вывода"), 1, 0)
        file_layout.addWidget(self.output_input, 1, 1)
        file_layout.addWidget(browse_output_button, 1, 2)

        dpi_form = QFormLayout()
        dpi_form.addRow("DPI", self.dpi_input)
        file_layout.addLayout(dpi_form, 2, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.open_output_button)
        actions.addWidget(self.calculate_button)

        layout.addWidget(file_group)

        result_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.table, 1)

        preview_group = QGroupBox("Просмотр цветоделения")
        preview_layout = QVBoxLayout(preview_group)
        layer_actions = QHBoxLayout()
        layer_actions.addWidget(self.move_layer_up_button)
        layer_actions.addWidget(self.move_layer_down_button)
        preview_layout.addWidget(self.layer_list, 1)
        preview_layout.addLayout(layer_actions)
        preview_layout.addWidget(self.preview_label, 3)

        result_splitter.addWidget(left_panel)
        result_splitter.addWidget(preview_group)
        result_splitter.setStretchFactor(0, 2)
        result_splitter.setStretchFactor(1, 3)

        layout.addWidget(result_splitter, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(actions)
        self.setCentralWidget(root)

    def _apply_style(self) -> None:
        app_font = QFont("Segoe UI", 10)
        self.setFont(app_font)
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f6f8; }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d8dee6;
                border-radius: 6px;
                margin-top: 10px;
                padding: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QSpinBox {
                min-height: 28px;
                border: 1px solid #c8d0da;
                border-radius: 4px;
                padding: 3px 6px;
                background: #ffffff;
            }
            QPushButton {
                min-height: 30px;
                border: 1px solid #b8c2cc;
                border-radius: 4px;
                padding: 4px 12px;
                background: #ffffff;
            }
            QPushButton:hover { background: #eef4fb; }
            QPushButton:disabled { color: #8a95a3; background: #edf0f3; }
            QTableWidget {
                background: #ffffff;
                border: 1px solid #d8dee6;
                gridline-color: #e1e6ec;
                selection-background-color: #d8eaff;
            }
            QLabel {
                color: #1f2933;
            }
            """
        )

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

    def set_busy(self, busy: bool) -> None:
        self.calculate_button.setEnabled(not busy)
        self.source_input.setEnabled(not busy)
        self.output_input.setEnabled(not busy)
        self.dpi_input.setEnabled(not busy)
        self.layer_list.setEnabled(not busy)
        self.move_layer_up_button.setEnabled(not busy)
        self.move_layer_down_button.setEnabled(not busy)

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
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for plate in result.plates:
            if not plate.tiff_path or not plate.tiff_path.exists():
                logger.warning("Preview layer skipped because TIFF is missing: %s", plate)
                continue
            layer = {"name": plate.name, "path": plate.tiff_path, "enabled": True}
            self.preview_layers.append(layer)
            item = QListWidgetItem(plate.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)
        self.render_preview()

    def on_layer_changed(self, item: QListWidgetItem) -> None:
        row = self.layer_list.row(item)
        if 0 <= row < len(self.preview_layers):
            self.preview_layers[row]["enabled"] = item.checkState() == Qt.CheckState.Checked
            logger.info("Preview layer toggled: %s enabled=%s", self.preview_layers[row]["name"], self.preview_layers[row]["enabled"])
            self.render_preview()

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
        item = self.layer_list.takeItem(row)
        self.layer_list.insertItem(new_row, item)
        self.layer_list.setCurrentRow(new_row)
        logger.info("Preview layer moved: from=%s to=%s", row, new_row)
        self.render_preview()

    def render_preview(self) -> None:
        enabled_layers = [layer for layer in self.preview_layers if layer.get("enabled")]
        if not enabled_layers:
            self.preview_label.setText("Все каналы выключены")
            self.preview_label.setPixmap(QPixmap())
            return

        try:
            preview = build_preview_image(enabled_layers)
        except Exception:
            logger.exception("Failed to render separation preview")
            self.preview_label.setText("Не удалось построить предпросмотр")
            self.preview_label.setPixmap(QPixmap())
            return

        qimage = pil_image_to_qimage(preview)
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)


def preview_color(name: str) -> tuple[int, int, int]:
    colors = {
        "C": (0, 174, 239),
        "M": (236, 0, 140),
        "Y": (255, 242, 0),
        "K": (0, 0, 0),
    }
    if name in colors:
        return colors[name]
    seed = sum(ord(ch) for ch in name)
    return ((seed * 37) % 206 + 25, (seed * 67) % 206 + 25, (seed * 97) % 206 + 25)


def build_preview_image(layers: list[dict[str, object]], max_size: int = 1200) -> Image.Image:
    base_size: tuple[int, int] | None = None
    composite: np.ndarray | None = None

    for layer in layers:
        image = Image.open(Path(layer["path"])).convert("L")
        if base_size is None:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            base_size = image.size
            composite = np.full((base_size[1], base_size[0], 3), 255.0, dtype=np.float32)
        elif image.size != base_size:
            image = image.resize(base_size, Image.Resampling.LANCZOS)

        coverage = (255.0 - np.asarray(image, dtype=np.float32)) / 255.0
        color = np.asarray(preview_color(str(layer["name"])), dtype=np.float32)
        composite = composite * (1.0 - coverage[..., None]) + color * coverage[..., None]

    if composite is None:
        return Image.new("RGB", (600, 400), "white")
    return Image.fromarray(np.clip(composite, 0, 255).astype(np.uint8), "RGB")


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
