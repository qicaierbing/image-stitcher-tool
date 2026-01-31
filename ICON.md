# 自定义软件图标说明

## 如何添加自定义图标

### 1. 准备图标文件

- **格式**：ICO 格式（推荐）或 PNG 格式
- **尺寸**：建议使用 256x256 或 512x512 像素
- **位置**：将图标文件命名为 `app_icon.ico`（或 `app_icon.png`）并放在项目根目录下

### 2. 方法一：修改代码（推荐用于打包 EXE）

1. 将您的图标文件命名为 `app_icon.ico`
2. 放在 `d:\myexe\pintu\` 目录下
3. 编辑 `build_exe.py`，找到注释部分并取消注释：

```python
# 如果有图标文件，取消下面的注释并修改路径
if icon_file and os.path.exists(icon_file):
    options.append('--icon=' + icon_file)
```

改为：

```python
# 如果有图标文件，取消下面的注释并修改路径
icon_file = "app_icon.ico"
if icon_file and os.path.exists(icon_file):
    options.append('--icon=' + icon_file)
```

4. 重新打包：`python build_exe.py`

### 3. 方法二：为运行中的程序设置图标

1. 编辑 `main.py`
2. 找到 `main()` 函数
3. 添加以下代码：

```python
if os.path.exists('app_icon.ico'):
    app.setWindowIcon(QIcon('app_icon.ico'))
```

### 4. 在线图标生成工具

如果只有 PNG 图片，可以使用以下工具转换为 ICO：

- https://convertico.com/
- https://icoconvert.com/
- https://www.icoconverter.com/

## 快速开始

1. 准备一个 256x256 的 PNG 图片
2. 使用在线工具转换为 ICO 格式
3. 保存为 `app_icon.ico`
4. 修改 `build_exe.py` 添加图标
5. 重新打包 EXE

## 注意事项

- 确保图标文件路径正确
- 打包后的 EXE 会自动包含图标
- 运行时设置图标需要图标文件在程序目录下
