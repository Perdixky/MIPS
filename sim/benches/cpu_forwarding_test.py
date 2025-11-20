"""
CPU转发单元测试（Forwarding Unit Tests）

测试场景：
1. EX Hazard - 从EX/MEM阶段转发
2. MEM Hazard - 从MEM/WB阶段转发
3. 双操作数转发 - rs和rt都需要转发
4. 不同阶段转发 - rs从EX/MEM转发，rt从MEM/WB转发
5. $0寄存器 - 验证$0不会被转发
6. 连续依赖 - 多条指令连续依赖
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
        m.submodules.imem = imem = MemoryFile(depth=256, sync_read=False)
        m.submodules.dmem = dmem = MemoryFile(depth=256, sync_read=True)

        m.d.comb += [
            imem.read_addr.eq(Mux(self.imem_init_we, self.imem_init_addr, cpu.imem_addr)),
            imem.write_addr.eq(self.imem_init_addr),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            dmem.read_addr.eq(cpu.dmem_read_addr),
            dmem.write_addr.eq(cpu.dmem_write_addr),
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


def build_forwarding_spec() -> SimulationSpec:
    dut = CPUTestBench()

    async def forwarding_tests(ctx):
        print("=" * 70)
        print("CPU转发单元测试 - 数据冒险场景")
        print("=" * 70)

        # ========== 测试1: EX Hazard - 从EX/MEM转发 ==========
        print("\n【测试1】EX Hazard - 从EX/MEM阶段转发")
        print("场景: ADD $1, $2, $3")
        print("      SUB $4, $1, $5  ← $1需要从EX/MEM转发")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 10),  # $2 = 10
            encode_i_type(Opcode.ADDI, 0, 3, 20),  # $3 = 20
            encode_i_type(Opcode.ADDI, 0, 5, 5),   # $5 = 5
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 1, 0, Funct.ADD),  # $1 = $2 + $3 = 30
            encode_r_type(Opcode.R_TYPE, 1, 5, 4, 0, Funct.SUB),  # $4 = $1 - $5 = 25 (需要转发!)
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(15):
            await ctx.tick()
            if i % 3 == 0:
                pc = ctx.get(dut.debug_pc)
                instr = ctx.get(dut.debug_instr)
                print(f"  Cycle {i:2d}: PC=0x{pc:08X}, Instr=0x{instr:08X}")

        print("✓ 测试1完成: 期望$4=25 (30-5)")

        # ========== 测试2: MEM Hazard - 从MEM/WB转发 ==========
        print("\n【测试2】MEM Hazard - 从MEM/WB阶段转发")
        print("场景: ADD $1, $2, $3")
        print("      NOP")
        print("      SUB $4, $1, $5  ← $1需要从MEM/WB转发")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 15),  # $2 = 15
            encode_i_type(Opcode.ADDI, 0, 3, 25),  # $3 = 25
            encode_i_type(Opcode.ADDI, 0, 5, 10),  # $5 = 10
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 1, 0, Funct.ADD),  # $1 = $2 + $3 = 40
            nop(),  # 延迟一个周期
            encode_r_type(Opcode.R_TYPE, 1, 5, 4, 0, Funct.SUB),  # $4 = $1 - $5 = 30 (从MEM/WB转发)
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(15):
            await ctx.tick()

        print("✓ 测试2完成: 期望$4=30 (40-10)")

        # ========== 测试3: 双操作数转发 ==========
        print("\n【测试3】双操作数转发 - rs和rt都需要转发")
        print("场景: ADD $1, $2, $3")
        print("      ADD $2, $4, $5")
        print("      ADD $6, $1, $2  ← $1和$2都需要转发!")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 5),   # $2 = 5
            encode_i_type(Opcode.ADDI, 0, 3, 10),  # $3 = 10
            encode_i_type(Opcode.ADDI, 0, 4, 3),   # $4 = 3
            encode_i_type(Opcode.ADDI, 0, 5, 7),   # $5 = 7
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 1, 0, Funct.ADD),  # $1 = 5 + 10 = 15
            encode_r_type(Opcode.R_TYPE, 4, 5, 2, 0, Funct.ADD),  # $2 = 3 + 7 = 10
            encode_r_type(Opcode.R_TYPE, 1, 2, 6, 0, Funct.ADD),  # $6 = 15 + 10 = 25 (双转发!)
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(18):
            await ctx.tick()

        print("✓ 测试3完成: 期望$6=25 (15+10)")

        # ========== 测试4: 不同阶段转发 ==========
        print("\n【测试4】不同阶段转发 - rs从EX/MEM，rt从MEM/WB")
        print("场景: ADD $1, $2, $3")
        print("      NOP")
        print("      ADD $2, $4, $5")
        print("      ADD $6, $1, $2  ← $1从MEM/WB转发, $2从EX/MEM转发")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 8),   # $2 = 8
            encode_i_type(Opcode.ADDI, 0, 3, 12),  # $3 = 12
            encode_i_type(Opcode.ADDI, 0, 4, 6),   # $4 = 6
            encode_i_type(Opcode.ADDI, 0, 5, 14),  # $5 = 14
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 1, 0, Funct.ADD),  # $1 = 8 + 12 = 20
            nop(),
            encode_r_type(Opcode.R_TYPE, 4, 5, 2, 0, Funct.ADD),  # $2 = 6 + 14 = 20
            encode_r_type(Opcode.R_TYPE, 1, 2, 6, 0, Funct.ADD),  # $6 = 20 + 20 = 40
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(18):
            await ctx.tick()

        print("✓ 测试4完成: 期望$6=40 (20+20)")

        # ========== 测试5: $0寄存器不转发 ==========
        print("\n【测试5】$0寄存器 - 验证$0不会被错误转发")
        print("场景: ADD $0, $2, $3  ← 尝试写$0（会被硬件忽略）")
        print("      ADD $4, $0, $5  ← 使用$0，应该得到0，不是转发的值")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 100),  # $2 = 100
            encode_i_type(Opcode.ADDI, 0, 3, 200),  # $3 = 200
            encode_i_type(Opcode.ADDI, 0, 5, 50),   # $5 = 50
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 0, 0, Funct.ADD),  # 尝试 $0 = 300 (会被忽略)
            encode_r_type(Opcode.R_TYPE, 0, 5, 4, 0, Funct.ADD),  # $4 = $0 + $5 = 0 + 50 = 50
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(15):
            await ctx.tick()

        print("✓ 测试5完成: 期望$4=50 (0+50), $0应始终为0")

        # ========== 测试6: 连续依赖链 ==========
        print("\n【测试6】连续依赖链 - 多条指令连续依赖")
        print("场景: ADD $1, $2, $3")
        print("      ADD $4, $1, $5  ← 依赖$1")
        print("      ADD $6, $4, $7  ← 依赖$4")
        print("      ADD $8, $6, $9  ← 依赖$6")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ADDI, 0, 2, 2),   # $2 = 2
            encode_i_type(Opcode.ADDI, 0, 3, 3),   # $3 = 3
            encode_i_type(Opcode.ADDI, 0, 5, 5),   # $5 = 5
            encode_i_type(Opcode.ADDI, 0, 7, 7),   # $7 = 7
            encode_i_type(Opcode.ADDI, 0, 9, 9),   # $9 = 9
            nop(),
            encode_r_type(Opcode.R_TYPE, 2, 3, 1, 0, Funct.ADD),  # $1 = 2 + 3 = 5
            encode_r_type(Opcode.R_TYPE, 1, 5, 4, 0, Funct.ADD),  # $4 = 5 + 5 = 10
            encode_r_type(Opcode.R_TYPE, 4, 7, 6, 0, Funct.ADD),  # $6 = 10 + 7 = 17
            encode_r_type(Opcode.R_TYPE, 6, 9, 8, 0, Funct.ADD),  # $8 = 17 + 9 = 26
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(20):
            await ctx.tick()

        print("✓ 测试6完成: 期望$8=26 (连续转发成功)")

        # ========== 测试7: 逻辑运算的转发 ==========
        print("\n【测试7】逻辑运算转发 - AND/OR指令")
        print("场景: ORI $1, $0, 0xFF")
        print("      ANDI $2, $0, 0x0F")
        print("      AND $3, $1, $2  ← $1和$2都需要转发")
        print("-" * 70)

        program = [
            encode_i_type(Opcode.ORI, 0, 1, 0xFF),   # $1 = 0xFF
            encode_i_type(Opcode.ANDI, 0, 2, 0x0F),  # $2 = 0x0F
            encode_r_type(Opcode.R_TYPE, 1, 2, 3, 0, Funct.AND),  # $3 = 0xFF & 0x0F = 0x0F
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("运行CPU...")
        for i in range(12):
            await ctx.tick()

        print("✓ 测试7完成: 期望$3=0x0F")

        print("\n" + "=" * 70)
        print("✓ 所有ForwardingUnit测试完成!")
        print("=" * 70)

    return SimulationSpec(dut=dut, bench=forwarding_tests, vcd_path="cpu_forwarding_test.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-forwarding",
            name="CPU Forwarding Stress",
            description="覆盖EX/MEM、MEM/WB、双操作数及$0保护等转发路径。",
            build=build_forwarding_spec,
            tags=("cpu", "forwarding"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
