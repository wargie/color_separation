# -*- coding: utf-8 -*-

from __future__ import annotations

from inkcalc import DEFAULT_DPI, DEFAULT_OUTPUT_ROOT, calculate_pdf_coverage, first_pdf_near_script


def main() -> None:
    pdf_path = first_pdf_near_script()
    if not pdf_path:
        print("Не найден *.pdf рядом со скриптом.")
        return

    try:
        result = calculate_pdf_coverage(pdf_path, dpi=DEFAULT_DPI, output_root=DEFAULT_OUTPUT_ROOT)
    except Exception as exc:
        print(f"[ERR] {exc}")
        return

    print(f"Файл: {result.pdf_path}")
    print(f"Папка цветоделения: {result.output_dir}")
    print("Покрытие в %:")
    for plate in result.plates:
        print(f"  {plate.name}: {plate.percent:.2f}")


if __name__ == "__main__":
    main()
