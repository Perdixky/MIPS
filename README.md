# MIPS CPU（Amaranth）

这是一个用 Amaranth HDL 编写的五级流水线 MIPS CPU 实验项目，包含寄存器文件、指令与数据存储器模型、前递与冒险处理、分支预测，以及 Hamming 程序的仿真示例。

## 运行

建议使用 Python 3.12 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
.venv/bin/python sim/test_all.py --all
.venv/bin/python main.py
.venv/bin/python generate_verilog.py --memory-depth 256
```

`sim/test_all.py --all` 非交互运行所有测试，失败时返回非零状态；不带参数时打开交互式测试菜单。`main.py` 仿真 Hamming 程序，输出内存映射写入记录，并在 `build/analysis/` 生成流水线与性能示意图。`generate_verilog.py` 默认将 CPU 和存储器模块分别导出到 `build/verilog/`；可用 `--output` 指定目录。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `mips/core/` | CPU、ALU 和流水线逻辑 |
| `mips/memory/` | 仿真用存储器 |
| `mips/peripherals/` | 独立的外设实验模块 |
| `sim/benches/` | CPU 与寄存器文件仿真测试 |
| `program/` | Hamming 程序与编码器 |
| `docs/instruction_set.md` | 指令格式与设计笔记 |

## 当前验证范围

仿真回归覆盖基础指令、前递、分支、访存冒险、JAL 和寄存器文件；Hamming 示例可运行，导出的 Verilog 可通过 Yosys 的 `check`。这些结果说明项目可用于软件仿真和继续开发。仓库没有 FPGA 顶层、引脚约束、板级验证或 ASIC 流程的可复现结果，因此尚不能认定为可直接上板或流片的完整硬件工程。

波形文件（`*.vcd`）、生成的 Verilog 和 `build/` 下的分析图都可重新生成，默认不纳入版本控制。
