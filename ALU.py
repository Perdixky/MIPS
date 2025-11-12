from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class ALU(wiring.Component):
    a: In(signed(32))
    b: In(signed(32))
    op: In(4)  # 0001: add, 0010: sub, 0010: and, 0011: or
    result: Out(signed(32))
    zero: Out(1)
    negative: Out(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        result = Signal(signed(33))
        with m.Switch(self.op):
            with m.Case(0b0000):  # Add
                m.d.comb += result.eq(self.a + self.b)
            with m.Case(0b0001):  # Subtract
                m.d.comb += result.eq(self.a - self.b)
            with m.Case(0b0010):  # AND
                m.d.comb += result.eq(self.a & self.b)
            with m.Case(0b0011):  # OR
                m.d.comb += result.eq(self.a | self.b)

        # 赋值给输出（隐式截断到32位）
        m.d.comb += self.result.eq(result)

        # 标志位（统一计算，避免多驱动）
        m.d.comb += self.zero.eq(self.result == 0)
        m.d.comb += self.negative.eq(self.result < 0)

        return m


from amaranth.sim import Simulator
import random


def to_signed_32(value):
    """将 Python 整数转换为 32 位有符号整数"""
    value = value & 0xFFFFFFFF  # 先截断到 32 位
    if value >= 2**31:  # 如果最高位是 1
        value -= 2**32  # 转换为负数
    return value


dut = ALU()


async def bench(ctx):
    ctx.set(dut.op, 0b0000)  # Add
    for _ in range(10000):
        a = random.randint(-(2**31), 2**31 - 1)
        b = random.randint(-(2**31), 2**31 - 1)
        ctx.set(dut.a, a)
        ctx.set(dut.b, b)
        assert ctx.get(dut.result) == to_signed_32(a + b)

    ctx.set(dut.op, 0b0001)  # Subtract
    for _ in range(10000):
        a = random.randint(-(2**31), 2**31 - 1)
        b = random.randint(-(2**31), 2**31 - 1)
        ctx.set(dut.a, a)
        ctx.set(dut.b, b)
        assert ctx.get(dut.result) == to_signed_32(a - b)

    ctx.set(dut.op, 0b0010)  # AND
    for _ in range(10000):
        a = random.randint(-(2**31), 2**31 - 1)
        b = random.randint(-(2**31), 2**31 - 1)
        ctx.set(dut.a, a)
        ctx.set(dut.b, b)
        assert ctx.get(dut.result) == to_signed_32(a & b)

    ctx.set(dut.op, 0b0011)  # OR
    for _ in range(10000):
        a = random.randint(-(2**31), 2**31 - 1)
        b = random.randint(-(2**31), 2**31 - 1)
        ctx.set(dut.a, a)
        ctx.set(dut.b, b)
        assert ctx.get(dut.result) == to_signed_32(a | b)


sim = Simulator(dut)
sim.add_testbench(bench)
with sim.write_vcd("ALU.vcd"):
    sim.run()
    print("ALU OK!")
