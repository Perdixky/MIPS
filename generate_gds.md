# 从 Verilog 生成 KLayout 版图的方案

## 方案 1：使用 OpenLane + SkyWater 130nm PDK（推荐）

### 步骤概述
1. **安装工具链**
2. **准备 Verilog 设计**
3. **运行综合和布局布线**
4. **生成 GDSII 文件**
5. **在 KLayout 中查看**

### 详细步骤

#### 1. 安装 OpenLane
```bash
# 使用 Docker 安装（最简单）
git clone https://github.com/The-OpenROAD-Project/OpenLane.git
cd OpenLane
make pull-openlane
make pdk
```

#### 2. 创建项目配置
创建 `openlane_config.json`:
```json
{
    "DESIGN_NAME": "CPU",
    "VERILOG_FILES": "dir::build/verilog/cpu.v",
    "CLOCK_PORT": "clk",
    "CLOCK_PERIOD": 10.0,
    "FP_SIZING": "absolute",
    "DIE_AREA": "0 0 2000 2000",
    "PL_TARGET_DENSITY": 0.5
}
```

#### 3. 运行 OpenLane
```bash
cd OpenLane
./flow.tcl -design <your_design_dir> -tag run1
```

#### 4. 生成的文件位置
```
OpenLane/designs/<design_name>/runs/run1/results/final/gds/
    └── cpu.gds  # 可以用 KLayout 打开
```

---

## 方案 2：使用 Yosys 生成简化的可视化

这个方案不生成真实版图，但可以快速查看设计结构：

### 安装工具
```bash
# Windows
winget install YosysHQ.Yosys

# 或使用 uv
uv tool install yowasp-yosys
```

### 生成可视化
```bash
# 生成 dot 格式的电路图
yosys -p "read_verilog build/verilog/cpu.v; proc; opt; show -format dot -prefix cpu"

# 使用 Graphviz 转换为图片
dot -Tpng cpu.dot -o cpu.png
```

---

## 方案 3：使用 netlistsvg（SVG 网表查看器）

生成美观的 SVG 格式网表图：

### 安装
```bash
npm install -g netlistsvg
```

### 使用
```bash
# 先用 Yosys 生成 JSON 网表
yosys -p "read_verilog build/verilog/cpu.v; proc; write_json cpu.json"

# 转换为 SVG
netlistsvg cpu.json -o cpu.svg
```

---

## 方案 4：使用 Amaranth 内置的可视化功能

直接从 Python 生成结构图：

```python
from amaranth import *
from amaranth.back import rtlil
from mips.core.cpu import CPU

# 生成 RTLIL
cpu = CPU()
output = rtlil.convert(cpu, ports=[...])

# 保存为 .il 文件
with open("cpu.il", "w") as f:
    f.write(output)

# 使用 Yosys 查看
# yosys -p "read_ilang cpu.il; show"
```

---

## 🎨 推荐流程（根据需求选择）

### 如果您想要：
- ✅ **真实的芯片版图**：使用方案 1（OpenLane）
- ✅ **快速查看电路结构**：使用方案 2（Yosys show）
- ✅ **美观的网表图**：使用方案 3（netlistsvg）
- ✅ **从 Python 直接生成**：使用方案 4（Amaranth）

### 注意事项
- 方案 1 需要较长时间（几小时），生成真实可制造的版图
- 方案 2-4 只需几秒钟，生成的是逻辑结构图而非物理版图
- KLayout 主要用于查看 GDSII 格式的物理版图（方案 1）
- 如果只是想可视化电路结构，推荐方案 2 或 3
