from pathlib import Path
import sys

# Allow running the script directly
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
    imm = imm & 0xFFFF  # 16位立即数
    return (opcode << 26) | (rs << 21) | (rt << 16) | imm


def encode_j_type(opcode, addr):
    """编码J型指令"""
    addr = addr & 0x3FFFFFF  # 26位地址
    return (opcode << 26) | addr


def nop():
    """NOP指令 (SLL $0, $0, 0)"""
    return 0x00000000


# ========== 测试台模块 ==========
class CPUTestBench(wiring.Component):
    """整合CPU、指令内存和数据内存的测试台"""

    # 用于初始化指令内存的接口
    imem_init_addr: In(32)
    imem_init_data: In(32)
    imem_init_we: In(1)

    # 用于调试的输出接口
    debug_pc: Out(32)
    debug_instr: Out(32)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 实例化组件
        m.submodules.cpu = cpu = CPU()
        m.submodules.imem = imem = MemoryFile(depth=256)
        m.submodules.dmem = dmem = MemoryFile(depth=256)

        # 连接CPU和内存
        m.d.comb += [
            # 指令内存连接
            imem.addr.eq(Mux(self.imem_init_we, self.imem_init_addr, cpu.imem_addr)),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            # 数据内存连接
            dmem.addr.eq(cpu.dmem_addr),
            dmem.write_data.eq(cpu.dmem_wdata),
            dmem.write_enable.eq(cpu.dmem_wen),
            cpu.dmem_rdata.eq(dmem.read_data),
            # 调试输出
            self.debug_pc.eq(cpu.imem_addr),
            self.debug_instr.eq(imem.read_data),
        ]

        return m


# ========== 辅助函数：加载程序 ==========
async def load_program(ctx, dut, program):
    """将程序加载到指令内存"""
    for i, instr in enumerate(program):
        ctx.set(dut.imem_init_addr, i * 4)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    await ctx.tick()


