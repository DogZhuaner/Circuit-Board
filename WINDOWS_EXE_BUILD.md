# Windows EXE 打包说明

当前程序入口文件是 `compare_nodes_ui.py`。

## 打包步骤

1. 在 Windows 电脑上安装 Python 3。
2. 安装时勾选 `Add python.exe to PATH`。
3. 把整个项目文件夹复制到 Windows 电脑。
4. 双击运行 `build_windows_exe.bat`。
5. 打包完成后，可执行文件在：

```text
dist\compare_nodes_ui.exe
```

## 说明

- 生成的 `compare_nodes_ui.exe` 是单文件程序，可以复制到其他 Windows 电脑直接运行。
- 最终用户运行 `compare_nodes_ui.exe` 时不需要再安装 Python。
- 首次打包时需要联网安装 PyInstaller。
- 如果杀毒软件提示风险，通常是 PyInstaller 单文件程序的误报，可改用可信环境重新打包。
