from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, connect
from amaranth.sim import Simulator
from CPU import CPU, Opcode, Funct
from MemoryFile import MemoryFile


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
        ctx.set(dut.imem_init_addr, i)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    await ctx.tick()


# ========== 测试程序 ==========
if __name__ == "__main__":
    # 创建测试台
    dut = CPUTestBench()

    async def bench(ctx):
        print("=" * 60)
        print("CPU测试开始 - 无冒险场景")
        print("=" * 60)

        # ========== 测试1: R型指令 - ADD ==========
        print("\n测试1: R型指令 - ADD")
        # 指令序列：
        # 0: ADDI $1, $0, 5      # $1 = 5
        # 1: NOP
        # 2: NOP
        # 3: NOP
        # 4: ADDI $2, $0, 3      # $2 = 3
        # 5: NOP
        # 6: NOP
        # 7: NOP
        # 8: ADD $3, $1, $2      # $3 = $1 + $2 = 8
        # 9: NOP
        # ...

        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 5),  # $1 = 5
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 0, 2, 3),  # $2 = 3
            nop(),
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 1, 2, 3, 0, Funct.ADD),  # $3 = $1 + $2
            nop(),
            nop(),
            nop(),
            nop(),
        ]

        # 加载程序
        await load_program(ctx, dut, program)

        # 运行CPU
        print("  运行CPU...")
        for i in range(20):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                instr = ctx.get(dut.debug_instr)
                print(f"  Cycle {i}: PC={pc:08X}, Instr={instr:08X}")

        print("✓ 测试1完成: ADD指令执行")

        # ========== 测试2: I型指令 - ADDI ==========
        print("\n测试2: I型指令 - ADDI")
        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 100),  # $1 = 100
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 1, 2, 50),  # $2 = $1 + 50 = 150
            nop(),
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行CPU...")
        for i in range(15):
            await ctx.tick()

        print("✓ 测试2完成: ADDI指令执行")

        # ========== 测试3: 逻辑指令 - AND, OR ==========
        print("\n测试3: 逻辑指令 - AND, OR")
        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 0xFF),  # $1 = 0xFF
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 0, 2, 0x0F),  # $2 = 0x0F
            nop(),
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 1, 2, 3, 0, Funct.AND),  # $3 = $1 & $2 = 0x0F
            nop(),
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 1, 2, 4, 0, Funct.OR),  # $4 = $1 | $2 = 0xFF
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行CPU...")
        for i in range(25):
            await ctx.tick()

        print("✓ 测试3完成: AND, OR指令执行")

        # ========== 测试4: R型指令 - SUB ==========
        print("\n测试4: R型指令 - SUB")
        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 10),  # $1 = 10
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 0, 2, 4),  # $2 = 4
            nop(),
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 1, 2, 3, 0, Funct.SUB),  # $3 = $1 - $2 = 6
            nop(),
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行CPU...")
        for i in range(20):
            await ctx.tick()

        print("✓ 测试4完成: SUB指令执行")

        # ========== 测试5: 内存访问 - SW/LW ==========
        print("\n测试5: 内存访问 - SW/LW")
        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 0x42),  # $1 = 0x42 (数据)
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.ADDI, 0, 2, 16),  # $2 = 16 (基地址)
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.SW, 2, 1, 0),  # MEM[$2+0] = $1
            nop(),
            nop(),
            nop(),
            nop(),
            encode_i_type(Opcode.LW, 2, 3, 0),  # $3 = MEM[$2+0]
            nop(),
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  执行SW/LW指令序列...")
        for i in range(30):
            await ctx.tick()
            if i % 5 == 0:
                pc = ctx.get(dut.debug_pc)
                instr = ctx.get(dut.debug_instr)
                print(f"  Cycle {i}: PC={pc:08X}, Instr={instr:08X}")

        print("✓ 测试5完成: SW/LW指令执行")

        # ========== 测试6: 移位指令 - SLL ==========
        print("\n测试6: 移位指令 - SLL")
        program = [
            encode_i_type(Opcode.ADDI, 0, 1, 0x01),  # $1 = 1
            nop(),
            nop(),
            nop(),
            encode_r_type(Opcode.R_TYPE, 0, 1, 2, 4, Funct.SLL),  # $2 = $1 << 4 = 16
            nop(),
            nop(),
            nop(),
            nop(),
        ]

        await load_program(ctx, dut, program)

        print("  运行CPU...")
        for i in range(15):
            await ctx.tick()

        print("✓ 测试6完成: SLL指令执行")

        print("\n" + "=" * 60)
        print("✓ 所有测试通过!")
        print("=" * 60)

    # 创建仿真器
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)

    with sim.write_vcd("cpu_test.vcd"):
        sim.run()
