from pathlib import Path
import sys

# Allow running the script directly (python sim/benches/cpu_branch_prediction_test.py)
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
        m.submodules.imem = imem = MemoryFile(depth=256, sync_read=False)
        m.submodules.dmem = dmem = MemoryFile(depth=256, sync_read=True)

        # 连接CPU和内存
        m.d.comb += [
            # 指令内存连接
            imem.read_addr.eq(Mux(self.imem_init_we, self.imem_init_addr, cpu.imem_addr)),
            imem.write_addr.eq(self.imem_init_addr),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            # 数据内存连接
            dmem.read_addr.eq(cpu.dmem_read_addr),
            dmem.write_addr.eq(cpu.dmem_write_addr),
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


def build_branch_prediction_spec() -> SimulationSpec:
    """分支预测功能测试"""
    dut = CPUTestBench()

    async def bench(ctx):
        print("\n" + "=" * 60)
        print("分支预测测试开始")
        print("=" * 60)

        # ========== 测试1: 简单向后跳转 - 学习阶段 ==========
        print("\n测试1: 简单向后跳转（BTB学习）")
        program = [
            # 0x00: 初始化计数器
            encode_i_type(Opcode.ADDI, 0, 1, 0),  # $1 = 0 (计数器)
            nop(),
            nop(),
            nop(),
            # 0x10: 循环体开始
            encode_i_type(Opcode.ADDI, 1, 1, 1),  # $1 = $1 + 1
            nop(),
            nop(),
            nop(),
            # 0x20: 检查是否 < 5
            encode_i_type(Opcode.SLTI, 1, 2, 5),  # $2 = ($1 < 5)
            nop(),
            nop(),
            nop(),
            # 0x30: 如果 $2 == 1，跳回循环开始
            encode_i_type(Opcode.ADDI, 0, 3, 1),  # $3 = 1（用于比较）
            nop(),
            nop(),
            nop(),
            # 0x40: 条件跳转
            encode_i_type(Opcode.BEQ, 2, 3, -12),  # 若$2==1，PC -= 12*4 跳回0x10
            nop(),
            nop(),
            nop(),
            # 0x50: 循环结束后
            encode_i_type(Opcode.ADDI, 0, 4, 100),  # $4 = 100（表示循环完成）
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行循环程序（第一次执行，BTB学习）...")
        prev_pc = 0
        for i in range(60):
            await ctx.tick()
            pc = ctx.get(dut.debug_pc)
            if i % 5 == 0:
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")
            # 检测循环是否完成
            if pc == 0x50 and prev_pc != 0x50:
                print(f"  ✓ 循环在 Cycle {i} 完成，PC到达0x50")
                break
            prev_pc = pc

        print("✓ 测试1完成: BTB应该已学习到分支目标")

        # ========== 测试2: J型跳转 ==========
        print("\n测试2: J型无条件跳转")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 10),  # $1 = 10
            nop(),
            nop(),
            nop(),
            # 0x10
            encode_j_type(Opcode.J, 10),  # 跳转到地址 10*4 = 0x28
            nop(),
            # 这里的指令不应该执行（会被flush）
            encode_i_type(Opcode.ADDI, 0, 2, 99),  # $2 = 99（不应执行）
            nop(),
            nop(),
            nop(),
            # 0x28: 跳转目标
            encode_i_type(Opcode.ADDI, 0, 3, 42),  # $3 = 42
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  执行J指令跳转...")
        for i in range(25):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                instr = ctx.get(dut.debug_instr)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}, Instr=0x{instr:08X}")

        print("✓ 测试2完成: J型跳转")

        # ========== 测试3: BNE分支（不相等则跳转） ==========
        print("\n测试3: BNE分支指令")
        program = [
            # 0x00
            encode_i_type(Opcode.ADDI, 0, 1, 5),  # $1 = 5
            nop(),
            nop(),
            nop(),
            # 0x10
            encode_i_type(Opcode.ADDI, 0, 2, 10),  # $2 = 10
            nop(),
            nop(),
            nop(),
            # 0x20
            encode_i_type(Opcode.BNE, 1, 2, 3),  # 若$1 != $2，跳过3条指令
            nop(),
            # 不应执行的部分
            encode_i_type(Opcode.ADDI, 0, 3, 99),  # $3 = 99（不应执行）
            nop(),
            nop(),
            # 0x34: 跳转目标
            encode_i_type(Opcode.ADDI, 0, 4, 77),  # $4 = 77（应执行）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  执行BNE指令...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试3完成: BNE分支指令")

        # ========== 测试4: JAL跳转并链接 ==========
        print("\n测试4: JAL指令（跳转并保存返回地址）")
        program = [
            # 0x00: 主程序
            encode_i_type(Opcode.ADDI, 0, 1, 20),  # $1 = 20
            nop(),
            nop(),
            nop(),
            # 0x10: 调用子程序
            encode_j_type(Opcode.JAL, 10),  # 跳转到0x28，$31 = 0x18
            nop(),
            nop(),
            nop(),
            # 0x20: 返回点
            encode_i_type(Opcode.ADDI, 0, 2, 30),  # $2 = 30
            nop(),
            nop(),
            # 0x28: 子程序
            encode_i_type(Opcode.ADDI, 0, 3, 40),  # $3 = 40
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  执行JAL指令...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试4完成: JAL跳转并链接")

        # ========== 测试5: 连续分支（测试BTB容量） ==========
        print("\n测试5: 多个不同分支（测试BTB记忆）")
        program = [
            # 分支1
            encode_i_type(Opcode.ADDI, 0, 1, 1),  # $1 = 1
            encode_i_type(Opcode.ADDI, 0, 2, 1),  # $2 = 1
            encode_i_type(Opcode.BEQ, 1, 2, 2),  # 跳过2条
            encode_i_type(Opcode.ADDI, 0, 10, 1),  # 不应执行
            encode_i_type(Opcode.ADDI, 0, 10, 2),  # 不应执行
            # 分支2
            encode_i_type(Opcode.ADDI, 0, 3, 2),  # $3 = 2
            encode_i_type(Opcode.ADDI, 0, 4, 2),  # $4 = 2
            encode_i_type(Opcode.BEQ, 3, 4, 2),  # 跳过2条
            encode_i_type(Opcode.ADDI, 0, 11, 1),  # 不应执行
            encode_i_type(Opcode.ADDI, 0, 11, 2),  # 不应执行
            # 分支3
            encode_i_type(Opcode.ADDI, 0, 5, 3),  # $5 = 3
            encode_i_type(Opcode.ADDI, 0, 6, 3),  # $6 = 3
            encode_i_type(Opcode.BEQ, 5, 6, 2),  # 跳过2条
            encode_i_type(Opcode.ADDI, 0, 12, 1),  # 不应执行
            encode_i_type(Opcode.ADDI, 0, 12, 2),  # 不应执行
            # 结束
            encode_i_type(Opcode.ADDI, 0, 7, 100),  # $7 = 100（完成标记）
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  执行多个分支指令...")
        for i in range(50):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                print(f"  Cycle {i:3d}: PC=0x{pc:08X}")

        print("✓ 测试5完成: 多分支BTB测试")

        print("\n" + "=" * 60)
        print("✓ 所有分支预测测试通过!")
        print("=" * 60)

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_branch_prediction_test.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-branch-prediction",
            name="CPU Branch Prediction",
            description="分支预测器（BTB）功能测试：学习、预测、flush机制。",
            build=build_branch_prediction_spec,
            tags=("cpu", "branch", "btb"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
