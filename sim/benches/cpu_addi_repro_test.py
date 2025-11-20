"""
Minimal reproducer for ADDI immediate doubling bug.

Program outline:
  1. ADDI $1, $0, DATA_BASE (0x80)
  2. ADDI $10, $0, 0x11111111
  3. SW   $10, 0($1)
  4. ADDI $1, $1, 4
  5. ADDI $10, $0, 0x22222222
  6. SW   $10, 0($1)
  7. ADDI $1, $1, 4
  8. ADDI $10, $0, 0x33333333
  9. SW   $10, 0($1)
  10. J    done (infinite loop)
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


WORD_BYTES = 4
DATA_BASE_ADDR = 0x80


class AddiReproBench(wiring.Component):
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
    await ctx.tick()
    await ctx.tick()
    ctx.set(dut.reset, 0)


def build_spec() -> SimulationSpec:
    dut = AddiReproBench()

    # Test immediates (will be truncated to 16-bit)
    test_immediates = [0x11111111, 0x22222222, 0x33333333]

    # Build program with detailed comments
    program = []

    print("\n" + "="*70)
    print("Program Assembly Listing")
    print("="*70)
    print("Addr   Hex        Assembly              Description")
    print("-"*70)

    # Instruction 0: ADDI $1, $0, 0x80
    # Initialize base address register $1 = DATA_BASE_ADDR (0x80)
    instr = encode_i_type(Opcode.ADDI, 0, 1, DATA_BASE_ADDR)
    program.append(instr)
    print(f"0x{0*4:04X}  0x{instr:08X}  ADDI $1, $0, 0x{DATA_BASE_ADDR:04X}   Initialize base addr (0x80)")

    # For each test immediate
    for idx, imm in enumerate(test_immediates):
        imm16 = imm & 0xFFFF  # Truncate to 16-bit

        # ADDI $10, $0, imm (load immediate into $10)
        instr = encode_i_type(Opcode.ADDI, 0, 10, imm16)
        addr = len(program) * 4
        program.append(instr)
        print(f"0x{addr:04X}  0x{instr:08X}  ADDI $10, $0, 0x{imm16:04X}  Load imm #{idx+1} into $10 (from 0x{imm:08X})")

        # SW $10, 0($1) (store $10 to memory)
        instr = encode_i_type(Opcode.SW, 1, 10, 0)
        addr = len(program) * 4
        program.append(instr)
        print(f"0x{addr:04X}  0x{instr:08X}  SW   $10, 0($1)        Store $10 to mem[${1}+0]")

        # ADDI $1, $1, WORD_BYTES (increment address)
        instr = encode_i_type(Opcode.ADDI, 1, 1, WORD_BYTES)
        addr = len(program) * 4
        program.append(instr)
        print(f"0x{addr:04X}  0x{instr:08X}  ADDI $1, $1, {WORD_BYTES}        Increment addr by {WORD_BYTES} bytes")

    # Infinite loop: J done
    done_addr = len(program)
    instr = encode_j_type(Opcode.J, done_addr)
    addr = len(program) * 4
    program.append(instr)
    print(f"0x{addr:04X}  0x{instr:08X}  J    0x{done_addr*4:04X}            Infinite loop (halt)")

    print("="*70)
    print(f"Total instructions: {len(program)}")
    print("="*70 + "\n")

    async def bench(ctx):
        await load_program(ctx, dut, program)

        observed = {}
        store_trace = []

        for cycle in range(80):
            await ctx.tick()
            if ctx.get(dut.dmem_wen_mon):
                addr = ctx.get(dut.dmem_addr_mon)
                data = ctx.get(dut.dmem_wdata_mon)
                observed[addr] = data
                store_trace.append((cycle, addr, data))

        print("\nStore trace (cycle, addr, data):")
        for cycle, addr, data in store_trace:
            print(f"  cycle={cycle:03d} addr=0x{addr:04X} data=0x{data:08X}")

        # Expected values (sign-extended from 16-bit)
        expected = {}
        addr = DATA_BASE_ADDR
        for imm in test_immediates:
            # Sign-extend the 16-bit immediate
            imm16 = imm & 0xFFFF
            if imm16 & 0x8000:
                expected_val = imm16 | 0xFFFF0000
            else:
                expected_val = imm16
            expected[addr] = expected_val & 0xFFFFFFFF
            addr += WORD_BYTES

        print("\nExpected stores:")
        for addr, data in expected.items():
            print(f"  addr=0x{addr:04X} data=0x{data:08X}")

        # Verify results
        mismatches = []
        for addr, expected_val in expected.items():
            actual = observed.get(addr)
            if actual != expected_val:
                actual_str = "None" if actual is None else f"0x{actual:08X}"
                mismatches.append(
                    f"addr 0x{addr:04X}: expected 0x{expected_val:08X}, observed {actual_str}"
                )

        if mismatches:
            raise AssertionError("ADDI immediate mismatches detected:\n" + "\n".join(mismatches))

        print(f"✓ All {len(expected)} ADDI operations produced correct results.")

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_addi_repro.vcd")


def get_tests():
    return [
        SimulationTest(
            key="cpu-addi-repro",
            name="CPU ADDI Immediate Repro",
            description="Minimal program to reproduce ADDI immediate doubling bug.",
            build=build_spec,
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
