"""测试 DPI 序列化"""
import json
from PIL import Image
import os

# 创建一个测试图片
test_image = Image.new('RGB', (100, 100), 'white')
test_image.info['dpi'] = (300, 300)

# 尝试序列化 DPI
dpi = test_image.info.get('dpi', (300, 300))
print(f"原始 DPI: {dpi}, 类型: {type(dpi)}")
print(f"DPI[0]: {dpi[0]}, 类型: {type(dpi[0])}")
print(f"DPI[1]: {dpi[1]}, 类型: {type(dpi[1])}")

# 转换为普通数值
dpi_x = float(dpi[0]) if hasattr(dpi[0], '__float__') else dpi[0]
dpi_y = float(dpi[1]) if hasattr(dpi[1], '__float__') else dpi[1]
dpi_converted = (int(dpi_x), int(dpi_y))

print(f"转换后 DPI: {dpi_converted}, 类型: {type(dpi_converted)}")

# 测试 JSON 序列化
test_data = {
    'filename': 'test.jpg',
    'x': 0,
    'y': 0,
    'width': 100,
    'height': 100,
    'dpi': list(dpi_converted)
}

try:
    json_str = json.dumps(test_data)
    print("✓ JSON 序列化成功")
    print(f"JSON 内容: {json_str}")
    
    # 测试反序列化
    loaded = json.loads(json_str)
    print(f"✓ JSON 反序列化成功")
    print(f"加载后的 DPI: {loaded['dpi']}")
except Exception as e:
    print(f"✗ JSON 序列化失败: {e}")
