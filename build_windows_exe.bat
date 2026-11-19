@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ========================================
echo 触点对 JSON 比对 - Windows EXE 打包
echo ========================================
echo.

if exist compare_nodes_ui.py (
    echo 找到 compare_nodes_ui.py
) else (
    echo 错误：当前目录没有 compare_nodes_ui.py
    echo 请把本脚本放在 compare_nodes_ui.py 同一个目录下运行。
    pause
    exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY_CMD=python"
    ) else (
        echo 错误：未找到 Python。
        echo 请先安装 Windows 版 Python 3，并勾选 Add python.exe to PATH。
        pause
        exit /b 1
    )
)

echo.
echo 检查 Python 和 tkinter...
%PY_CMD% -c "import tkinter; print('tkinter OK')" || (
    echo.
    echo 错误：当前 Python 缺少 tkinter，无法打包这个界面程序。
    pause
    exit /b 1
)

echo.
echo 安装/更新 PyInstaller...
%PY_CMD% -m pip install --upgrade pyinstaller || (
    echo.
    echo 错误：PyInstaller 安装失败。
    pause
    exit /b 1
)

echo.
echo 清理旧的打包输出...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo 开始打包...
%PY_CMD% -m PyInstaller --clean --noconfirm compare_nodes_ui_windows.spec || (
    echo.
    echo 错误：打包失败。
    pause
    exit /b 1
)

echo.
if exist dist\compare_nodes_ui.exe (
    echo 打包完成：
    echo %cd%\dist\compare_nodes_ui.exe
    echo.
    echo 可以把 dist\compare_nodes_ui.exe 复制到其他 Windows 电脑上直接运行。
) else (
    echo 错误：没有找到 dist\compare_nodes_ui.exe
    pause
    exit /b 1
)

echo.
pause
