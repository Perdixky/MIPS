# 🎨 MIPS CPU 可视化指南

## 📦 安装所需工具

### Windows 系统

#### 方法 1: 使用 OSS CAD Suite（推荐）
这是最简单的方法，一次性安装所有工具：

```bash
# 下载 OSS CAD Suite
# 访问: https://github.com/YosysHQ/oss-cad-suite-build/releases
# 下载最新的 Windows 版本（.exe）

# 安装后，将安装目录添加到 PATH，或在安装目录运行：
oss-cad-suite\environment.bat
```

#### 方法 2: 使用 winget
```bash
winget install YosysHQ.Yosys
```

#### 方法 3: 使用 Chocolatey
```bash
choco install yosys
```

### 安装 Graphviz（用于生成 PNG 图片）
```bash
winget install Graphviz.Graphviz
# 或
choco install graphviz
```

### 安装 netlistsvg（可选，用于生成美观的 SVG）
```bash
# 需要先安装 Node.js
winget install OpenJS.NodeJS

# 然后安装 netlistsvg
npm install -g netlistsvg
```

---

## 🚀 快速开始

### 1. 生成 Verilog 文件
```bash
uv run python generate_verilog.py
```

### 2. 生成可视化

#### 方案 A: 使用 Yosys（电路结构图）
```bash
# 生成 CPU 的电路图
uv run python visualize.py --yosys build/verilog/cpu.v

# 生成 Memory 的电路图
uv run python visualize.py --yosys build/verilog/memory_file.v --format png
```

生成的文件位置：`build/visualizations/`

#### 方案 B: 使用 netlistsvg（美观的网表图）
```bash
uv run python visualize.py --netlistsvg build/verilog/memory_file.v
```

---

## 🖼️ 生成真实芯片版图（KLayout）

要生成 KLayout 可以打开的 GDSII 版图文件，需要完整的 ASIC 设计流程：

### 使用 OpenLane（完整开源工具链）

#### 1. 安装 Docker
```bash
# Windows: 下载 Docker Desktop
# https://www.docker.com/products/docker-desktop
```

#### 2. 克隆 OpenLane
```bash
git clone --depth 1 https://github.com/The-OpenROAD-Project/OpenLane.git
cd OpenLane
```

#### 3. 安装 PDK（工艺库）
```bash
make pull-openlane
make pdk
```

#### 4. 创建设计项目
```bash
cd OpenLane/designs
mkdir mips_cpu
cd mips_cpu

# 复制 Verilog 文件
cp ../../../../build/verilog/cpu.v .
```

#### 5. 创建配置文件 `config.json`
```json
{
    "DESIGN_NAME": "CPU",
    "VERILOG_FILES": "dir::*.v",
    "CLOCK_PORT": "clk",
    "CLOCK_PERIOD": 20.0,
    "FP_SIZING": "absolute",
    "DIE_AREA": "0 0 3000 3000",
    "PL_TARGET_DENSITY": 0.3,
    "FP_CORE_UTIL": 30,
    "SYNTH_STRATEGY": "AREA 0"
}
```

#### 6. 运行综合和布局布线
```bash
cd ../..
./flow.tcl -design mips_cpu
```

这个过程需要 **1-3 小时**，会生成：
- **GDS 文件**: `designs/mips_cpu/runs/<timestamp>/results/final/gds/CPU.gds`
- **DEF 文件**: `designs/mips_cpu/runs/<timestamp>/results/final/def/CPU.def`

#### 7. 在 KLayout 中查看
```bash
# 安装 KLayout
# https://www.klayout.de/build.html

# 打开 GDS 文件
klayout CPU.gds
```

---

## 📊 各方案对比

| 方案 | 生成时间 | 文件类型 | 用途 | 难度 |
|------|---------|---------|------|------|
| **Yosys show** | 几秒 | PNG/SVG/DOT | 查看电路逻辑结构 | ⭐ 简单 |
| **netlistsvg** | 几秒 | SVG | 美观的网表展示 | ⭐⭐ 中等 |
| **OpenLane** | 1-3小时 | GDSII | 真实芯片版图 | ⭐⭐⭐⭐ 复杂 |

---

## 🎯 推荐流程

### 初学者/快速预览
1. 安装 OSS CAD Suite
2. 运行 `visualize.py --yosys`
3. 查看生成的 PNG 图片

### 想要美观展示
1. 安装 Node.js + netlistsvg
2. 运行 `visualize.py --netlistsvg`
3. 用浏览器打开 SVG 文件

### 需要真实版图
1. 安装 Docker + OpenLane
2. 配置设计参数
3. 运行完整流程（耗时较长）
4. 用 KLayout 查看 GDSII

---

## 💡 提示

- **内存模块太大**：如果 CPU 模块太复杂无法可视化，先尝试 memory_file.v
- **简化设计**：可以使用 `--memory-depth 64` 生成更小的内存模块
- **分模块查看**：对大型设计，建议分别可视化各个子模块

---

## 🔧 故障排除

### Yosys 报错 "hierarchy" 失败
- 检查 Verilog 文件语法
- 尝试添加 `-noauto` 参数

### DOT 文件无法转 PNG
- 安装 Graphviz
- 手动运行: `dot -Tpng file.dot -o file.png`

### OpenLane 运行失败
- 检查 Docker 是否正常运行
- 查看日志: `designs/<design>/runs/<timestamp>/logs/`
- 减小设计规模或增加 `DIE_AREA`
