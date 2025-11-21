#!/usr/bin/env python3

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from amaranth import Mux
from amaranth import Module
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.sim import Simulator

from mips.core.cpu import CPU, Opcode, Funct
from mips.memory.memory_file import MemoryFile
from program.harming import build_hamming_program

OUTPUT_BASE_ADDR = 0xFFFF0000
PIPELINE_DRAIN_CYCLES = 12
DEFAULT_MAX_CYCLES = 4000
JR_RA_ENCODING = ((Opcode.R_TYPE & 0x3F) << 26) | (31 << 21) | (Funct.JR & 0x3F)
PROJECT_ROOT = Path(__file__).resolve().parent
ANALYSIS_DIR = PROJECT_ROOT / "build" / "analysis"


@dataclass
class MemoryWrite:
    cycle: int
    addr: int
    data: int


class HammingSystem(wiring.Component):
    """CPU + instruction memory hook for running the Hamming test program."""

    imem_init_addr: In(32)
    imem_init_data: In(32)
    imem_init_we: In(1)
    reset: In(1)

    debug_pc: Out(32)
    debug_instr: Out(32)

    def __init__(self, *, imem_depth: int):
        super().__init__()
        self._imem_depth = imem_depth

    def elaborate(self, platform):  # noqa: D401 - interface required by amaranth
        m = Module()
        self.cpu = cpu = CPU()
        m.submodules.cpu = cpu
        m.submodules.imem = imem = MemoryFile(depth=self._imem_depth, sync_read=False)

        # Instruction memory loader muxes: during init we drive addr/data manually.
        word_addr = cpu.imem_addr >> 2
        m.d.comb += [
            cpu.reset.eq(self.reset),
            imem.read_addr.eq(Mux(self.imem_init_we, self.imem_init_addr, word_addr)),
            imem.write_addr.eq(self.imem_init_addr),
            imem.write_data.eq(self.imem_init_data),
            imem.write_enable.eq(self.imem_init_we),
            cpu.imem_rdata.eq(imem.read_data),
            cpu.dmem_rdata.eq(0),
            self.debug_pc.eq(cpu.imem_addr),
            self.debug_instr.eq(imem.read_data),
        ]

        return m


def decode_ascii(value: int) -> Optional[str]:
    value &= 0xFFFFFFFF
    raw = value.to_bytes(4, byteorder="big")
    if all(32 <= b <= 126 for b in raw):
        return raw.decode("ascii")
    return None


def format_word(value: int) -> str:
    text = decode_ascii(value)
    if text is None:
        return f"0x{value & 0xFFFFFFFF:08X}"
    return f"0x{value & 0xFFFFFFFF:08X} ('{text}')"


async def load_program(ctx, dut: HammingSystem, words: List[int]) -> None:
    ctx.set(dut.imem_init_we, 0)
    for idx, word in enumerate(words):
        ctx.set(dut.imem_init_addr, idx)
        ctx.set(dut.imem_init_data, word)
        ctx.set(dut.imem_init_we, 1)
        await ctx.tick()
    ctx.set(dut.imem_init_we, 0)
    await ctx.tick()