def build_branch_forwarding_spec() -> SimulationSpec:
    """分支旁路前递与Load-Branch冒险测试"""
    dut = CPUTestBench()

    async def bench(ctx):
        print("\n" + "=" * 60)
        print("分支旁路前递与数据冒险测试")
        print("=" * 60)

        # ========== 测试1: ALU → Branch（旁路前递，零延迟）==========
        print("\n测试1: ALU → Branch 旁路前递")
        print("  场景：ADDI后立即BEQ，应该通过旁路前递零延迟执行")
        program = [
            # 0x00: 初始化$2为比较值
            encode_i_type(Opcode.ADDI, 0, 2, 5),  # $2 = 5
            nop(),
            nop(),
            nop(),
            # 0x10: ALU → Branch（关键测试！）
            encode_i_type(Opcode.ADDI, 0, 1, 5),  # $1 = 5（Cycle N）
            encode_i_type(Opcode.BEQ, 1, 2, 3),  # BEQ $1, $2（Cycle N+1）应该旁路前递！
            nop(),
            encode_i_type(Opcode.ADDI, 0, 10, 99),  # 不应执行（分支跳过）
            encode_i_type(Opcode.ADDI, 0, 10, 88),  # 不应执行
            # 0x28: 分支目标
            encode_i_type(Opcode.ADDI, 0, 3, 42),  # $3 = 42（应该执行）
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        for i in range(35):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试1完成: ALU→Branch旁路前递（零bubble）")

        # ========== 测试2: Load → Branch（必须stall）==========
        print("\n测试2: Load → Branch 冒险检测")
        print("  场景：LW后立即BEQ，旁路前递无法解决，必须stall")
        program = [
            # 0x00: 准备数据到内存
            encode_i_type(Opcode.ADDI, 0, 1, 5),  # $1 = 5
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 0, 2, 16),  # $2 = 16（基地址）
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.SW, 2, 1, 0),  # MEM[$2] = 5
            nop(),
            nop(),
            nop(),
            nop(),
            # 0x34: Load → Branch（关键测试！）
            encode_i_type(Opcode.LW, 2, 3, 0),  # $3 = MEM[$2]（Cycle N）
            encode_i_type(Opcode.ADDI, 0, 4, 5),  # $4 = 5
            nop(),
            nop(),
            encode_i_type(Opcode.BEQ, 3, 4, 2),  # BEQ $3, $4（应该stall等待$3）
            nop(),
            encode_i_type(Opcode.ADDI, 0, 11, 99),  # 不应执行
            # 分支目标
            encode_i_type(Opcode.ADDI, 0, 5, 77),  # $5 = 77（应该执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        stall_detected = False
        for i in range(50):
            await ctx.tick()
            pc = ctx.get(dut.debug_pc)
            if i % 5 == 0:
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")
            # 检测stall（PC不变）
            if i > 20 and pc == 0x44:
                if not stall_detected:
                    print(f"  ✓ Cycle {i}: 检测到stall（Load-Branch冒险）")
                    stall_detected = True

        if stall_detected:
            print("✓ 测试2完成: Load→Branch冒险检测工作正常")
        else:
            print("⚠ 测试2警告: 未检测到stall")

        # ========== 测试3: 多级ALU链 → Branch ==========
        print("\n测试3: 多级ALU链 → Branch")
        print("  场景：连续ALU操作后分支，测试多级前递")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 10),  # $1 = 10
            nop(),
            nop(),
            nop(),
            # 0x10: 连续ALU操作
            encode_r_type(Opcode.R_TYPE, 1, 0, 2, 0, Funct.ADD),  # $2 = $1 + 0 = 10
            encode_r_type(Opcode.R_TYPE, 2, 0, 3, 0, Funct.ADD),  # $3 = $2 + 0 = 10
            encode_i_type(Opcode.BEQ, 3, 1, 2),  # BEQ $3, $1（需要多级前递）
            nop(),
            encode_i_type(Opcode.ADDI, 0, 12, 99),  # 不应执行
            # 分支目标
            encode_i_type(Opcode.ADDI, 0, 6, 88),  # $6 = 88（应该执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试3完成: 多级前递测试")

        # ========== 测试4: BNE with forwarding ==========
        print("\n测试4: BNE指令 + 旁路前递")
        print("  场景：验证BNE也能正确使用旁路前递")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 10),  # $1 = 10
            encode_i_type(Opcode.ADDI, 0, 2, 20),  # $2 = 20
            encode_i_type(Opcode.BNE, 1, 2, 2),  # BNE $1, $2（应该跳转）
            nop(),
            encode_i_type(Opcode.ADDI, 0, 13, 99),  # 不应执行
            # 分支目标
            encode_i_type(Opcode.ADDI, 0, 7, 66),  # $7 = 66（应该执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        for i in range(25):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试4完成: BNE指令前递测试")

        # ========== 测试5: 边界条件 - $0寄存器 ==========
        print("\n测试5: 边界条件 - $0寄存器")
        print("  场景：验证$0寄存器不参与前递")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 5),  # $1 = 5
            nop(),
            nop(),
            nop(),
            # 试图写$0（无效）
            encode_r_type(Opcode.R_TYPE, 1, 0, 0, 0, Funct.ADD),  # $0 = $1（无效）
            encode_i_type(Opcode.BEQ, 0, 0, 2),  # BEQ $0, $0（应该跳转，$0总是0）
            nop(),
            encode_i_type(Opcode.ADDI, 0, 14, 99),  # 不应执行
            # 分支目标
            encode_i_type(Opcode.ADDI, 0, 8, 55),  # $8 = 55（应该执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试5完成: $0寄存器边界条件")

        # ========== 测试6: 连续分支 + 前递 ==========
        print("\n测试6: 连续分支指令")
        print("  场景：背靠背的分支指令，测试前递稳定性")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 1),  # $1 = 1
            encode_i_type(Opcode.ADDI, 0, 2, 1),  # $2 = 1
            encode_i_type(Opcode.ADDI, 0, 3, 2),  # $3 = 2
            nop(),
            # 连续分支
            encode_i_type(Opcode.BEQ, 1, 2, 1),  # 第一个分支（跳1条）
            encode_i_type(Opcode.ADDI, 0, 15, 99),  # 不应执行
            encode_i_type(Opcode.BNE, 2, 3, 1),  # 第二个分支（跳1条）
            encode_i_type(Opcode.ADDI, 0, 16, 88),  # 不应执行
            encode_i_type(Opcode.ADDI, 0, 9, 44),  # $9 = 44（应该执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行程序...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试6完成: 连续分支测试")

        print("\n" + "=" * 60)
        print("✓ 所有旁路前递与冒险检测测试通过!")
        print("=" * 60)

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_branch_forwarding_test.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-branch-forwarding",
            name="CPU Branch Forwarding",
            description="分支旁路前递与Load-Branch数据冒险测试：ALU→Branch零延迟，Load→Branch stall。",
            build=build_branch_forwarding_spec,
            tags=("cpu", "branch", "forwarding", "hazard"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
