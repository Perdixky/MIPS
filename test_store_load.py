#!/usr/bin/env python3
"""测试Store-Load连续指令在同步内存下的行为"""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from amaranth import *
from amaranth.sim import Simulator
from mips.core.cpu import CPU, Opcode
from mips.memory.memory_file import MemoryFile

def encode_i_type(opcode, rs, rt, imm):
    imm = imm & 0xFFFF
    return (opcode << 26) | (rs << 21) | (rt << 16) | imm

# 创建测试系统
class TestSystem(Elaboratable):
    def __init__(self):
        pass

    def elaborate(self, platform):
        m = Module()
        m.submodules.cpu = cpu = CPU()
        m.submodules.imem = imem = MemoryFile(depth=256)
        m.submodules.dmem = dmem = MemoryFile(depth=256)

        m.d.comb += [
            imem.read_addr.eq(cpu.imem_addr),
            imem.write_addr.eq(0),
            imem.write_data.eq(0),
            imem.write_enable.eq(0),
            cpu.imem_rdata.eq(imem.read_data),
            cpu.reset.eq(0),
            dmem.read_addr.eq(cpu.dmem_read_addr),
            dmem.write_addr.eq(cpu.dmem_write_addr),
            dmem.write_data.eq(cpu.dmem_wdata),
            dmem.write_enable.eq(cpu.dmem_wen),
            cpu.dmem_rdata.eq(dmem.read_data),
        ]
        return m

dut = TestSystem()

# 测试程序：
# ADDI $t0, $0, 42    # $t0 = 42
# SW $t0, 0x80($0)    # mem[0x80] = 42
# LW $t1, 0x80($0)    # $t1 = mem[0x80] (应该是42)
# SW $t1, 0x84($0)    # mem[0x84] = $t1 (验证load的值)
program = [
    encode_i_type(Opcode.ADDI, 0, 8, 42),     # $t0 = 42
    encode_i_type(Opcode.SW, 0, 8, 0x80),     # mem[0x80] = 42
    encode_i_type(Opcode.LW, 0, 9, 0x80),     # $t1 = mem[0x80]
    encode_i_type(Opcode.SW, 0, 9, 0x84),     # mem[0x84] = $t1
    0,  # NOP
]

async def bench(ctx):
    # 初始化指令内存
    for i, inst in enumerate(program):
        ctx.set(dut.elaborate(None).cpu.imem_rdata, inst)
        await ctx.tick()
        # 等待几个周期让流水线填充
    for _ in range(20):
        await ctx.tick()
        pc = ctx.get(dut.elaborate(None).cpu.imem_addr)
        print(f"PC=0x{pc:04X}")

    # 检查内存
    # 需要手动读取dmem的值...
    print("测试完成")

sim = Simulator(dut)
sim.add_clock(1e-6)
sim.add_testbench(bench)
with sim.write_vcd("test_store_load.vcd"):
    sim.run()