def run_hamming(
    max_cycles: int, vcd_path: Optional[str], expected_tests: int
) -> Tuple[List[MemoryWrite], int, List[Tuple[int, int]], List[int]]:
    artifact = build_hamming_program()
    imem_depth = max(256, len(artifact.words) + 8)
    dut = HammingSystem(imem_depth=imem_depth)
    writes: List[MemoryWrite] = []

    async def bench(ctx):
        ctx.set(dut.reset, 1)
        await load_program(ctx, dut, artifact.words)
        for _ in range(3):
            await ctx.tick()
        ctx.set(dut.reset, 0)

        idle_cycles = 0
        cycles_executed = 0
        halted = False
        jr_active = False
        jr_seen = 0
        drain = 0
        retired = 0
        perf_samples: List[Tuple[int, int]] = []
        jr_events: List[int] = []
        for cycle in range(max_cycles):
            await ctx.tick()
            cycles_executed = cycle + 1
            pc = ctx.get(dut.debug_pc)
            if pc == artifact.done_pc:
                idle_cycles += 1
            else:
                idle_cycles = 0

            if ctx.get(dut.cpu.dmem_wen):
                addr = ctx.get(dut.cpu.dmem_write_addr) & 0xFFFFFFFF
                data = ctx.get(dut.cpu.dmem_wdata) & 0xFFFFFFFF
                writes.append(MemoryWrite(cycle=cycle, addr=addr, data=data))

            if ctx.get(dut.cpu.regfile.wr_en):
                dest = ctx.get(dut.cpu.regfile.wr_addr)
                if dest != 0:
                    retired += 1

            perf_samples.append((cycle, retired))

            instr = ctx.get(dut.debug_instr) & 0xFFFFFFFF
            if instr == JR_RA_ENCODING:
                if not jr_active:
                    jr_seen += 1
                    jr_events.append(cycle)
                    drain = PIPELINE_DRAIN_CYCLES
                jr_active = True
            else:
                jr_active = False

            if drain > 0:
                drain -= 1
                if (drain == 0) and (expected_tests > 0) and (jr_seen >= expected_tests):
                    halted = True
                    break

            if idle_cycles >= PIPELINE_DRAIN_CYCLES and expected_tests <= 0:
                halted = True
                break

        if not halted:
            raise RuntimeError(
                f"Program did not finish {expected_tests} JR returns within {max_cycles} cycles"
            )

        bench.cycles = cycles_executed
        bench.samples = perf_samples
        bench.jr_events = jr_events

    bench.cycles = 0
    bench.samples = []
    bench.jr_events = []

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)

    if vcd_path:
        with sim.write_vcd(vcd_path):
            sim.run()
    else:
        sim.run()

    return writes, bench.cycles, bench.samples, bench.jr_events


def group_test_outputs(events: List[MemoryWrite]):
    grouped = []
    current = {}
    for evt in events:
        offset = evt.addr - OUTPUT_BASE_ADDR
        if offset == 4:
            if current:
                grouped.append(current)
                current = {}
            current["status"] = evt
        elif offset == 8:
            current["code"] = evt
            grouped.append(current)
            current = {}
    if current:
        grouped.append(current)
    return grouped


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Hamming-code assembly on the MIPS CPU")
    parser.add_argument("--max-cycles", type=int, default=DEFAULT_MAX_CYCLES, help="Maximum cycles to simulate")
    parser.add_argument("--vcd", type=str, default=None, help="Optional path for waveform dump")
    parser.add_argument(
        "--tests",
        type=int,
        default=3,
        help="Number of JR-returning testcases to wait for (<=0 disables the limit).",
    )
    args = parser.parse_args(argv)

    try:
        writes, cycles, samples, jr_events = run_hamming(args.max_cycles, args.vcd, args.tests)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    if args.tests > 0:
        print(f"Observed {args.tests} JR returns after {cycles} cycles.")
    else:
        print(f"Reached steady JR loop after {cycles} cycles.")

    if not writes:
        print("No memory-mapped output was produced.")
        return 1

    print("\nCaptured writes to output MMIO:")
    for evt in writes:
        print(
            f"  cycle={evt.cycle:04d} addr=0x{evt.addr:08X} data={format_word(evt.data)}"
        )

    grouped = group_test_outputs(writes)
    print("\nDecoded test results:")
    for idx, result in enumerate(grouped, start=1):
        status = result.get("status")
        code = result.get("code")
        print(f"Test {idx}:")
        if status:
            print(
                f"  status @cycle {status.cycle:04d}: {format_word(status.data)}"
            )
        else:
            print("  status : <missing>")
        if code:
            print(
                f"  code   @cycle {code.cycle:04d}: 0x{code.data & 0xFFFFFFFF:08X}"
            )
        else:
            print("  code   : <missing>")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_path = ANALYSIS_DIR / "pipeline.svg"
    perf_path = ANALYSIS_DIR / "performance.svg"
    generate_pipeline_svg(pipeline_path)
    generate_performance_svg(perf_path, samples, writes, jr_events)

    print(f"\n流水线结构图已生成: {pipeline_path}")
    print(f"性能分析图已生成: {perf_path}")

    return 0


def svg_header(width: int, height: int) -> List[str]:
    return [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "  <style>text{font-family:Consolas,Monaco,monospace;font-size:14px;}" "</style>",
    ]


