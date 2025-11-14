"""
生成 CPU 设计的可视化图形

支持多种可视化方式：
1. Yosys show - 生成电路结构图
2. netlistsvg - 生成美观的 SVG 网表图
"""

from pathlib import Path
import sys
import subprocess
import argparse

PROJECT_ROOT = Path(__file__).resolve().parent


def check_tool(tool_name, install_hint):
    """检查工具是否安装"""
    try:
        result = subprocess.run(
            [tool_name, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"✗ 未找到 {tool_name}")
        print(f"  安装提示: {install_hint}")
        return False


def generate_yosys_visualization(verilog_file, output_format="png"):
    """使用 Yosys 生成电路可视化"""
    print("\n" + "=" * 60)
    print(f"方案 1: 使用 Yosys 生成 {output_format.upper()} 格式电路图")
    print("=" * 60)

    # 检查 Yosys
    if not check_tool("yosys", "https://github.com/YosysHQ/yosys"):
        return False

    verilog_path = PROJECT_ROOT / verilog_file
    if not verilog_path.exists():
        print(f"✗ 文件不存在: {verilog_path}")
        return False

    output_prefix = verilog_path.stem
    output_dir = PROJECT_ROOT / "build" / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取 Verilog: {verilog_path}")
    print(f"输出目录: {output_dir}")

    # Yosys 命令：读取 -> 处理 -> 生成图形
    yosys_script = f"""
read_verilog {verilog_path}
hierarchy -auto-top
proc
opt
clean
show -format {output_format} -prefix {output_dir / output_prefix}
"""

    script_file = output_dir / "yosys_script.ys"
    with open(script_file, "w") as f:
        f.write(yosys_script)

    print(f"\n执行 Yosys...")
    try:
        result = subprocess.run(
            ["yosys", "-s", str(script_file)],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            output_file = output_dir / f"{output_prefix}.{output_format}"
            print(f"✓ 可视化生成成功: {output_file}")

            # 检查是否生成了 dot 文件
            dot_file = output_dir / f"{output_prefix}.dot"
            if dot_file.exists() and check_tool("dot", "https://graphviz.org/"):
                print(f"\n生成 PNG 图片...")
                subprocess.run(
                    ["dot", "-Tpng", str(dot_file), "-o", str(output_dir / f"{output_prefix}.png")],
                    timeout=60
                )
                print(f"✓ PNG 图片已生成: {output_dir / output_prefix}.png")

            return True
        else:
            print(f"✗ Yosys 执行失败:")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("✗ Yosys 执行超时")
        return False
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def generate_netlistsvg(verilog_file):
    """使用 netlistsvg 生成 SVG 网表图"""
    print("\n" + "=" * 60)
    print("方案 2: 使用 netlistsvg 生成 SVG 网表图")
    print("=" * 60)

    # 检查工具
    if not check_tool("yosys", "https://github.com/YosysHQ/yosys"):
        return False

    if not check_tool("netlistsvg", "npm install -g netlistsvg"):
        return False

    verilog_path = PROJECT_ROOT / verilog_file
    if not verilog_path.exists():
        print(f"✗ 文件不存在: {verilog_path}")
        return False

    output_prefix = verilog_path.stem
    output_dir = PROJECT_ROOT / "build" / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_file = output_dir / f"{output_prefix}.json"
    svg_file = output_dir / f"{output_prefix}.svg"

    # 步骤 1: 使用 Yosys 生成 JSON 网表
    print(f"\n步骤 1: 生成 JSON 网表...")
    yosys_script = f"""
read_verilog {verilog_path}
hierarchy -auto-top
proc
opt
clean
write_json {json_file}
"""

    script_file = output_dir / "netlist_script.ys"
    with open(script_file, "w") as f:
        f.write(yosys_script)

    try:
        result = subprocess.run(
            ["yosys", "-s", str(script_file)],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print(f"✗ Yosys 执行失败:")
            print(result.stderr)
            return False

        print(f"✓ JSON 网表已生成: {json_file}")

        # 步骤 2: 使用 netlistsvg 转换为 SVG
        print(f"\n步骤 2: 转换为 SVG...")
        result = subprocess.run(
            ["netlistsvg", str(json_file), "-o", str(svg_file)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print(f"✓ SVG 网表图已生成: {svg_file}")
            return True
        else:
            print(f"✗ netlistsvg 执行失败:")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("✗ 执行超时")
        return False
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="生成 CPU 设计的可视化图形",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 Yosys 生成 CPU 的电路图
  python visualize.py --yosys build/verilog/cpu.v

  # 使用 netlistsvg 生成美观的 SVG 图
  python visualize.py --netlistsvg build/verilog/cpu.v

  # 可视化内存模块
  python visualize.py --yosys build/verilog/memory_file.v

  # 生成 DOT 格式（可以用 Graphviz 进一步处理）
  python visualize.py --yosys build/verilog/cpu.v --format dot
        """
    )

    parser.add_argument(
        "--yosys",
        metavar="VERILOG_FILE",
        help="使用 Yosys 生成电路可视化"
    )

    parser.add_argument(
        "--netlistsvg",
        metavar="VERILOG_FILE",
        help="使用 netlistsvg 生成 SVG 网表图"
    )

    parser.add_argument(
        "--format",
        default="dot",
        choices=["dot", "png", "svg", "pdf"],
        help="Yosys 输出格式 (默认: dot)"
    )

    args = parser.parse_args()

    if not args.yosys and not args.netlistsvg:
        parser.print_help()
        return 1

    print("=" * 60)
    print("CPU 可视化工具")
    print("=" * 60)

    success = False

    if args.yosys:
        success = generate_yosys_visualization(args.yosys, args.format)

    if args.netlistsvg:
        success = generate_netlistsvg(args.netlistsvg)

    if success:
        print("\n" + "=" * 60)
        print("✓ 可视化生成完成!")
        print("=" * 60)
        return 0
    else:
        print("\n" + "=" * 60)
        print("✗ 可视化生成失败")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
