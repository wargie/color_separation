# -*- coding: utf-8 -*-

from __future__ import annotations

import logging

from app_logging import setup_logging
from inkcalc import DEFAULT_DPI, DEFAULT_OUTPUT_ROOT, calculate_pdf_coverage, first_supported_file_near_script


logger = logging.getLogger(__name__)


def main() -> None:
    log_file = setup_logging()
    logger.info("Console calculation started. Log file: %s", log_file)

    source_path = first_supported_file_near_script()
    if not source_path:
        logger.warning("Console calculation stopped: no PDF/PS/EPS near script")
        print("Не найден *.pdf, *.ps или *.eps рядом со скриптом.")
        return

    try:
        result = calculate_pdf_coverage(source_path, dpi=DEFAULT_DPI, output_root=DEFAULT_OUTPUT_ROOT)
    except Exception as exc:
        logger.exception("Console calculation failed")
        print(f"[ERR] {exc}")
        return

    logger.info("Console calculation finished successfully: %s", result.source_paths)
    print("Файлы:")
    for source in result.source_paths:
        print(f"  {source}")
    print(f"Папка цветоделения: {result.output_dir}")
    print("Покрытие в %:")
    for plate in result.plates:
        print(f"  {plate.name}: {plate.percent:.2f}")


if __name__ == "__main__":
    main()