def generate_pipeline_svg(path: Path) -> None:
    width, height = 900, 220
    stages = [
        ("IF", "取指 (Instruction Fetch)"),
        ("ID", "译码 (Instruction Decode)"),
        ("EX", "执行 (Execute)"),
        ("MEM", "访存 (Memory)"),
        ("WB", "写回 (Write Back)"),
    ]
    margin = 60
    gap = 20
    box_width = (width - 2 * margin - gap * (len(stages) - 1)) / len(stages)
    box_height = 80
    y = (height - box_height) / 2

    parts = svg_header(width, height)
    for idx, (name, desc) in enumerate(stages):
        x = margin + idx * (box_width + gap)
        parts.append(
            f"  <rect x='{x:.1f}' y='{y:.1f}' width='{box_width:.1f}' height='{box_height}' "
            "rx='12' ry='12' fill='#E0F7FA' stroke='#00838F' stroke-width='2'/>"
        )
        parts.append(
            f"  <text x='{x + box_width / 2:.1f}' y='{y + 30:.1f}' text-anchor='middle' fill='#004D40' font-size='22'>{name}</text>"
        )
        parts.append(
            f"  <text x='{x + box_width / 2:.1f}' y='{y + 60:.1f}' text-anchor='middle' fill='#006064'>{desc}</text>"
        )
        if idx < len(stages) - 1:
            x2 = x + box_width + gap / 2
            parts.append(
                f"  <line x1='{x + box_width:.1f}' y1='{y + box_height / 2:.1f}' x2='{x2:.1f}' y2='{y + box_height / 2:.1f}' stroke='#006064' stroke-width='3' marker-end='url(#arrow)'/>"
            )

    # Arrow marker
    parts.insert(2, "  <defs><marker id='arrow' markerWidth='10' markerHeight='10' refX='6' refY='3' orient='auto'><path d='M0,0 L0,6 L9,3 z' fill='#006064'/></marker></defs>")
    parts.append("</svg>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def generate_performance_svg(
    path: Path, samples: List[Tuple[int, int]], writes: List[MemoryWrite], jr_events: List[int]
) -> None:
    if not samples:
        return

    width, height = 960, 360
    margin = 60
    max_cycle = max(c for c, _ in samples) or 1
    max_retired = max(r for _, r in samples) or 1

    def sx(cycle: int) -> float:
        return margin + (cycle / max_cycle) * (width - 2 * margin)

    def sy(value: int) -> float:
        return height - margin - (value / max_retired) * (height - 2 * margin)

    parts = svg_header(width, height)
    parts.append(
        f"  <line x1='{margin}' y1='{height - margin}' x2='{width - margin}' y2='{height - margin}' stroke='black' stroke-width='2'/>"
    )
    parts.append(
        f"  <line x1='{margin}' y1='{margin}' x2='{margin}' y2='{height - margin}' stroke='black' stroke-width='2'/>"
    )
    parts.append(
        f"  <text x='{width - margin}' y='{height - margin + 30}' text-anchor='end'>Cycles (0~{max_cycle})</text>"
    )
    parts.append(
        f"  <text x='{margin - 35}' y='{margin - 10}' text-anchor='start' transform='rotate(-90 {margin - 35},{margin - 10})'>Retired Instructions (0~{max_retired})</text>"
    )

    points = " ".join(f"{sx(c):.2f},{sy(r):.2f}" for c, r in samples)
    parts.append(
        f"  <polyline fill='none' stroke='#2E7D32' stroke-width='2.5' points='{points}'/>"
    )

    for write in writes:
        x = sx(write.cycle)
        color = "#FF6F00" if (write.addr - OUTPUT_BASE_ADDR) == 4 else "#0D47A1"
        parts.append(
            f"  <line x1='{x:.2f}' y1='{margin}' x2='{x:.2f}' y2='{height - margin}' stroke='{color}' stroke-width='1.5' stroke-dasharray='4 4'/>"
        )
        parts.append(
            f"  <text x='{x + 3:.2f}' y='{margin + 15}' fill='{color}' font-size='12'>MMIO@{write.cycle}</text>"
        )

    for idx, cycle in enumerate(jr_events, start=1):
        x = sx(cycle)
        y = sy(max_retired * 0.95)
        parts.append(
            f"  <circle cx='{x:.2f}' cy='{y:.2f}' r='5' fill='#C62828'/>")
        parts.append(
            f"  <text x='{x + 8:.2f}' y='{y - 5:.2f}' fill='#C62828' font-size='12'>JR {idx}@{cycle}</text>"
        )

    parts.append("</svg>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


if __name__ == "__main__":
    sys.exit(main())
