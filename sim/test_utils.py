from __future__ import annotations

import contextlib
import io
import os
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, List, Optional

from amaranth import Elaboratable
from amaranth.sim import Simulator

BenchCoroutine = Callable[..., Awaitable[None]]


@dataclass
class SimulationSpec:
    """Container describing how to build and run a single simulation bench."""

    dut: Elaboratable
    bench: BenchCoroutine
    clock_period: float = 1e-6
    vcd_path: Optional[str] = None


@dataclass
class SimulationTest:
    """Metadata + factory for a simulation-driven regression test."""

    key: str
    name: str
    description: str
    build: Callable[[], SimulationSpec]
    tags: tuple[str, ...] = ()

    def run(self, *, capture: bool = True) -> "TestResult":
        """Execute the simulation and return a structured result."""
        log_buffer: Optional[io.StringIO] = io.StringIO() if capture else None
        stdout_cm = (
            contextlib.redirect_stdout(log_buffer)
            if log_buffer is not None
            else contextlib.nullcontext()
        )

        start = time.perf_counter()
        error: Optional[BaseException] = None

        try:
            spec = self.build()
            simulator = Simulator(spec.dut)
            simulator.add_clock(spec.clock_period)
            simulator.add_testbench(spec.bench)

            with stdout_cm:
                vcd_path = (
                    spec.vcd_path
                    if spec.vcd_path and os.environ.get("MIPS_SIM_SAVE_VCD", "")
                    else None
                )
                if vcd_path:
                    with simulator.write_vcd(vcd_path):
                        simulator.run()
                else:
                    simulator.run()
        except BaseException as exc:  # noqa: BLE001 - need to capture everything
            error = exc

        duration = time.perf_counter() - start
        output = log_buffer.getvalue() if log_buffer is not None else ""
        return TestResult(
            test=self,
            passed=error is None,
            output=output,
            duration=duration,
            error=error,
        )


@dataclass
class TestResult:
    test: SimulationTest
    passed: bool
    output: str
    duration: float
    error: Optional[BaseException] = None

    def short_status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def run_tests_cli(tests: Iterable[SimulationTest]) -> int:
    """Fallback CLI runner for individual test modules."""
    tests = list(tests)
    if not tests:
        print("No tests registered.")
        return 0

    print("=" * 72)
    print("MIPS Simulation Tests")
    print("=" * 72)

    exit_code = 0
    for idx, test in enumerate(tests, start=1):
        print(f"\n[{idx}/{len(tests)}] {test.name}")
        print(textwrap.fill(test.description, width=70))
        result = test.run()

        print(f"  Result : {result.short_status()} ({result.duration:.2f}s)")
        if result.output.strip():
            print("  Output :")
            for line in result.output.strip().splitlines():
                print(f"    {line}")
        if not result.passed:
            exit_code = 1
            if result.error:
                print("  Error  :")
                traceback.print_exception(result.error, file=sys.stdout)

    return exit_code


def ansi(text: str, code: str) -> str:
    """Basic ANSI color helper with Windows fallback."""
    if os.name == "nt":
        # Enable ANSI processing on Windows terminals that need it.
        os.system("")  # type: ignore[call-arg]
    return f"\033[{code}m{text}\033[0m"
