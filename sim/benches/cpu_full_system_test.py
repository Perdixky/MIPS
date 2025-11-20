from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
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

WORD_BYTES = 4
MASK32 = (1 << 32) - 1
DATA_BASE_ADDR = 0x80
RESULT_BASE_ADDR = 0x180
MAX_CYCLES = 600


def encode_r_type(opcode, rs, rt, rd, shamt, funct):
    return (opcode << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct


def encode_i_type(opcode, rs, rt, imm):
    imm = imm & 0xFFFF
    return (opcode << 26) | (rs << 21) | (rt << 16) | imm


def encode_j_type(opcode, addr):
    addr &= 0x3FFFFFF
    return (opcode << 26) | addr


def nop():
    return 0


@dataclass
class ProgramArtifact:
    words: List[int]
    expected_writes: Dict[int, int]
    done_pc: int


class ProgramBuilder:
    def __init__(self):
        self.instructions: List[int] = []
        self.labels: Dict[str, int] = {}
        self.patches: List[Tuple[str, ...]] = []
        self._finalized = False

    def _assert_mutable(self) -> None:
        if self._finalized:
            raise RuntimeError("Program already finalized")

    def label(self, name: str) -> None:
        self._assert_mutable()
        if name in self.labels:
            raise ValueError(f"Label '{name}' already defined")
        self.labels[name] = len(self.instructions)

    def _emit(self, word: int) -> None:
        self.instructions.append(word & MASK32)

    def emit_r_type(self, opcode, rs, rt, rd, shamt, funct) -> None:
        self._assert_mutable()
        self._emit(encode_r_type(opcode, rs, rt, rd, shamt, funct))

    def emit_i_type(self, opcode, rs, rt, imm) -> None:
        self._assert_mutable()
        self._emit(encode_i_type(opcode, rs, rt, imm))

    def emit_branch(self, opcode, rs, rt, label: str) -> None:
        self._assert_mutable()
        idx = len(self.instructions)
        self.instructions.append(nop())
        self.patches.append(("branch", idx, opcode, rs, rt, label))

    def emit_jump(self, opcode, label: str) -> None:
        self._assert_mutable()
        idx = len(self.instructions)
        self.instructions.append(nop())
        self.patches.append(("jump", idx, opcode, label))

    def finalize(self) -> None:
        if self._finalized:
            return
        for patch in self.patches:
            kind = patch[0]
            if kind == "branch":
                _, idx, opcode, rs, rt, label = patch
                if label not in self.labels:
                    raise ValueError(f"Undefined label '{label}'")
                target = self.labels[label]
                offset = target - (idx + 1)
                self.instructions[idx] = encode_i_type(opcode, rs, rt, offset)
            else:
                _, idx, opcode, label = patch
                if label not in self.labels:
                    raise ValueError(f"Undefined label '{label}'")
                target = self.labels[label]
                self.instructions[idx] = encode_j_type(opcode, target)
        self._finalized = True

    def program(self) -> List[int]:
        self.finalize()
        return list(self.instructions)

    def address_of(self, label: str) -> int:
        if label not in self.labels:
            raise ValueError(f"Undefined label '{label}'")
        return self.labels[label]


def build_integration_program() -> ProgramArtifact:
    builder = ProgramBuilder()
    data_values = [3, 17, 8, 29, 12, 5]
    threshold = 20
    length = len(data_values)

    builder.emit_i_type(Opcode.ADDI, 0, 1, DATA_BASE_ADDR)
    builder.emit_i_type(Opcode.ADDI, 0, 2, RESULT_BASE_ADDR)
    builder.emit_i_type(Opcode.ADDI, 0, 3, length)
    builder.emit_i_type(Opcode.ADDI, 0, 4, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 5, -1)
    builder.emit_i_type(Opcode.ADDI, 0, 6, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 7, threshold)
    builder.emit_i_type(Opcode.ADDI, 0, 8, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 9, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 12, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 13, 0)
    builder.emit_i_type(Opcode.ADDI, 0, 14, 0)

    for value in data_values:
        builder.emit_i_type(Opcode.ADDI, 0, 10, value)
        builder.emit_i_type(Opcode.SW, 1, 10, 0)
        builder.emit_i_type(Opcode.ADDI, 1, 1, WORD_BYTES)

    builder.emit_i_type(Opcode.ADDI, 0, 1, DATA_BASE_ADDR)

    builder.label("loop_start")
    builder.emit_i_type(Opcode.LW, 1, 10, 0)
    builder.emit_r_type(Opcode.R_TYPE, 4, 10, 4, 0, Funct.ADD)
    builder.emit_r_type(Opcode.R_TYPE, 5, 10, 5, 0, Funct.AND)
    builder.emit_r_type(Opcode.R_TYPE, 6, 10, 6, 0, Funct.OR)
    builder.emit_i_type(Opcode.ANDI, 10, 11, 1)
    builder.emit_branch(Opcode.BEQ, 11, 0, "even_path")
    builder.emit_r_type(Opcode.R_TYPE, 9, 10, 9, 0, Funct.ADD)
    builder.emit_jump(Opcode.J, "parity_join")
    builder.label("even_path")
    builder.emit_r_type(Opcode.R_TYPE, 8, 10, 8, 0, Funct.ADD)
    builder.label("parity_join")
    builder.emit_r_type(Opcode.R_TYPE, 10, 7, 17, 0, Funct.SLT)
    builder.emit_branch(Opcode.BNE, 17, 0, "below_threshold")
    builder.emit_r_type(Opcode.R_TYPE, 14, 10, 14, 0, Funct.ADD)
    builder.emit_jump(Opcode.J, "threshold_join")
    builder.label("below_threshold")
    builder.emit_r_type(Opcode.R_TYPE, 13, 10, 13, 0, Funct.ADD)
    builder.label("threshold_join")
    builder.emit_i_type(Opcode.ADDI, 12, 12, 1)
    builder.emit_i_type(Opcode.ADDI, 1, 1, WORD_BYTES)
    builder.emit_branch(Opcode.BNE, 12, 3, "loop_start")

    builder.emit_r_type(Opcode.R_TYPE, 0, 4, 16, 1, Funct.SLL)
    builder.emit_r_type(Opcode.R_TYPE, 0, 16, 17, 2, Funct.SRL)
    builder.emit_r_type(Opcode.R_TYPE, 14, 13, 18, 0, Funct.SUB)
    builder.emit_i_type(Opcode.SLTI, 4, 19, 80)
    builder.emit_i_type(Opcode.SLTI, 9, 20, 60)
    builder.emit_i_type(Opcode.ORI, 0, 21, 0x1234)
    builder.emit_r_type(Opcode.R_TYPE, 21, 6, 21, 0, Funct.OR)
    builder.emit_i_type(Opcode.ADDI, 0, 11, RESULT_BASE_ADDR)

    result_regs = [4, 5, 6, 8, 9, 13, 14, 16, 17, 18, 19, 20, 21, 12]
    for reg in result_regs:
        builder.emit_i_type(Opcode.SW, 11, reg, 0)
        builder.emit_i_type(Opcode.ADDI, 11, 11, WORD_BYTES)

    builder.label("done")
    builder.emit_jump(Opcode.J, "done")

    words = builder.program()
    done_pc = builder.address_of("done") * WORD_BYTES

    sum_total = sum(data_values) & MASK32
    and_accum = MASK32
    or_accum = 0
    for value in data_values:
        and_accum &= value
        or_accum |= value
    even_sum = sum(value for value in data_values if (value & 1) == 0) & MASK32
    odd_sum = sum(value for value in data_values if (value & 1) == 1) & MASK32
    below_threshold = sum(value for value in data_values if value < threshold) & MASK32
    above_threshold = sum(value for value in data_values if value >= threshold) & MASK32
    shift_left = (sum_total << 1) & MASK32
    shift_back = (shift_left >> 2) & MASK32
    diff_high_low = (above_threshold - below_threshold) & MASK32
    slti_sum_flag = 1 if sum_total < 80 else 0
    slti_odd_flag = 1 if odd_sum < 60 else 0
    ori_constant = (0x1234 | or_accum) & MASK32
    final_counter = length & MASK32

    expected: Dict[int, int] = {}
    addr = DATA_BASE_ADDR
    for value in data_values:
        expected[addr] = value & MASK32
        addr += WORD_BYTES

    result_values = [
        sum_total,
        and_accum,
        or_accum,
        even_sum,
        odd_sum,
        below_threshold,
        above_threshold,
        shift_left,
        shift_back,
        diff_high_low,
        slti_sum_flag,
        slti_odd_flag,
        ori_constant,
        final_counter,
    ]
    addr = RESULT_BASE_ADDR
    for value in result_values:
        expected[addr] = value & MASK32
        addr += WORD_BYTES

    return ProgramArtifact(words=words, expected_writes=expected, done_pc=done_pc)


class CPUFullSystemBench(wiring.Component):
    imem_init_addr: In(32)
    imem_init_data: In(32)
    imem_init_we: In(1)

    reset: In(1)

    debug_pc: Out(32)
    debug_instr: Out(32)
    dmem_addr_mon: Out(32)
    dmem_wdata_mon: Out(32)
    dmem_wen_mon: Out(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.submodules.cpu = cpu = CPU()
        m.submodules.imem = imem = MemoryFile(depth=512, sync_read=False)  # 指令内存：组合读
        m.submodules.dmem = dmem = MemoryFile(depth=512, sync_read=True)   # 数据内存：同步读

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
            self.debug_instr.eq(imem.read_data),
            self.dmem_addr_mon.eq(cpu.dmem_write_addr),
            self.dmem_wdata_mon.eq(cpu.dmem_wdata),
            self.dmem_wen_mon.eq(cpu.dmem_wen),
        ]
        return m


async def load_program(ctx, dut, program: List[int]) -> None:
    for i, instr in enumerate(program):
        ctx.set(dut.imem_init_addr, i * WORD_BYTES)
        ctx.set(dut.imem_init_data, instr)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    ctx.set(dut.reset, 1)
    await ctx.tick()
    await ctx.tick()
    ctx.set(dut.reset, 0)


def build_full_system_spec() -> SimulationSpec:
    dut = CPUFullSystemBench()
    artifact = build_integration_program()

    async def bench(ctx):
        print("加载集成测试程序...")
        await load_program(ctx, dut, artifact.words)

        expected_writes = artifact.expected_writes
        observed: Dict[int, int] = {}
        store_trace: List[Tuple[int, int, int]] = []
        done_pc = artifact.done_pc

        for cycle in range(MAX_CYCLES):
            await ctx.tick()
            pc = ctx.get(dut.debug_pc)
            if cycle % 20 == 0:
                print(
                    f"[cycle {cycle:03d}] PC=0x{pc:04X} stores={len(observed)}/{len(expected_writes)}"
                )
            if ctx.get(dut.dmem_wen_mon):
                addr = ctx.get(dut.dmem_addr_mon)
                data = ctx.get(dut.dmem_wdata_mon) & MASK32
                observed[addr] = data
                store_trace.append((cycle, addr, data))
            if pc == done_pc and len(observed) >= len(expected_writes):
                break
        else:
            # 测试超时，输出详细诊断信息
            print("\n" + "="*60)
            print("测试失败诊断信息")
            print("="*60)

            print(f"\n实际执行的stores ({len(store_trace)}个):")
            print("  Cycle  地址      数据")
            for cycle, addr, data in store_trace:
                print(f"  {cycle:03d}    0x{addr:04X}  0x{data:08X}")

            missing_addrs = sorted(set(expected_writes.keys()) - set(observed.keys()))
            if missing_addrs:
                print(f"\n缺失的stores ({len(missing_addrs)}个):")
                data_missing = [a for a in missing_addrs if a < 0x180]
                result_missing = [a for a in missing_addrs if a >= 0x180]

                if data_missing:
                    print(f"  数据区 (0x80-0x94): {len(data_missing)}个")
                    for addr in data_missing:
                        print(f"    0x{addr:04X}: 应该是 0x{expected_writes[addr]:08X}")

                if result_missing:
                    print(f"  结果区 (0x180-0x1B4): {len(result_missing)}个")
                    for addr in result_missing:
                        print(f"    0x{addr:04X}: 应该是 0x{expected_writes[addr]:08X}")

            raise AssertionError(
                f"Program did not reach halt PC 0x{done_pc:04X} within {MAX_CYCLES} cycles "
                f"(saw {len(observed)}/{len(expected_writes)} stores)"
            )

        mismatches = []
        for addr, expected in expected_writes.items():
            actual = observed.get(addr)
            if actual != expected:
                actual_str = "None" if actual is None else f"0x{actual:08X}"
                mismatches.append(
                    f"addr 0x{addr:04X}: expected 0x{expected:08X}, observed {actual_str}"
                )
        if mismatches:
            print("Store trace (cycle, addr, data):")
            for entry in store_trace:
                print(f"  {entry[0]:03d} 0x{entry[1]:04X} 0x{entry[2]:08X}")
            raise AssertionError("Memory state mismatches detected:\n" + "\n".join(mismatches))

        unexpected = sorted(set(observed) - set(expected_writes))
        if unexpected:
            raise AssertionError(
                "Unexpected store addresses observed: "
                + ", ".join(f"0x{addr:04X}" for addr in unexpected)
            )

        print(f"✓ Captured all {len(expected_writes)} architecturally visible stores.")

    return SimulationSpec(dut=dut, bench=bench, vcd_path="cpu_full_system.vcd")


def get_tests() -> List[SimulationTest]:
    return [
        SimulationTest(
            key="cpu-integration",
            name="CPU Full-System Integration",
            description="综合算术/访存/跳转/冒险的端到端集成验证，并断言每一次数据存储。",
            build=build_full_system_spec,
            tags=("cpu", "integration", "system"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
