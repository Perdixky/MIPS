from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

class RandomSelector(wiring.Component):
    start: In(1)
    done: Out(1)
    selection: Out(4)  # Assuming we want to select from 16 options

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        counter = Signal(4)
        selecting = Signal()

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.start):
                    m.next = "SELECTING"
                    m.d.sync += selecting.eq(1)
                    m.d.sync += counter.eq(0)

            with m.State("SELECTING"):
                with m.If(counter < 15):
                    m.d.sync += counter.eq(counter + 1)
                with m.Else():
                    m.d.sync += selecting.eq(0)
                    m.next = "DONE"

            with m.State("DONE"):
                m.d.comb += self.done.eq(1)
                m.d.comb += self.selection.eq(counter)
                m.next = "IDLE"

        return m
