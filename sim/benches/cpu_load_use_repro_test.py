"""
Regression reproducer for the missing load-use stall bug.

Program outline:
  1. ADDI $2, $0, DATA_BASE (0x80)
  2. ADDI $1, $0, 3
  3. SW   $1, 0($2)         ; write 3 into memory[0x80]
  4. LW   $5, 0($2)         ; load 3 into $5
  5. ADD  $6, $5, $1        ; should see 3 + 3 = 6, but hazard bug feeds 0
  6. SW   $6, 4($2)         ; expect memory[0x84] == 6, but the bug stores 3
  7. J    6 (infinite loop)
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


def encode_r_type(opcode, rs, rt, rd, shamt, funct):
    return (opcode << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct


def encode_i_type(opcode, rs, rt, imm):
    imm &= 0xFFFF
    return (opcode << 26) | (rs << 21) | (rt << 16) | imm


def encode_j_type(opcode, addr):
    addr &= 0x3FFFFFF
    return (opcode << 26) | addr


DATA_BASE_ADDR = 0x80
RESULT_OFFSET = 4
EXPECTED_STORE = 6
MAX_CYCLES = 80


class LoadUseReproBench(wiring.Component):
    imem_init_addr: In(32)
    imem_init_data: In(32)
    imem_init_we: In(1)

    reset: In(1)

    debug_pc: Out(32)
    dmem_addr_mon: Out(32)
    dmem_wdata_mon: Out(32)
    dmem_wen_mon: Out(1)

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
            cpu.reset.eq(self.reset),
            dmem.read_addr.eq(cpu.dmem_read_addr),
            dmem.write_addr.eq(cpu.dmem_write_addr),
            dmem.write_data.eq(cpu.dmem_wdata),
            dmem.write_enable.eq(cpu.dmem_wen),
            cpu.dmem_rdata.eq(dmem.read_data),
            self.debug_pc.eq(cpu.imem_addr),
            self.dmem_addr_mon.eq(cpu.dmem_addr),
            self.dmem_wdata_mon.eq(cpu.dmem_wdata),
            self.dmem_wen_mon.eq(cpu.dmem_wen),
        ]
        return m


async def load_program(ctx, dut, program):
    for i, instr in enumerate(program):
        ctx.set(dut.imem_init_addr, i * 4)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()

    await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    ctx.set(dut.reset, 1)
    await ctx.tick()
    await ctx.tick()
    ctx.set(dut.reset, 0)


def build_spec() -> SimulationSpec:
    dut = LoadUseReproBench()

    program = [
        encode_i_type(Opcode.ADDI, 0, 2, DATA_BASE_ADDR),  # 0x20020080 (ADDI $2, $0, 0x80)
        encode_i_type(Opcode.ADDI, 0, 1, 3),  # 0x20010003 (ADDI $1, $0, 3)
        encode_i_type(Opcode.SW, 2, 1, 0),  # 0xAC410000 (SW $1, 0($2))
        encode_i_type(Opcode.LW, 2, 5, 0),  # 0x8C450000 (LW $5, 0($2))
        encode_r_type(Opcode.R_TYPE, 5, 1, 6, 0, Funct.ADD),  # 0x00A13020 (ADD $6, $5, $1)
        encode_i_type(Opcode.SW, 2, 6, RESULT_OFFSET),  # 0xAC460004 (SW $6, 4($2))
        encode_j_type(Opcode.J, 6),  # 0x08000006 (J 6, infinite loop to halt progression)
    ]

    async def bench(ctx):
        await load_program(ctx, dut, program)

        result_addr = DATA_BASE_ADDR + RESULT_OFFSET
        for cycle in range(1, MAX_CYCLES + 1):
            await ctx.tick()
            if not ctx.get(dut.dmem_wen_mon):
                continue

            addr = ctx.get(dut.dmem_addr_mon)
            if addr != result_addr:
                continue

            data = ctx.get(dut.dmem_wdata_mon)
            if data != EXPECTED_STORE:
                raise AssertionError(
                    f"Load-Use hazard repro: expected store 0x{EXPECTED_STORE:08X} "
                    f"to 0x{result_addr:04X}, observed 0x{data:08X} at cycle {cycle}"
                )

            # Exit early once the correct store is observed.
            return

        raise AssertionError(
            f"Load-Use hazard repro: did not observe store to 0x{result_addr:04X} "
            f"within {MAX_CYCLES} cycles"
        )

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_load_use_repro.vcd")


def get_tests():
    return [
        SimulationTest(
            key="cpu-load-use-repro",
            name="CPU Load-Use Regression",
            description="Minimal program that fails without a load-use stall.",
            build=build_spec,
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
