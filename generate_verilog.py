"""
将 Amaranth HDL 模块转换为 Verilog 文件

这个脚本演示如何从 cpu.py 和 memory_file.py 生成 Verilog 代码。
"""

from pathlib import Path
import sys
import re
import argparse

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amaranth.back import verilog
from mips.core.cpu import CPU
from mips.memory.memory_file import MemoryFile


def process_verilog_paths(verilog_text: str, strip_paths: bool = False) -> str:
    """
    处理 Verilog 代码中的文件路径

    Args:
        verilog_text: 原始 Verilog 代码
        strip_paths: 如果为 True，移除所有路径注释；否则转换为相对路径

    Returns:
        处理后的 Verilog 代码
    """
    if strip_paths:
        # 移除所有包含 src = "..." 的注释行
        verilog_text = re.sub(r'\(\* src = "[^"]*" \*\)\n', '', verilog_text)
    else:
        # 将绝对路径转换为相对路径
        project_root_str = str(PROJECT_ROOT).replace('\\', '\\\\')
        # 匹配形如 (* src = "D:\Code\MIPS\..." *) 的注释
        def replace_path(match):
            full_path = match.group(1)
            # 尝试转换为相对路径
            try:
                rel_path = Path(full_path).relative_to(PROJECT_ROOT)
                return f'(* src = "{rel_path}" *)'
            except ValueError:
                # 如果无法转换，保持原样
                return match.group(0)

        verilog_text = re.sub(r'\(\* src = "([^"]*)" \*\)', replace_path, verilog_text)

    return verilog_text


def generate_cpu_verilog(output_dir="build/verilog", strip_paths=False):
    """生成 CPU 的 Verilog 代码"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("生成 CPU Verilog 代码...")
    cpu = CPU()

    # 使用 Amaranth 的 verilog 后端生成代码
    verilog_text = verilog.convert(
        cpu,
        name="CPU",
        ports=[
            cpu.imem_addr,
            cpu.imem_rdata,
            cpu.dmem_addr,
            cpu.dmem_wdata,
            cpu.dmem_wen,
            cpu.dmem_rdata,
        ],
    )

    # 处理文件路径
    verilog_text = process_verilog_paths(verilog_text, strip_paths)

    # 写入文件
    output_file = output_path / "cpu.v"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(verilog_text)

    print(f"✓ CPU Verilog 已生成: {output_file}")
    return output_file


def generate_memory_verilog(output_dir="build/verilog", strip_paths=False, memory_depth=4096, simplify_init=False):
    """生成 MemoryFile 的 Verilog 代码"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n生成 MemoryFile Verilog 代码 (深度: {memory_depth})...")
    memory = MemoryFile(depth=memory_depth)

    # 使用 Amaranth 的 verilog 后端生成代码
    verilog_text = verilog.convert(
        memory,
        name="MemoryFile",
        ports=[
            memory.addr,
            memory.read_data,
            memory.write_data,
            memory.write_enable,
        ],
    )

    # 处理文件路径
    verilog_text = process_verilog_paths(verilog_text, strip_paths)

    # 简化重复的初始化代码
    if simplify_init:
        verilog_text = simplify_memory_init(verilog_text, memory_depth)

    # 写入文件
    output_file = output_path / "memory_file.v"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(verilog_text)

    print(f"✓ MemoryFile Verilog 已生成: {output_file}")
    return output_file


def simplify_memory_init(verilog_text: str, depth: int) -> str:
    """
    简化内存初始化代码，将大量重复的 mem[i] = 32'd0 替换为循环

    Args:
        verilog_text: 原始 Verilog 代码
        depth: 内存深度

    Returns:
        简化后的 Verilog 代码
    """
    # 查找 initial begin ... end 块中的重复初始化
    # 匹配形如 mem[0] = 32'd0; mem[1] = 32'd0; ... 的模式

    # 使用正则表达式找到 initial begin 和 end 之间的内容
    init_pattern = r'(  initial begin\n)((?:    mem\[\d+\] = 32\'d0;\n)+)(  end)'

    def replace_init(match):
        prefix = match.group(1)
        suffix = match.group(3)

        # 生成简洁的初始化代码
        replacement = f"{prefix}    integer i;\n    for (i = 0; i < {depth}; i = i + 1)\n      mem[i] = 32'd0;\n{suffix}"
        return replacement

    verilog_text = re.sub(init_pattern, replace_init, verilog_text)

    return verilog_text


def main():
    parser = argparse.ArgumentParser(
        description="将 Amaranth HDL 模块转换为 Verilog 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 默认：使用相对路径，4096深度内存，标准初始化
  python generate_verilog.py

  # 完全移除路径注释
  python generate_verilog.py --strip-paths

  # 生成 256 深度的内存
  python generate_verilog.py --memory-depth 256

  # 简化初始化（使用 for 循环，文件更小但可能影响综合）
  python generate_verilog.py --simplify

  # 指定输出目录
  python generate_verilog.py --output build/rtl
        """
    )

    parser.add_argument(
        "--strip-paths",
        action="store_true",
        help="完全移除 Verilog 代码中的源文件路径注释"
    )

    parser.add_argument(
        "-o", "--output",
        default="build/verilog",
        help="输出目录 (默认: build/verilog)"
    )

    parser.add_argument(
        "--memory-depth",
        type=int,
        default=4096,
        help="内存深度（存储单元数量，默认: 4096）"
    )

    parser.add_argument(
        "--simplify",
        action="store_true",
        help="简化内存初始化代码（使用 for 循环代替重复语句）"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Amaranth HDL → Verilog 转换工具")
    print("=" * 60)

    if args.strip_paths:
        print("模式: 移除所有路径注释")
    else:
        print("模式: 使用相对路径")

    print(f"输出目录: {args.output}\n")

    try:
        cpu_file = generate_cpu_verilog(args.output, args.strip_paths)
        memory_file = generate_memory_verilog(
            args.output,
            args.strip_paths,
            args.memory_depth,
            args.simplify
        )

        print("\n" + "=" * 60)
        print("✓ 所有 Verilog 文件生成完成!")
        print("=" * 60)
        print(f"\n生成的文件:")
        print(f"  1. {cpu_file}")
        print(f"  2. {memory_file}")

        return 0
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
