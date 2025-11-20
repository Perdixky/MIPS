"""
Minimal reproduction for branch operand hazard bug.

This test isolates a defect where BEQ reads stale register values when the
producer instruction is in the immediately preceding cycle. The bug manifests
in ANDI→BEQ sequences where the branch compares a register against zero
immediately after that register is written.

Expected behavior:
  - even sum = 8 (only value 8)
  - odd sum = 20 (values 3 + 17)

Actual buggy behavior:
  - even sum = 0 (branch reads stale non-zero value, skips even path)
  - odd sum = 20 (works by accident because $11 retained previous non-zero)

Root cause:
  - No forwarding/stall path for branch operand reads
  - BEQ in ID stage reads from register file before ANDI's write in WB stage
  - Branch forwarding only covers EX/MEM/WB stages, not ID/EX (ANDI is still in EX)

Program outline (with machine code):
  1. Initialize even_sum ($8) = 0, odd_sum ($9) = 0
     PC=0:  ADDI $2, $0, 0x180    # 0x20020180 - result base address
     PC=4:  ADDI $8, $0, 0        # 0x20080000 - even_sum = 0
     PC=8:  ADDI $9, $0, 0        # 0x20090000 - odd_sum = 0

  2. For each value in [3, 8, 17]:
     a. ADDI $10, $0, value       # 0x200a000{3,8,11} - load value
     b. ANDI $11, $10, 1          # 0x314b0001 - check LSB (odd/even)
     c. BEQ $11, $0, even         # 0x11600002 - branch if even (offset=2)
                                  #   *** BUG: reads stale $11! ***
     d. ADD $9, $9, $10           # 0x012a4820 - odd path
     e. J join                    # 0x0800000{9,f,15} - skip even path
     f. even: ADD $8, $8, $10     # 0x010a4020 - even path
     g. join: continue

  3. Store results
     SW $8, 0($2)                 # 0xac480000 - store even_sum
     ADDI $2, $2, 4               # 0x20420004 - advance pointer
     SW $9, 0($2)                 # 0xac490000 - store odd_sum
     ADDI $2, $2, 4               # 0x20420004 - advance pointer

  4. J done                       # 0x08000019 - infinite loop to PC=100
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


MASK32 = 0xFFFFFFFF
RESULT_BASE_ADDR = 0x180


class ProgramBuilder:
    """Helper class to build MIPS programs with labels."""

    def __init__(self):
        self.instructions = []
        self.labels = {}
        self.unresolved_branches = []
        self.unresolved_jumps = []

    def label(self, name):
        """Mark current position with a label."""
        self.labels[name] = len(self.instructions)

    def emit_r_type(self, opcode, rs, rt, rd, shamt, funct):
        """Emit R-type instruction."""
        inst = (opcode << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct
        self.instructions.append(inst)

    def emit_i_type(self, opcode, rs, rt, imm):
        """Emit I-type instruction."""
        imm &= 0xFFFF
        inst = (opcode << 26) | (rs << 21) | (rt << 16) | imm
        self.instructions.append(inst)

    def emit_branch(self, opcode, rs, rt, label):
        """Emit branch instruction with symbolic label."""
        self.unresolved_branches.append((len(self.instructions), rs, rt, label))
        self.emit_i_type(opcode, rs, rt, 0)  # placeholder

    def emit_jump(self, opcode, label):
        """Emit jump instruction with symbolic label."""
        self.unresolved_jumps.append((len(self.instructions), label))
        addr = 0  # placeholder
        inst = (opcode << 26) | addr
        self.instructions.append(inst)

    def program(self):
        """Resolve labels and return final program."""
        prog = list(self.instructions)

        # Resolve branches (PC-relative)
        for idx, rs, rt, label in self.unresolved_branches:
            if label not in self.labels:
                raise ValueError(f"Undefined label: {label}")
            target_idx = self.labels[label]
            # Branch offset = (target - (PC+4)) / 4 = target - (idx+1)
            offset = target_idx - (idx + 1)
            offset &= 0xFFFF  # sign-extend to 16 bits
            opcode = (prog[idx] >> 26) & 0x3F
            prog[idx] = (opcode << 26) | (rs << 21) | (rt << 16) | offset

        # Resolve jumps (absolute)
        for idx, label in self.unresolved_jumps:
            if label not in self.labels:
                raise ValueError(f"Undefined label: {label}")
            target_idx = self.labels[label]
            target_addr = target_idx  # word address (will be shifted by 2 in hardware)
            opcode = (prog[idx] >> 26) & 0x3F
            prog[idx] = (opcode << 26) | (target_addr & 0x3FFFFFF)

        return prog


class BranchHazardBench(wiring.Component):
    """Test bench for branch operand hazard."""

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
    """Load program into instruction memory and reset CPU."""
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
    """Build test specification."""
    dut = BranchHazardBench()

    # Test values: two odd (3, 17) and one even (8)
    values = [3, 8, 17]

    builder = ProgramBuilder()

    # Initialize result base address and accumulators
    builder.emit_i_type(Opcode.ADDI, 0, 2, RESULT_BASE_ADDR)  # ADDI $2, $0, 0x180  (0x20020180)
    builder.emit_i_type(Opcode.ADDI, 0, 8, 0)                  # ADDI $8, $0, 0      (0x20080000)
    builder.emit_i_type(Opcode.ADDI, 0, 9, 0)                  # ADDI $9, $0, 0      (0x20090000)

    # Process each value
    for value in values:
        # ADDI $10, $0, value
        # For value=3: 0x200a0003, value=8: 0x200a0008, value=17: 0x200a0011
        builder.emit_i_type(Opcode.ADDI, 0, 10, value)

        # ANDI $11, $10, 1 (0x314b0001) - Extract LSB to check odd/even
        builder.emit_i_type(Opcode.ANDI, 10, 11, 1)

        # BEQ $11, $0, even_X (0x11600002) - Branch if even
        # *** CRITICAL: BEQ reads $11 immediately after ANDI writes it! ***
        builder.emit_branch(Opcode.BEQ, 11, 0, f"even_{value}")

        # Odd path: ADD $9, $9, $10 (0x012a4820)
        builder.emit_r_type(Opcode.R_TYPE, 9, 10, 9, 0, Funct.ADD)

        # J join_X - Skip even path
        # For value=3: 0x08000009, value=8: 0x0800000f, value=17: 0x08000015
        builder.emit_jump(Opcode.J, f"join_{value}")

        # Even path
        builder.label(f"even_{value}")
        # ADD $8, $8, $10 (0x010a4020)
        builder.emit_r_type(Opcode.R_TYPE, 8, 10, 8, 0, Funct.ADD)

        builder.label(f"join_{value}")

    # Store results
    for reg in [8, 9]:
        # SW $reg, 0($2) (0xac4x0000 where x=8 or 9)
        builder.emit_i_type(Opcode.SW, 2, reg, 0)
        # ADDI $2, $2, 4 (0x20420004)
        builder.emit_i_type(Opcode.ADDI, 2, 2, 4)

    # Infinite loop to halt
    builder.label("done")
    # J done (0x0800xxxx) - jumps to itself
    builder.emit_jump(Opcode.J, "done")

    program = builder.program()

    async def bench(ctx):
        await load_program(ctx, dut, program)

        # Collect memory writes
        observed = {}
        for cycle in range(100):
            await ctx.tick()
            if ctx.get(dut.dmem_wen_mon):
                addr = ctx.get(dut.dmem_addr_mon)
                data = ctx.get(dut.dmem_wdata_mon) & MASK32
                observed[addr] = data
                print(f"  cycle {cycle:03d}: store addr=0x{addr:04X} data=0x{data:08X}")

        # Check results
        even_sum_addr = RESULT_BASE_ADDR
        odd_sum_addr = RESULT_BASE_ADDR + 4

        expected_even_sum = 8  # only value 8 is even
        expected_odd_sum = 20  # 3 + 17 = 20

        actual_even = observed.get(even_sum_addr)
        actual_odd = observed.get(odd_sum_addr)

        errors = []
        if actual_even != expected_even_sum:
            errors.append(
                f"even_sum mismatch: expected 0x{expected_even_sum:08X}, "
                f"got {'None' if actual_even is None else f'0x{actual_even:08X}'}"
            )
        if actual_odd != expected_odd_sum:
            errors.append(
                f"odd_sum mismatch: expected 0x{expected_odd_sum:08X}, "
                f"got {'None' if actual_odd is None else f'0x{actual_odd:08X}'}"
            )

        if errors:
            raise AssertionError("Branch operand hazard detected:\n  " + "\n  ".join(errors))

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_branch_hazard_test.vcd")


def get_tests():
    return [
        SimulationTest(
            key="cpu-branch-hazard",
            name="CPU Branch Operand Hazard",
            description=(
                "Detects missing forwarding/stall for branch operands. "
                "BEQ should see fresh register values from preceding ANDI instruction."
            ),
            build=build_spec,
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
