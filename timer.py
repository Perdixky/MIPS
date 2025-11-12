from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

class Timer(wiring.Component):
    en: In(1)
    flag: Out(1)

    def __init__(self, clk_freq, timeout):
        self.clk_freq= clk_freq
        self._max_count= int(clk_freq * timeout)

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        counter = Signal(range(self._max_count + 1))

        with m.If(self.en):
            with m.If(counter < self._max_count):
                m.d.sync += counter.eq(counter + 1)
                m.d.comb += self.flag.eq(0)
            with m.Else():
                m.d.comb += self.flag.eq(1)
        with m.Else():
            m.d.sync += counter.eq(0)
            m.d.comb += self.flag.eq(0)

        return m

from amaranth.sim import Simulator

dut = Timer(clk_freq=10, timeout=2)  # 10 Hz clock, 2 seconds timeout
async def bench(ctx):
    ctx.set(dut.en, 0)
    for _ in range(25):
        await ctx.tick()
        assert not ctx.get(dut.flag)

    ctx.set(dut.en, 1)
    for _ in range(19):
        await ctx.tick()
        assert not ctx.get(dut.flag)

    await ctx.tick()
    assert ctx.get(dut.flag)

    ctx.set(dut.en, 0)
    for _ in range(5):
        await ctx.tick()
        assert not ctx.get(dut.flag)
        assert ctx.get(dut.flag) == 0

sim = Simulator(dut)
sim.add_clock(1e-1)
sim.add_testbench(bench)
with sim.write_vcd("timer.vcd"):
    sim.run()
