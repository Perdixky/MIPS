"""
简单的可视化工具 - 不需要安装 Yosys

使用 Amaranth 内置功能生成模块层级结构图
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amaranth import *
from mips.core.cpu import CPU
from mips.memory.memory_file import MemoryFile
import argparse


def print_hierarchy(elaboratable, name="top", indent=0):
    """打印模块层级结构"""
    prefix = "  " * indent
    print(f"{prefix}├─ {name}")

    # 创建一个临时的 Module 来探索子模块
    m = Module()

    try:
        # 手动列出已知的子模块（基于代码结构）
        if name == "CPU":
            submodules = [
                ("pc", "PC"),
                ("pc_controller", "PCController"),
                ("regfile", "RegFile"),
                ("forwarding_unit_rs", "ForwardingUnit"),
                ("forwarding_unit_rt", "ForwardingUnit"),
                ("hazard_detection_rs", "HazardDetectionUnit"),
                ("hazard_detection_rt", "HazardDetectionUnit"),
                ("fetch_stage", "InstructionFetchStage"),
                ("if_id_reg", "IFIDRegister"),
                ("decode_stage", "InstructionDecodeStage"),
                ("id_ex_reg", "IDEXRegister"),
                ("execute_stage", "ExecuteStage"),
                ("ex_mem_reg", "EXMEMRegister"),
                ("memory_stage", "MemoryStage"),
                ("mem_wb_reg", "MEMWBRegister"),
                ("writeback_stage", "WriteBackStage"),
            ]
            for sub_name, sub_type in submodules:
                print(f"{prefix}  ├─ {sub_name} ({sub_type})")
        elif name == "MemoryFile":
            print(f"{prefix}  ├─ mem (Memory[4096 x 32-bit])")
            print(f"{prefix}  ├─ write_port")
            print(f"{prefix}  └─ read_port")
    except Exception as e:
        print(f"{prefix}  [无法获取子模块信息]")


def generate_text_diagram(module_type="cpu"):
    """生成文本格式的模块图"""
    output_dir = PROJECT_ROOT / "build" / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    if module_type == "cpu":
        print("=" * 60)
        print("CPU 模块层级结构")
        print("=" * 60)
        print_hierarchy(CPU(), "CPU")

        # 生成文本文件
        output_file = output_dir / "cpu_hierarchy.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("CPU 五级流水线结构\n")
            f.write("=" * 60 + "\n\n")
            f.write("流水线阶段:\n")
            f.write("  1. IF  (Instruction Fetch)     - 取指令\n")
            f.write("  2. ID  (Instruction Decode)    - 译码\n")
            f.write("  3. EX  (Execute)               - 执行\n")
            f.write("  4. MEM (Memory Access)         - 访存\n")
            f.write("  5. WB  (Write Back)            - 写回\n\n")

            f.write("主要组件:\n")
            f.write("  - PC (程序计数器)\n")
            f.write("  - RegFile (寄存器堆, 32x32-bit)\n")
            f.write("  - ALU (算术逻辑单元)\n")
            f.write("  - ForwardingUnit x2 (数据转发单元)\n")
            f.write("  - HazardDetectionUnit x2 (冒险检测单元)\n\n")

            f.write("流水线寄存器:\n")
            f.write("  - IF/ID Register\n")
            f.write("  - ID/EX Register\n")
            f.write("  - EX/MEM Register\n")
            f.write("  - MEM/WB Register\n\n")

            f.write("端口:\n")
            f.write("  输入:\n")
            f.write("    - clk (时钟)\n")
            f.write("    - rst (复位)\n")
            f.write("    - imem_rdata[31:0] (指令存储器读数据)\n")
            f.write("    - dmem_rdata[31:0] (数据存储器读数据)\n")
            f.write("  输出:\n")
            f.write("    - imem_addr[31:0] (指令存储器地址)\n")
            f.write("    - dmem_addr[31:0] (数据存储器地址)\n")
            f.write("    - dmem_wdata[31:0] (数据存储器写数据)\n")
            f.write("    - dmem_wen (数据存储器写使能)\n")

        print(f"\n✓ 层级结构已保存: {output_file}")

    elif module_type == "memory":
        print("=" * 60)
        print("MemoryFile 模块层级结构")
        print("=" * 60)
        print_hierarchy(MemoryFile(), "MemoryFile")

        output_file = output_dir / "memory_hierarchy.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("MemoryFile 模块结构\n")
            f.write("=" * 60 + "\n\n")
            f.write("存储器配置:\n")
            f.write("  - 深度: 4096 个存储单元\n")
            f.write("  - 宽度: 32-bit\n")
            f.write("  - 总容量: 16 KB\n\n")

            f.write("端口:\n")
            f.write("  输入:\n")
            f.write("    - clk (时钟)\n")
            f.write("    - rst (复位)\n")
            f.write("    - addr[31:0] (地址)\n")
            f.write("    - write_data[31:0] (写数据)\n")
            f.write("    - write_enable (写使能)\n")
            f.write("  输出:\n")
            f.write("    - read_data[31:0] (读数据)\n\n")

            f.write("特性:\n")
            f.write("  - 同步读写\n")
            f.write("  - 透明写入 (写后立即可读)\n")
            f.write("  - 初始化为全 0\n")

        print(f"\n✓ 层级结构已保存: {output_file}")


def generate_ascii_diagram():
    """生成 ASCII 艺术风格的流水线图"""
    output_dir = PROJECT_ROOT / "build" / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    diagram = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                         MIPS 五级流水线 CPU                               ║
╚═══════════════════════════════════════════════════════════════════════════╝

    ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐
    │   IF    │─────▶│   ID    │─────▶│   EX    │─────▶│   MEM   │─────▶│   WB    │
    │  取指令  │      │  译码    │      │  执行    │      │  访存    │      │  写回    │
    └─────────┘      └─────────┘      └─────────┘      └─────────┘      └─────────┘
         │                │                │                │                │
         │                │                │                │                │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │ IF/ID   │      │ ID/EX   │      │ EX/MEM  │      │ MEM/WB  │      │         │
    │Register │      │Register │      │Register │      │Register │      │ RegFile │
    └─────────┘      └─────────┘      └─────────┘      └─────────┘      └─────────┘
                                           │                                   ▲
                                           │                                   │
    ┌──────────────────────────────────────┼───────────────────────────────────┘
    │                                      │
    │                          ┌───────────▼──────────┐
    │                          │  ForwardingUnit x2   │
    │                          │   (数据转发单元)      │
    │                          └──────────────────────┘
    │
    │                          ┌──────────────────────┐
    └─────────────────────────▶│ HazardDetectionUnit  │
                               │   (冒险检测单元)      │
                               └──────────────────────┘

外部接口:
  ┌────────────┐                                          ┌────────────┐
  │ 指令存储器  │◀─────── imem_addr ────────────────────│            │
  │  (IMem)    │─────── imem_rdata ──────────────────▶│    CPU     │
  └────────────┘                                          │            │
  ┌────────────┐                                          │            │
  │ 数据存储器  │◀─────── dmem_addr ────────────────────│            │
  │  (DMem)    │◀─────── dmem_wdata ───────────────────│            │
  │            │◀─────── dmem_wen ─────────────────────│            │
  │            │─────── dmem_rdata ──────────────────▶│            │
  └────────────┘                                          └────────────┘

支持的指令类型:
  • R型指令: ADD, SUB, AND, OR, SLT, SLL, SRL 等
  • I型指令: ADDI, ANDI, ORI, SLTI, LW, SW, BEQ, BNE 等
  • J型指令: J, JAL

特性:
  ✓ 数据转发 (Data Forwarding)
  ✓ 冒险检测 (Hazard Detection)
  ✓ 流水线暂停 (Pipeline Stall)
"""

    output_file = output_dir / "pipeline_diagram.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(diagram)

    print(diagram)
    print(f"\n✓ 流水线图已保存: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="简单的可视化工具（不需要额外工具）",
        epilog="""
示例:
  # 生成 CPU 层级结构
  python simple_visualize.py --cpu

  # 生成 Memory 层级结构
  python simple_visualize.py --memory

  # 生成 ASCII 流水线图
  python simple_visualize.py --pipeline

  # 生成所有
  python simple_visualize.py --all
        """
    )

    parser.add_argument("--cpu", action="store_true", help="生成 CPU 层级结构")
    parser.add_argument("--memory", action="store_true", help="生成 Memory 层级结构")
    parser.add_argument("--pipeline", action="store_true", help="生成 ASCII 流水线图")
    parser.add_argument("--all", action="store_true", help="生成所有图表")

    args = parser.parse_args()

    if not any([args.cpu, args.memory, args.pipeline, args.all]):
        parser.print_help()
        return 1

    if args.all or args.cpu:
        generate_text_diagram("cpu")

    if args.all or args.memory:
        print()
        generate_text_diagram("memory")

    if args.all or args.pipeline:
        print()
        generate_ascii_diagram()

    return 0


if __name__ == "__main__":
    sys.exit(main())
