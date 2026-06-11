# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from inkcalc import DEFAULT_DPI, DEFAULT_OUTPUT_ROOT, CoverageResult, calculate_pdf_coverage, first_pdf_near_script


class CalculationWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, pdf_path: Path, dpi: int, output_root: Path) -> None:
        super().__init__()
        self.pdf_path = pdf_path
        self.dpi = dpi
        self.output_root = output_root

    def run(self) -> None:
        try:
            result = calculate_pdf_coverage(
                self.pdf_path,
                dpi=self.dpi,
                output_root=self.output_root,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Калькулятор покрытия краской")
        self.resize(820, 520)

        self.thread: QThread | None = None
        self.worker: CalculationWorker | None = None
        self.last_result: CoverageResult | None = None

        self.pdf_input = QLineEdit()
        self.pdf_input.setPlaceholderText("Выберите PDF-файл")

        default_pdf = first_pdf_near_script()
        if default_pdf:
            self.pdf_input.setText(str(default_pdf))

        self.output_input = QLineEdit(str(DEFAULT_OUTPUT_ROOT))
        self.dpi_input = QSpinBox()
        self.dpi_input.setRange(72, 2400)
        self.dpi_input.setSingleStep(50)
        self.dpi_input.setValue(DEFAULT_DPI)

        self.status_label = QLabel("Готово")
        self.status_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.status_label.setMinimumHeight(32)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Канал", "Тип", "Покрытие, %"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.clicked.connect(self.start_calculation)

        self.open_output_button = QPushButton("Открыть папку")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_dir)

        self._build_layout()
        self._apply_style()

    def _build_layout(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        file_group = QGroupBox("Файл и параметры")
        file_layout = QGridLayout(file_group)

        browse_pdf_button = QPushButton("Обзор...")
        browse_pdf_button.clicked.connect(self.choose_pdf)
        browse_output_button = QPushButton("Обзор...")
        browse_output_button.clicked.connect(self.choose_output_root)

        file_layout.addWidget(QLabel("PDF"), 0, 0)
        file_layout.addWidget(self.pdf_input, 0, 1)
        file_layout.addWidget(browse_pdf_button, 0, 2)
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
        layout.addWidget(self.table, 1)
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

    def choose_pdf(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Выберите PDF", "", "PDF (*.pdf)")
        if file_name:
            self.pdf_input.setText(file_name)

    def choose_output_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку вывода", self.output_input.text())
        if directory:
            self.output_input.setText(directory)

    def start_calculation(self) -> None:
        pdf_path = Path(self.pdf_input.text().strip())
        output_root = Path(self.output_input.text().strip())

        if not pdf_path.exists():
            QMessageBox.warning(self, "Файл не найден", "Выберите существующий PDF-файл.")
            return

        self.set_busy(True)
        self.table.setRowCount(0)
        self.status_label.setText("Запуск расчёта...")

        self.thread = QThread(self)
        self.worker = CalculationWorker(pdf_path, self.dpi_input.value(), output_root)
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
        self.last_result = result
        self.table.setRowCount(len(result.plates))
        for row, plate in enumerate(result.plates):
            name_item = QTableWidgetItem(plate.name)
            kind_item = QTableWidgetItem(plate.kind)
            percent_item = QTableWidgetItem(f"{plate.percent:.2f}")
            percent_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, kind_item)
            self.table.setItem(row, 2, percent_item)
        self.status_label.setText(f"Готово. Файлы цветоделения: {result.output_dir}")
        self.open_output_button.setEnabled(True)
        self.set_busy(False)

    def on_failed(self, message: str) -> None:
        self.status_label.setText("Ошибка")
        self.set_busy(False)
        QMessageBox.critical(self, "Ошибка расчёта", message)

    def cleanup_worker(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def set_busy(self, busy: bool) -> None:
        self.calculate_button.setEnabled(not busy)
        self.pdf_input.setEnabled(not busy)
        self.output_input.setEnabled(not busy)
        self.dpi_input.setEnabled(not busy)

    def open_output_dir(self) -> None:
        if self.last_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result.output_dir)))


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
