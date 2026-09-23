from pathlib import Path
import sys

# Allow running the script directly (python sim/benches/test_jal.py)
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
    debug_ra: Out(32)  # 暴露$ra (register 31) 用于检查

    cpu_reset: In(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 实例化组件
        self.cpu = cpu = CPU()
        m.submodules.cpu = cpu
        m.submodules.imem = imem = MemoryFile(depth=256, sync_read=False)
        m.submodules.dmem = dmem = MemoryFile(depth=256, sync_read=True)

        # 连接CPU和内存
        m.d.comb += [
            cpu.reset.eq(self.cpu_reset),
            # 指令内存连接
            imem.read_addr.eq(Mux(self.imem_init_we, self.imem_init_addr, cpu.imem_addr[2:])),
            imem.write_addr.eq(self.imem_init_addr),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            # 数据内存连接
            dmem.read_addr.eq(cpu.dmem_read_addr[2:]),
            dmem.write_addr.eq(cpu.dmem_write_addr[2:]),
            dmem.write_data.eq(cpu.dmem_wdata),
            dmem.write_enable.eq(cpu.dmem_wen),
            cpu.dmem_rdata.eq(dmem.read_data),
            # 调试输出
            self.debug_pc.eq(cpu.imem_addr),
            self.debug_instr.eq(imem.read_data),
            # 这里的访问方式依赖于CPU内部实现，假设regfile暴露了mem
            # 注意：RegFile通常没有直接暴露所有寄存器的端口，我们可能需要hack一下或者只看写回
            # 但为了测试方便，我们可以观察 ALU写回阶段的数据，或者直接看 regfile 的内部信号（如果在仿真中可行）
            # 这里我们暂时只观察 PC 的变化，以及通过后续指令验证 $ra 的值
        ]

        return m


# ========== 辅助函数：加载程序 ==========
async def load_program(ctx, dut, program):
    """将程序加载到指令内存"""
    for i, instr in enumerate(program):
        ctx.set(dut.imem_init_addr, i)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    await ctx.tick()


def build_jal_test_spec() -> SimulationSpec:
    """测试JAL指令"""
    dut = CPUTestBench()

    async def bench(ctx):
        print("=" * 60)
        print("CPU测试 - JAL指令")
        print("=" * 60)

        # 目标跳转地址：0x00000040 (word index 16)
        target_addr_word = 16
        target_addr_byte = target_addr_word * 4

        # JAL指令位于地址 0x00000010 (word index 4)
        # PC+4 = 0x00000014
        # 预期 $ra = 0x00000014

        program = [
            nop(), # 0x00
            nop(), # 0x04
            nop(), # 0x08
            nop(), # 0x0C
            encode_j_type(Opcode.JAL, target_addr_word), # 0x10: JAL 0x40
            nop(), # 0x14: Delay slot (should be flushed/skipped or executed depending on implementation, current impl flushes)
            nop(), # 0x18
            nop(), # 0x1C
        ]

        # 填充NOP直到目标地址
        while len(program) < target_addr_word:
            program.append(nop())

        # 在目标地址处放置指令验证跳转成功
        # 0x40: ADDI $1, $31, 0  -> 将 $ra 移动到 $1 以便观察（或者直接检查 $ra 如果能访问）
        # 这里我们通过将 $ra 的值写入 $1，然后检查 $1 来验证 $ra 是否正确
        program.append(encode_i_type(Opcode.ADDI, 31, 1, 0)) # 0x40: $1 = $ra + 0
        program.append(nop())
        program.append(nop())
        program.append(nop())

        # Hold reset while loading program
        ctx.set(dut.cpu_reset, 1)
        await load_program(ctx, dut, program)
        ctx.set(dut.cpu_reset, 0)
        await ctx.tick()

        print("  运行CPU...")

        # 运行足够多的周期
        # 0-3: NOPs
        # 4: JAL (Fetch)
        # 5: JAL (Decode) -> PC update to 0x40, Flush 0x14
        # 6: Target (Fetch 0x40)
        # ...

        jal_pc = 0x10
        expected_ra = jal_pc + 4 # 0x14

        jump_occurred = False
        ra_correct = False

        for i in range(30):
            pc = ctx.get(dut.debug_pc)
            instr = ctx.get(dut.debug_instr)
            print(f"  Cycle {i}: PC={pc:08X}, Instr={instr:08X}")

            # 检查是否跳转到了 0x40
            if pc == target_addr_byte:
                jump_occurred = True
                print(f"  Cycle {i}: Jumped to target PC={pc:08X}")

            # 我们无法直接读取寄存器文件，但我们可以观察 ADDI $1, $31, 0 的执行结果
            # 这条指令在 0x40，它会在 WB 阶段写入 $1
            # 我们可以通过观察 cpu.regfile.wr_data 和 wr_addr 来验证
            # 需要访问内部信号

            # 在仿真中访问内部信号
            reg_wr_en = ctx.get(dut.cpu.regfile.wr_en)
            reg_wr_addr = ctx.get(dut.cpu.regfile.wr_addr)
            reg_wr_data = ctx.get(dut.cpu.regfile.wr_data)

            if reg_wr_en and reg_wr_addr == 1:
                print(f"  Cycle {i}: Register Write $1 = {reg_wr_data:08X}")
                if reg_wr_data == expected_ra:
                    ra_correct = True
                    print(f"    -> $ra value verified correct: {expected_ra:08X}")
                else:
                    print(f"    -> $ra value INCORRECT: expected {expected_ra:08X}, got {reg_wr_data:08X}")

            # 也可以检查 JAL 指令本身的写回 ($31)
            if reg_wr_en and reg_wr_addr == 31:
                 print(f"  Cycle {i}: JAL writing $31 = {reg_wr_data:08X}")
                 if reg_wr_data == expected_ra:
                     print(f"    -> JAL wrote correct return address")

            await ctx.tick()

        if not jump_occurred:
            print("FAIL: Did not jump to target address")
            assert False, "Did not jump to target address"

        if not ra_correct:
            print("FAIL: $ra value was not correct")
            assert False, "$ra value was not correct"

        print("✓ JAL测试通过")

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_jal_test.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-jal",
            name="CPU JAL Test",
            description="测试JAL指令跳转和链接功能",
            build=build_jal_test_spec,
            tags=("cpu", "jal"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
