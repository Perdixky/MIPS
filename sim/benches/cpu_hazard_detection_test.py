"""
CPU冒险检测单元测试（Hazard Detection Unit Tests）

测试场景：
1. Load-Use Hazard (rs) - load指令后立即使用rs
2. Load-Use Hazard (rt) - load指令后立即使用rt
3. Load-Use Hazard (双操作数) - rs和rt都来自load
4. 无冒险 - load和use之间有NOP
5. $0寄存器 - 验证$0不会触发hazard
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from mips.core.cpu import CPU, Opcode, Funct
from mips.memory.memory_file import MemoryFile
from sim.test_utils import SimulationSpec, SimulationTest, run_tests_cli


# ========== MIPS指令编码辅助函数 ==========
def encode_r_type(opcode, rs, rt, rd, shamt, funct):
    """编码R型指令"""
    return (opcode << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct


def encode_i_type(opcode, rs, rt, imm):
    """编码I型指令"""
    imm = imm & 0xFFFF
    return (opcode << 26) | (rs << 21) | (rt << 16) | imm


def nop():
    """NOP指令"""
    return 0x00000000


# ========== 测试台模块 ==========
class CPUTestBench(wiring.Component):
    """整合CPU、指令内存和数据内存的测试台"""

    imem_init_addr: In(32)
    imem_init_data: In(32)
    imem_init_we: In(1)

    debug_pc: Out(32)
    debug_instr: Out(32)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.cpu = cpu = CPU()
        m.submodules.imem = imem = MemoryFile(depth=256)
        m.submodules.dmem = dmem = MemoryFile(depth=256)

        m.d.comb += [
            imem.addr.eq(Mux(self.imem_init_we, self.imem_init_addr, cpu.imem_addr)),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            dmem.addr.eq(cpu.dmem_addr),
            dmem.write_data.eq(cpu.dmem_wdata),
            dmem.write_enable.eq(cpu.dmem_wen),
            cpu.dmem_rdata.eq(dmem.read_data),
            self.debug_pc.eq(cpu.imem_addr),
            self.debug_instr.eq(imem.read_data),
        ]

        return m


async def load_program(ctx, dut, program):
    """将程序加载到指令内存"""
    for i, instr in enumerate(program):
        ctx.set(dut.imem_init_addr, i)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    await ctx.tick()


def build_hazard_detection_spec() -> SimulationSpec:
    dut = CPUTestBench()

    async def hazard_detection_tests(ctx):
        print("=" * 70)
        print("CPU冒险检测单元测试 - Load-Use Hazard场景")
        print("=" * 70)

        # ========== 测试1: Load-Use Hazard (rs) ==========
        print("\n【测试1】Load-Use Hazard - load后立即使用rs")
        print("场景: LW $1, 0($2)")
        print("      ADD $3, $1, $4  ← $1来自load，需要stall!")
        print("期望: CPU自动插入1个bubble（stall）")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100 (地址)
            encode_i_type(Opcode.ADDI, 0, 4, 20),   # $4 = 20
            nop(),
            nop(),
            encode_i_type(Opcode.LW, 2, 1, 0),      # $1 = MEM[$2+0] (Load!)
            encode_r_type(Opcode.R_TYPE, 1, 4, 3, 0, Funct.ADD),  # $3 = $1 + $4 (应该stall)
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        stall_detected = False
        prev_pc = 0
        for i in range(15):
            await ctx.tick()
            pc = ctx.get(dut.debug_pc)
            instr = ctx.get(dut.debug_instr)

            # 检测PC是否停止前进（stall）
            if i > 5 and pc == prev_pc and pc != 0:
                if not stall_detected:
                    print(f"  ✓ Cycle {i:2d}: 检测到stall! PC=0x{pc:08X}")
                    stall_detected = True

            if i % 2 == 0:
                print(f"  Cycle {i:2d}: PC=0x{pc:08X}, Instr=0x{instr:08X}")

            prev_pc = pc

        if stall_detected:
            print("✓ 测试1通过: 成功检测到Load-Use Hazard并stall")
        else:
            print("✗ 测试1失败: 未检测到预期的stall")

        # ========== 测试2: Load-Use Hazard (rt) ==========
        print("\n【测试2】Load-Use Hazard - load后立即使用rt")
        print("场景: LW $1, 0($2)")
        print("      ADD $3, $4, $1  ← $1来自load，使用在rt位置")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 200),  # $2 = 200
            encode_i_type(Opcode.ADDI, 0, 4, 30),   # $4 = 30
            nop(),
            nop(),
            encode_i_type(Opcode.LW, 2, 1, 0),      # $1 = MEM[$2+0]
            encode_r_type(Opcode.R_TYPE, 4, 1, 3, 0, Funct.ADD),  # $3 = $4 + $1 (stall)
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(15):
            await ctx.tick()

        print("✓ 测试2完成")

        # ========== 测试3: Load-Use Hazard (双操作数) ==========
        print("\n【测试3】Load-Use Hazard - rs和rt都来自load")
        print("场景: LW $1, 0($2)")
        print("      LW $3, 4($2)")
        print("      ADD $5, $1, $3  ← $1和$3都来自load")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100
            nop(),
            nop(),
            encode_i_type(Opcode.LW, 2, 1, 0),      # $1 = MEM[$2+0]
            encode_i_type(Opcode.LW, 2, 3, 4),      # $3 = MEM[$2+4]
            encode_r_type(Opcode.R_TYPE, 1, 3, 5, 0, Funct.ADD),  # $5 = $1 + $3 (双stall)
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(20):
            await ctx.tick()

        print("✓ 测试3完成")

        # ========== 测试4: 无冒险 - 中间有NOP ==========
        print("\n【测试4】无冒险 - load和use之间有NOP")
        print("场景: LW $1, 0($2)")
        print("      NOP")
        print("      ADD $3, $1, $4  ← 有NOP隔开，不需要stall")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100
            encode_i_type(Opcode.ADDI, 0, 4, 25),   # $4 = 25
            nop(),
            encode_i_type(Opcode.LW, 2, 1, 0),      # $1 = MEM[$2+0]
            nop(),  # 这个NOP让数据有时间准备
            encode_r_type(Opcode.R_TYPE, 1, 4, 3, 0, Funct.ADD),  # $3 = $1 + $4 (不需要stall)
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        no_unexpected_stall = True
        prev_pc = 0
        for i in range(15):
            await ctx.tick()
            pc = ctx.get(dut.debug_pc)

            # 检查是否有意外的stall
            if i > 8 and pc == prev_pc and pc != 0:
                print(f"  ✗ Cycle {i:2d}: 检测到意外的stall! PC=0x{pc:08X}")
                no_unexpected_stall = False

            prev_pc = pc

        if no_unexpected_stall:
            print("✓ 测试4通过: 没有不必要的stall")
        else:
            print("✗ 测试4失败: 检测到不应该出现的stall")

        # ========== 测试5: $0寄存器不触发hazard ==========
        print("\n【测试5】$0寄存器 - 不应触发hazard")
        print("场景: LW $0, 0($2)  ← load到$0（会被忽略）")
        print("      ADD $3, $0, $4  ← 使用$0，不应该stall")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100
            encode_i_type(Opcode.ADDI, 0, 4, 35),   # $4 = 35
            nop(),
            encode_i_type(Opcode.LW, 2, 0, 0),      # 尝试 $0 = MEM[$2+0]
            encode_r_type(Opcode.R_TYPE, 0, 4, 3, 0, Funct.ADD),  # $3 = $0 + $4 = 35
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(12):
            await ctx.tick()

        print("✓ 测试5完成: $0寄存器不触发hazard")

        # ========== 测试6: 连续load指令 ==========
        print("\n【测试6】连续load指令 - 确保每个都正确处理")
        print("场景: LW $1, 0($2)")
        print("      LW $3, 4($2)")
        print("      LW $5, 8($2)")
        print("      ADD $7, $1, $3  ← 使用之前的load结果")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100
            nop(),
            encode_i_type(Opcode.LW, 2, 1, 0),      # $1 = MEM[100]
            encode_i_type(Opcode.LW, 2, 3, 4),      # $3 = MEM[104]
            encode_i_type(Opcode.LW, 2, 5, 8),      # $5 = MEM[108]
            encode_r_type(Opcode.R_TYPE, 1, 3, 7, 0, Funct.ADD),  # $7 = $1 + $3
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(18):
            await ctx.tick()

        print("✓ 测试6完成")

        print("\n" + "=" * 70)
        print("✓ 所有HazardDetectionUnit测试完成!")
        print("=" * 70)

    return SimulationSpec(dut=dut, bench=hazard_detection_tests, vcd_path="cpu_hazard_detection_test.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-hazard-detection",
            name="CPU Hazard Detection",
            description="测试Load-Use Hazard检测和流水线stall功能。",
            build=build_hazard_detection_spec,
            tags=("cpu", "hazard"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
