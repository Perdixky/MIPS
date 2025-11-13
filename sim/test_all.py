from __future__ import annotations

import itertools
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sim.benches.cpu_forwarding_test import get_tests as get_forwarding_tests
from sim.benches.cpu_hazard_detection_test import get_tests as get_hazard_detection_tests
from sim.benches.cpu_test import get_tests as get_cpu_tests
from sim.benches.register_file_test import get_tests as get_regfile_tests
from sim.test_utils import SimulationTest, TestResult

console = Console()
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
STATUS_STYLE = {
    "pending": ("○", "grey50", "待运行"),
    "running": ("⟳", "cyan", "运行中"),
    "passed": ("✔", "green", "通过"),
    "failed": ("✖", "red", "失败"),
}
BANNER = Text(
    "\n MIPS Simulation Regression Suite ",
    style="bold white on dark_green",
    justify="center",
)


def collect_tests() -> List[SimulationTest]:
    suites = [
        get_cpu_tests,
        get_forwarding_tests,
        get_hazard_detection_tests,
        get_regfile_tests,
    ]
    tests: List[SimulationTest] = []
    seen_keys: set[str] = set()
    for factory in suites:
        for test in factory():
            if test.key in seen_keys:
                raise ValueError(f"Duplicated test key detected: {test.key}")
            seen_keys.add(test.key)
            tests.append(test)
    return tests


def build_table(
    tests: List[SimulationTest],
    state: Dict[str, Dict[str, Optional[object]]],
    highlight: Optional[str],
) -> Table:
    table = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="bold grey70",
    )
    table.add_column("#", width=3)
    table.add_column("状态", width=6)
    table.add_column("测试名称", justify="left")
    table.add_column("说明", justify="left")
    table.add_column("耗时", width=8, justify="right")
    table.add_column("标签", justify="left")

    for idx, test in enumerate(tests, start=1):
        data = state[test.key]
        status = data["status"]
        icon, color, label = STATUS_STYLE[status]
        spinner = data.get("spinner")
        icon_to_show = spinner if (status == "running" and spinner) else icon

        result: TestResult | None = data.get("result")  # type: ignore[assignment]
        duration = f"{result.duration:0.2f}s" if result else "-"
        tags = ", ".join(test.tags)
        err_line = ""
        if result and not result.passed:
            if result.error:
                err_line = str(result.error).splitlines()[0]
            elif result.output.strip():
                err_line = result.output.strip().splitlines()[-1]

        row_style = "bold magenta" if highlight == test.key else None
        table.add_row(
            str(idx),
            Text(icon_to_show, style=color),
            test.name,
            Text(err_line or STATUS_STYLE[status][2], style=color if err_line else "white"),
            duration,
            Text(tags, style="cyan"),
            style=row_style,
        )
    return table


def render_dashboard(
    tests: List[SimulationTest],
    state: Dict[str, Dict[str, Optional[object]]],
    *,
    message: str,
    highlight: Optional[str],
) -> Layout:
    total = len(tests)
    counts = {
        "passed": sum(1 for data in state.values() if data["status"] == "passed"),
        "failed": sum(1 for data in state.values() if data["status"] == "failed"),
        "pending": sum(1 for data in state.values() if data["status"] == "pending"),
    }
    summary = Text(
        f"总计 {total} | 通过 {counts['passed']} | 失败 {counts['failed']} | 待运行 {counts['pending']}",
        style="bold",
        justify="center",
    )

    layout = Layout()
    layout.split_column(
        Layout(Panel(Align.center(BANNER), border_style="dark_green"), size=5),
        Layout(Panel(summary, border_style="grey46"), size=3),
        Layout(Panel(build_table(tests, state, highlight), border_style="grey50"), ratio=1),
        Layout(
            Panel(
                Text(
                    message
                    + "\n命令: 输入编号运行 | a=全部 | l编号查看日志 | r重置 | q退出",
                    style="grey80",
                ),
                border_style="grey35",
            ),
            size=5,
        ),
    )
    return layout


