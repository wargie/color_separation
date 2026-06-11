# Калькулятор покрытия краской

Windows-приложение для расчёта среднего покрытия PDF по CMYK и spot-краскам.

## Что нужно установить

1. Python 3.11 или 3.12.
2. Ghostscript для Windows. После установки команда `gswin64c` должна быть доступна в `PATH`.
3. Python-зависимости:

```powershell
py -m pip install -r requirements.txt
```

## Запуск GUI

```powershell
py app.py
```

В окне можно выбрать PDF, папку вывода, DPI и запустить расчёт. TIFF-сепарации сохраняются в папку `Separation`.

## Консольный запуск

```powershell
py newcalc.py
```

Консольный режим берёт первый PDF рядом со скриптом и выводит проценты покрытия в терминал.

## Сборка exe

После установки PyInstaller:

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconsole --onefile --name InkCoverageCalc app.py
```

Готовый файл появится в папке `dist`.
