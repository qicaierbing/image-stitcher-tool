import sys
import json
import os
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFileDialog, 
                             QProgressBar, QTabWidget, QFrame, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QIcon, QDesktopServices
from PyQt6.QtCore import QUrl
from PIL import Image
import pillow_heif
import subprocess

# 注册 HEIF 支持
pillow_heif.register_heif_opener()

# 设置 Pillow 的最大像素限制（增大到更大的值）
Image.MAX_IMAGE_PIXELS = None


def open_folder(path):
    """打开文件夹"""
    try:
        if os.path.exists(path):
            if os.name == 'nt':  # Windows
                subprocess.Popen(f'explorer "{os.path.normpath(path)}"')
            elif os.name == 'posix':  # macOS and Linux
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
    except Exception as e:
        print(f"打开文件夹失败: {e}")


class StitchWorker(QThread):
    """拼接图像的工作线程"""
    progress_updated = pyqtSignal(int)
    batch_progress = pyqtSignal(int, int, int)  # batch_index, total_batches, progress
    finished = pyqtSignal(bool, str, list)  # success, message, output_files
    
    def __init__(self, image_paths, output_path):
        super().__init__()
        self.image_paths = image_paths
        self.output_path = output_path
    
    def run(self):
        try:
            output_files = []
            num_images = len(self.image_paths)
            
            # 如果超过6张，分批处理
            if num_images > 6:
                batch_count = (num_images + 5) // 6  # 向上取整
                
                for batch_idx in range(batch_count):
                    start_idx = batch_idx * 6
                    end_idx = min(start_idx + 6, num_images)
                    batch_images = self.image_paths[start_idx:end_idx]
                    
                    # 生成批次文件名
                    output_dir = os.path.dirname(self.output_path)
                    base_name = Path(self.output_path).stem
                    if batch_count > 1:
                        batch_suffix = f"_part{batch_idx + 1}"
                    else:
                        batch_suffix = ""
                    batch_output = os.path.join(output_dir, f"{base_name}{batch_suffix}.jpg")
                    
                    # 处理当前批次
                    result = self.process_batch(batch_images, batch_output, batch_idx, batch_count)
                    if not result['success']:
                        self.finished.emit(False, result['message'], [])
                        return
                    
                    output_files.extend(result['output_files'])
                    self.batch_progress.emit(batch_idx + 1, batch_count, 100)
                
                self.finished.emit(True, f"拼接成功！共生成 {len(output_files)} 个文件", output_files)
            else:
                # 单批处理
                result = self.process_batch(self.image_paths, self.output_path, 0, 1)
                if result['success']:
                    self.finished.emit(True, f"拼接成功！已保存至：{self.output_path}", result['output_files'])
                else:
                    self.finished.emit(False, result['message'], [])
            
        except Exception as e:
            self.finished.emit(False, f"拼接失败：{str(e)}", [])
    
    def process_batch(self, image_paths, output_path, batch_idx, batch_count):
        """处理单个批次的图片"""
        try:
            # 读取所有图片并保存原始信息
            self.batch_progress.emit(batch_idx + 1, batch_count, 10)
            images = []
            dpi_info = {}  # 记录每张图片的DPI信息
            
            for i, img_path in enumerate(image_paths):
                img = Image.open(img_path)
                # 获取图片的DPI信息，并转换为普通数值
                dpi = img.info.get('dpi', (300, 300))
                
                # 处理各种 DPI 类型（IFDRational, int, float 等）
                def convert_dpi(value):
                    """转换 DPI 值为整数"""
                    try:
                        if hasattr(value, '__float__'):
                            return int(float(value))
                        elif isinstance(value, (int, float)):
                            return int(value)
                        else:
                            return 300  # 默认值
                    except:
                        return 300
                
                dpi_x = convert_dpi(dpi[0])
                dpi_y = convert_dpi(dpi[1])
                dpi_info[i] = (dpi_x, dpi_y)
                
                images.append({
                    'path': img_path,
                    'filename': os.path.basename(img_path),
                    'image': img,
                    'width': img.width,
                    'height': img.height
                })
                progress = 10 + int((i / len(image_paths)) * 20)
                self.batch_progress.emit(batch_idx + 1, batch_count, progress)
            
            # 根据图片数量决定布局
            num_images = len(images)
            if num_images == 2:
                rows, cols = 1, 2
            elif num_images <= 4:
                rows, cols = 2, 2
            elif num_images <= 6:
                rows, cols = 2, 3
            else:
                rows, cols = 2, 3
            
            # 计算每行的最大高度和每列的最大宽度
            row_max_heights = [0] * rows
            col_max_widths = [0] * cols
            
            for i, img_info in enumerate(images):
                row = i // cols
                col = i % cols
                row_max_heights[row] = max(row_max_heights[row], img_info['height'])
                col_max_widths[col] = max(col_max_widths[col], img_info['width'])
            
            self.progress_updated.emit(40)
            
            # 计算大图总尺寸
            total_width = sum(col_max_widths)
            total_height = sum(row_max_heights)
            
            # 创建白色背景的大图
            combined = Image.new('RGB', (total_width, total_height), 'white')
            
            # 计算拼接图的DPI（使用第一张图片的DPI作为参考）
            if dpi_info:
                output_dpi = dpi_info[0]
            else:
                output_dpi = (300, 300)
            
            # 计算每张图在合成图中的位置并记录元数据
            metadata = []
            y_offset = 0
            current_row = 0
            for i, img_info in enumerate(images):
                row = i // cols
                col = i % cols
                
                # 如果是新的一行，更新y坐标
                if row != current_row:
                    y_offset += row_max_heights[current_row]
                    current_row = row
                
                # 计算当前位置
                x = sum(col_max_widths[:col])
                y = y_offset
                
                # 居中放置图片
                paste_x = x + (col_max_widths[col] - img_info['width']) // 2
                paste_y = y + (row_max_heights[row] - img_info['height']) // 2
                
                # 粘贴图片
                combined.paste(img_info['image'], (paste_x, paste_y))
                
                # 记录元数据（记录实际粘贴位置和DPI信息）
                metadata.append({
                    'filename': img_info['filename'],
                    'x': paste_x,
                    'y': paste_y,
                    'width': img_info['width'],
                    'height': img_info['height'],
                    'dpi': list(dpi_info[i]) if i in dpi_info else [300, 300]
                })
                
                progress = 40 + int(((i + 1) / num_images) * 30)
                self.progress_updated.emit(progress)
            
            self.progress_updated.emit(70)
            
            # 保存为高质量 JPG，保持DPI
            jpg_path = Path(output_path)
            if jpg_path.suffix.lower() != '.jpg':
                jpg_path = jpg_path.with_suffix('.jpg')
            
            combined.save(str(jpg_path), 'JPEG', quality=100, subsampling=0, dpi=output_dpi)
            
            # 保存元数据 JSON
            json_path = jpg_path.with_suffix('.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            self.batch_progress.emit(batch_idx + 1, batch_count, 100)
            return {'success': True, 'output_files': [str(jpg_path), str(json_path)]}
            
        except Exception as e:
            return {'success': False, 'message': str(e)}


class SplitWorker(QThread):
    """拆分图像的工作线程"""
    progress_updated = pyqtSignal(int)
    batch_progress = pyqtSignal(int, int, int)  # current_image, total_images, progress
    finished = pyqtSignal(bool, str, list)  # success, message, output_files
    
    def __init__(self, image_list, output_dir):
        super().__init__()
        self.image_list = image_list  # List of tuples: (image_path, json_path)
        self.output_dir = output_dir
    
    def run(self):
        try:
            output_files = []
            total_images = len(self.image_list)
            
            for idx, (image_path, json_path) in enumerate(self.image_list):
                self.batch_progress.emit(idx + 1, total_images, 10)
                
                # 读取大图
                image = Image.open(image_path)
                self.batch_progress.emit(idx + 1, total_images, 30)
                
                # 读取 JSON 元数据
                with open(json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                self.batch_progress.emit(idx + 1, total_images, 50)
                
                # 切割并保存每张图片
                for i, item in enumerate(metadata):
                    x = item['x']
                    y = item['y']
                    w = item['width']
                    h = item['height']
                    filename = item['filename']
                    dpi = tuple(item.get('dpi', [300, 300]))  # 获取DPI信息，默认300
                    
                    # 切割图片
                    cropped = image.crop((x, y, x + w, y + h))
                    
                    # 保存为原始文件名，保持DPI
                    output_path = os.path.join(self.output_dir, filename)
                    
                    # 根据原始文件扩展名保存
                    ext = Path(filename).suffix.lower()
                    if ext in ['.jpg', '.jpeg']:
                        cropped.save(output_path, 'JPEG', quality=100, subsampling=0, dpi=dpi)
                    elif ext == '.png':
                        cropped.save(output_path, 'PNG', dpi=dpi)
                    else:
                        cropped.save(output_path, 'PNG', dpi=dpi)
                    
                    output_files.append(output_path)
                    
                    progress = 50 + int(((i + 1) / len(metadata)) * 40)
                    self.batch_progress.emit(idx + 1, total_images, progress)
                
                self.batch_progress.emit(idx + 1, total_images, 100)
            
            self.finished.emit(True, f"拆分成功！共处理 {total_images} 个拼接图，生成了 {len(output_files)} 个图片文件", output_files)
            
        except Exception as e:
            self.finished.emit(False, f"拆分失败：{str(e)}", [])


class DropZone(QFrame):
    """支持拖放的文件区域"""
    files_dropped = pyqtSignal(list)
    
    def __init__(self, text="拖放文件到这里", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #555555;
                border-radius: 10px;
                background-color: #2d2d2d;
                min-height: 150px;
            }
            QFrame:hover {
                border-color: #0078d4;
                background-color: #3d3d3d;
            }
        """)
        layout = QVBoxLayout()
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: #888888; font-size: 14px;")
        layout.addWidget(self.label)
        self.setLayout(layout)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        files = []
        for url in urls:
            if url.isLocalFile():
                files.append(url.toLocalFile())
        if files:
            self.files_dropped.emit(files)


class ImageStitcherApp(QMainWindow):
    """主应用窗口"""
    def __init__(self):
        super().__init__()
        self.stitch_images = []
        self.stitch_worker = None
        self.split_worker = None
        
        # 加载配置
        self.settings = QSettings("ImageStitcher", "ImageStitcherApp")
        self.last_save_dir = self.settings.value("last_save_dir", os.path.expanduser("~"))
        self.last_split_output_dir = self.settings.value("last_split_output_dir", "")
        
        self.init_ui()
        self.apply_dark_theme()
    
    def init_ui(self):
        self.setWindowTitle("图像拼接与拆分工具")
        self.setGeometry(100, 100, 800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 拼接标签页
        stitch_tab = self.create_stitch_tab()
        tab_widget.addTab(stitch_tab, "图片拼接")
        
        # 拆分标签页
        split_tab = self.create_split_tab()
        tab_widget.addTab(split_tab, "图片拆分")
        
        main_layout.addWidget(tab_widget)
    
    def create_stitch_tab(self):
        """创建拼接标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 拖放区域
        self.stitch_drop_zone = DropZone("拖放图片到这里（每批最多6张）")
        self.stitch_drop_zone.files_dropped.connect(self.on_stitch_files_dropped)
        layout.addWidget(self.stitch_drop_zone)
        
        # 文件列表
        self.stitch_files_label = QLabel("已选择：0 张图片")
        self.stitch_files_label.setStyleSheet("color: #888888; margin-top: 10px;")
        layout.addWidget(self.stitch_files_label)
        
        # 文件名列表显示
        self.stitch_filenames_label = QLabel("")
        self.stitch_filenames_label.setStyleSheet("color: #666666; font-size: 11px; margin-top: 5px;")
        self.stitch_filenames_label.setWordWrap(True)
        layout.addWidget(self.stitch_filenames_label)
        
        # 拼接按钮
        stitch_btn = QPushButton("开始拼接")
        stitch_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                padding: 12px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1084d8;
            }
            QPushButton:disabled {
                background-color: #555555;
            }
        """)
        stitch_btn.clicked.connect(self.start_stitch)
        stitch_btn.setEnabled(False)
        self.stitch_btn = stitch_btn
        layout.addWidget(stitch_btn)
        
        # 清除按钮
        clear_btn = QPushButton("清除已选")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: white;
                padding: 10px;
                font-size: 13px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        clear_btn.clicked.connect(self.clear_stitch_files)
        layout.addWidget(clear_btn)
        
        # 进度条
        self.stitch_progress = QProgressBar()
        self.stitch_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444444;
                border-radius: 5px;
                text-align: center;
                background-color: #2d2d2d;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.stitch_progress)
        
        # 批次进度标签
        self.stitch_batch_label = QLabel("")
        self.stitch_batch_label.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(self.stitch_batch_label)
        
        # 状态标签
        self.stitch_status = QLabel("")
        self.stitch_status.setStyleSheet("color: #888888; margin-top: 5px;")
        layout.addWidget(self.stitch_status)
        
        return widget
    
    def create_split_tab(self):
        """创建拆分标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 大图拖放区域
        self.image_drop_zone = DropZone("拖放拼接后的图片（JPG），支持多选")
        self.image_drop_zone.files_dropped.connect(self.on_image_dropped)
        layout.addWidget(self.image_drop_zone)
        
        self.split_image_label = QLabel("已选择：0 张拼接图")
        self.split_image_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.split_image_label)
        
        # 文件名列表显示
        self.split_filenames_label = QLabel("")
        self.split_filenames_label.setStyleSheet("color: #666666; font-size: 11px; margin-top: 5px;")
        self.split_filenames_label.setWordWrap(True)
        layout.addWidget(self.split_filenames_label)
        
        # JSON匹配状态标签
        self.json_match_label = QLabel("")
        self.json_match_label.setStyleSheet("color: #4caf50; font-size: 12px;")
        layout.addWidget(self.json_match_label)
        
        # 说明标签
        hint_label = QLabel("提示：拖放多个JPG图片，会自动查找同目录下的JSON文件")
        hint_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(hint_label)
        
        # 拆分按钮
        split_btn = QPushButton("开始拆分")
        split_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                padding: 12px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1084d8;
            }
            QPushButton:disabled {
                background-color: #555555;
            }
        """)
        split_btn.clicked.connect(self.start_split)
        split_btn.setEnabled(False)
        self.split_btn = split_btn
        layout.addWidget(split_btn)
        
        # 选择输出目录按钮
        output_dir_btn = QPushButton("选择输出目录")
        output_dir_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
                color: white;
                padding: 10px;
                font-size: 13px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        output_dir_btn.clicked.connect(self.select_output_dir)
        layout.addWidget(output_dir_btn)
        
        self.split_output_label = QLabel("输出目录：原图片所在目录")
        self.split_output_label.setStyleSheet("color: #888888;")
        layout.addWidget(self.split_output_label)
        
        # 进度条
        self.split_progress = QProgressBar()
        self.split_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444444;
                border-radius: 5px;
                text-align: center;
                background-color: #2d2d2d;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.split_progress)
        
        # 批次进度标签
        self.split_batch_label = QLabel("")
        self.split_batch_label.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(self.split_batch_label)
        
        # 状态标签
        self.split_status = QLabel("")
        self.split_status.setStyleSheet("color: #888888; margin-top: 5px;")
        layout.addWidget(self.split_status)
        
        # 初始化输出目录
        self.split_output_dir = ""
        
        return widget
    
    def apply_dark_theme(self):
        """应用深色主题"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
            QLabel {
                color: #d4d4d4;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #888888;
                padding: 10px 20px;
                border: 1px solid #333333;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border-bottom: 2px solid #0078d4;
            }
        """)
    
    def on_stitch_files_dropped(self, files):
        """处理拖放的图片文件"""
        valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.heic', '.heif'}
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in valid_extensions and file not in self.stitch_images:
                self.stitch_images.append(file)
        
        self.update_stitch_ui()
    
    def update_stitch_ui(self):
        """更新拼接界面"""
        count = len(self.stitch_images)
        self.stitch_files_label.setText(f"已选择：{count} 张图片")
        
        # 显示文件名列表
        if count > 0:
            filenames = [os.path.basename(f) for f in self.stitch_images]
            self.stitch_filenames_label.setText(f"文件列表：\n" + "\n".join(f"{i+1}. {fn}" for i, fn in enumerate(filenames)))
        else:
            self.stitch_filenames_label.setText("")
        
        # 移除6张的限制，允许任意数量
        if count >= 2:
            self.stitch_btn.setEnabled(True)
            self.stitch_files_label.setStyleSheet("color: #4caf50;")
            # 提示将分批处理
            if count > 6:
                batch_count = (count + 5) // 6
                self.stitch_batch_label.setText(f"将分 {batch_count} 批次处理，每批最多6张")
            else:
                self.stitch_batch_label.setText("")
        else:
            self.stitch_btn.setEnabled(False)
            self.stitch_files_label.setStyleSheet("color: #888888;")
            self.stitch_batch_label.setText("")
    
    def clear_stitch_files(self):
        """清除已选图片"""
        self.stitch_images.clear()
        self.stitch_progress.setValue(0)
        self.stitch_status.setText("")
        self.update_stitch_ui()
    
    def start_stitch(self):
        """开始拼接"""
        # 选择输出路径（使用上次保存的目录）
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存拼接图片",
            os.path.join(self.last_save_dir, "combined.jpg"),
            "JPEG 图片 (*.jpg)"
        )
        
        if file_path:
            # 保存目录
            self.last_save_dir = os.path.dirname(file_path)
            self.settings.setValue("last_save_dir", self.last_save_dir)
            
            self.stitch_btn.setEnabled(False)
            self.stitch_status.setText("正在处理...")
            
            self.stitch_worker = StitchWorker(self.stitch_images, file_path)
            self.stitch_worker.batch_progress.connect(self.on_batch_progress)
            self.stitch_worker.finished.connect(self.on_stitch_finished)
            self.stitch_worker.start()
    
    def on_batch_progress(self, batch_idx, total_batches, progress):
        """更新批次进度"""
        self.stitch_progress.setValue(progress)
        if total_batches > 1:
            self.stitch_batch_label.setText(f"正在处理第 {batch_idx}/{total_batches} 批次...")
    
    def on_stitch_finished(self, success, message, output_files):
        """拼接完成"""
        self.stitch_btn.setEnabled(True)
        self.stitch_status.setText(message)
        if success:
            # 显示所有生成的文件
            if output_files:
                file_list = "\n".join([f"  - {os.path.basename(f)}" for f in output_files])
                full_message = f"{message}\n\n生成的文件：\n{file_list}"
                
                # 询问是否打开文件夹
                reply = QMessageBox.question(
                    self,
                    "完成",
                    full_message + "\n\n是否打开输出文件夹？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    output_dir = os.path.dirname(output_files[0])
                    open_folder(output_dir)
            else:
                QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "错误", message)
    
    def on_image_dropped(self, files):
        """处理拖放的大图（支持多选）"""
        self.split_image_list = []
        matched_count = 0
        total_count = 0
        
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg')):
                # 查找对应的JSON文件
                json_path = self.find_matching_json(file)
                if json_path and os.path.exists(json_path):
                    self.split_image_list.append((file, json_path))
                    matched_count += 1
                total_count += 1
        
        # 更新界面
        self.split_image_label.setText(f"已选择：{total_count} 张拼接图，匹配到 {matched_count} 个JSON文件")
        self.update_split_ui()
    
    def on_json_dropped(self, files):
        """处理拖放的 JSON 文件（不再需要，保留兼容性）"""
        # 此功能已废弃，保留是为了避免错误
        pass
    
    def select_output_dir(self):
        """选择输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.split_output_dir = dir_path
            self.split_output_label.setText(f"输出目录：{dir_path}")
    
    def update_split_ui(self):
        """更新拆分界面"""
        if hasattr(self, 'split_image_list') and len(self.split_image_list) > 0:
            # 显示文件名列表
            filenames = [os.path.basename(img_path) for img_path, _ in self.split_image_list]
            self.split_filenames_label.setText(f"图片列表：\n" + "\n".join(f"{i+1}. {fn}" for i, fn in enumerate(filenames)))
            
            # 显示匹配状态
            total = len([f for f in self.split_image_list if f[1]])
            matched = len(self.split_image_list)
            self.json_match_label.setText(f"✓ 已匹配 {matched}/{total} 个JSON文件")
            self.json_match_label.setStyleSheet("color: #4caf50; font-size: 12px;")
            
            self.split_btn.setEnabled(True)
        else:
            self.split_filenames_label.setText("")
            self.json_match_label.setText("")
            self.split_btn.setEnabled(False)
    
    def find_matching_json(self, image_path):
        """查找与图片同名的JSON文件"""
        base_path = Path(image_path)
        json_path = base_path.with_suffix('.json')
        if json_path.exists():
            return str(json_path)
        return None
    
    def start_split(self):
        """开始拆分"""
        # 如果没有指定输出目录，使用上次保存的目录或图片所在目录
        if self.last_split_output_dir:
            self.split_output_dir = self.last_split_output_dir
        elif not self.split_output_dir:
            self.split_output_dir = os.path.dirname(self.split_image_list[0][0])
        
        # 保存输出目录
        self.last_split_output_dir = self.split_output_dir
        self.settings.setValue("last_split_output_dir", self.last_split_output_dir)
        
        self.split_btn.setEnabled(False)
        self.split_status.setText("正在处理...")
        
        self.split_worker = SplitWorker(self.split_image_list, self.split_output_dir)
        self.split_worker.batch_progress.connect(self.on_split_batch_progress)
        self.split_worker.finished.connect(self.on_split_finished)
        self.split_worker.start()
    
    def on_split_batch_progress(self, current_image, total_images, progress):
        """更新批次进度"""
        self.split_progress.setValue(progress)
        self.split_batch_label.setText(f"正在处理第 {current_image}/{total_images} 个拼接图...")
    
    def on_split_finished(self, success, message, output_files):
        """拆分完成"""
        self.split_btn.setEnabled(True)
        self.split_status.setText(message)
        if success:
            # 显示输出的文件列表
            file_count = len(output_files)
            file_preview = output_files[:5] if len(output_files) > 5 else output_files
            preview_text = "\n".join([f"  - {os.path.basename(f)}" for f in file_preview])
            if len(output_files) > 5:
                preview_text += f"\n  ... 还有 {len(output_files) - 5} 个文件"
            
            full_message = f"{message}\n\n生成的文件（前5个）：\n{preview_text}"
            
            # 询问是否打开文件夹
            reply = QMessageBox.question(
                self,
                "完成",
                full_message + "\n\n是否打开输出文件夹？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                open_folder(self.split_output_dir)
        else:
            QMessageBox.warning(self, "错误", message)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置应用图标
    icon_paths = ['app_icon.ico', 'app_icon.png']
    for icon_path in icon_paths:
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break
    
    window = ImageStitcherApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