def run_with_spinner(
    test: SimulationTest,
    tests: List[SimulationTest],
    state: Dict[str, Dict[str, Optional[object]]],
    live: Live,
) -> TestResult:
    state[test.key]["status"] = "running"
    state[test.key]["spinner"] = SPINNER_FRAMES[0]
    start_time = time.perf_counter()
    live.update(
        render_dashboard(
            tests,
            state,
            message=f"正在运行 {test.name} ...",
            highlight=test.key,
        )
    )

    spinner_cycle = itertools.cycle(SPINNER_FRAMES)
    result: Optional[TestResult] = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(test.run)
        while True:
            try:
                result = future.result(timeout=0.1)
                break
            except TimeoutError:
                state[test.key]["spinner"] = next(spinner_cycle)
                live.update(
                    render_dashboard(
                        tests,
                        state,
                        message=f"正在运行 {test.name} ...",
                        highlight=test.key,
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                result = TestResult(
                    test=test,
                    passed=False,
                    output="",
                    duration=time.perf_counter() - start_time,
                    error=exc,
                )
                break

    if result is None:
        result = TestResult(
            test=test,
            passed=False,
            output="",
            duration=time.perf_counter() - start_time,
            error=RuntimeError("未知错误：测试未产生结果"),
        )

    state[test.key]["result"] = result
    state[test.key]["status"] = "passed" if result.passed else "failed"
    state[test.key]["spinner"] = ""

    summary = f"{'✔' if result.passed else '✖'} {test.name} 用时 {result.duration:.2f}s"
    if not result.passed and result.error:
        summary += f" | 错误: {result.error}"

    live.update(
        render_dashboard(tests, state, message=summary, highlight=test.key)
    )
    time.sleep(0.4)
    return result


def show_log(
    test: SimulationTest,
    state: Dict[str, Dict[str, Optional[object]]],
    live: Live,
) -> None:
    result: TestResult | None = state[test.key].get("result")  # type: ignore[assignment]
    live.stop()
    console.rule(f"日志 - {test.name}")
    if not result:
        console.print("尚未运行该测试。")
    else:
        console.print(result.output or "<无输出>")
        if result.error:
            console.print("\n异常堆栈：", style="bold red")
            import traceback

            traceback.print_exception(result.error, file=sys.stdout)
    console.input("\n按回车返回菜单...")
    live.start()


def reset_state(state: Dict[str, Dict[str, Optional[object]]]) -> None:
    for data in state.values():
        data["status"] = "pending"
        data["result"] = None
        data["spinner"] = ""


def prompt_command(live: Live) -> str:
    pause_ctx = getattr(live, "pause", None)
    if pause_ctx is not None:
        try:
            with pause_ctx():
                return console.input("[bold cyan]请输入指令 › [/]").strip()
        finally:
            console.line()

    # Fallback for older rich versions without Live.pause()
    live.stop()
    try:
        return console.input("[bold cyan]请输入指令 › [/]").strip()
    finally:
        console.line()
        live.start()


def main() -> int:
    try:
        tests = collect_tests()
    except ValueError as exc:
        console.print(exc, style="red")
        return 1

    state: Dict[str, Dict[str, Optional[object]]] = {
        test.key: {"status": "pending", "result": None, "spinner": ""} for test in tests
    }

    message = "输入命令开始运行测试。"
    highlight: Optional[str] = None

    with Live(
        render_dashboard(tests, state, message=message, highlight=highlight),
        console=console,
        refresh_per_second=10,
        screen=False,
    ) as live:
        while True:
            try:
                cmd = prompt_command(live)
            except (EOFError, KeyboardInterrupt):
                message = "已中断，退出。"
                live.update(
                    render_dashboard(tests, state, message=message, highlight=None)
                )
                break

            if not cmd:
                message = "输入不能为空。"
                live.update(render_dashboard(tests, state, message=message, highlight=highlight))
                continue

            lower_cmd = cmd.lower()
            if lower_cmd in {"q", "quit"}:
                message = "再见！"
                live.update(render_dashboard(tests, state, message=message, highlight=None))
                break
            if lower_cmd in {"a", "all"}:
                for test in tests:
                    highlight = test.key
                    run_with_spinner(test, tests, state, live)
                message = "全部测试完成。"
                highlight = None
                live.update(render_dashboard(tests, state, message=message, highlight=highlight))
                continue
            if lower_cmd in {"r", "reset"}:
                reset_state(state)
                message = "状态已重置。"
                highlight = None
                live.update(render_dashboard(tests, state, message=message, highlight=highlight))
                continue
            if lower_cmd.startswith("l") and lower_cmd[1:].isdigit():
                idx = int(lower_cmd[1:]) - 1
                if 0 <= idx < len(tests):
                    show_log(tests[idx], state, live)
                    message = f"已查看 {tests[idx].name} 日志。"
                else:
                    message = "无效的编号。"
                live.update(render_dashboard(tests, state, message=message, highlight=highlight))
                continue
            if cmd.isdigit():
                idx = int(cmd) - 1
                if 0 <= idx < len(tests):
                    highlight = tests[idx].key
                    run_with_spinner(tests[idx], tests, state, live)
                    message = f"{tests[idx].name} 已完成。"
                    highlight = None
                else:
                    message = "无效的编号。"
                live.update(render_dashboard(tests, state, message=message, highlight=highlight))
                continue

            message = "未知命令，请重试。"
            live.update(render_dashboard(tests, state, message=message, highlight=highlight))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
