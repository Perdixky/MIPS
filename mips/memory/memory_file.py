from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory


class MemoryFile(wiring.Component):
    addr: In(32)
    read_data: Out(32)
    write_data: In(32)
    write_enable: In(1)

    def __init__(self, depth=4096):
        self.depth = depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.submodules.mem = mem = Memory(shape=unsigned(32), depth=self.depth, init=[])
        wr_port = mem.write_port(domain="sync")
        rd_port = mem.read_port(domain="sync", transparent_for=[wr_port])

        m.d.comb += [
            wr_port.addr.eq(self.addr),
            wr_port.data.eq(self.write_data),
            wr_port.en.eq(self.write_enable),
            rd_port.addr.eq(self.addr),
            self.read_data.eq(rd_port.data),
        ]

        return m


if __name__ == "__main__":
    from amaranth.sim import Simulator

    dut = MemoryFile(depth=256)

    async def bench(ctx):
        # 测试1: 基本写入和读取
        ctx.set(dut.addr, 0x10)
        ctx.set(dut.write_data, 0xDEADBEEF)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xDEADBEEF, (
            f"Test 1 failed: expected 0xDEADBEEF, got 0x{read_val:08X}"
        )
        print(f"✓ Test 1 passed: Basic write/read at addr 0x10")

        # 测试2: 写使能控制
        ctx.set(dut.addr, 0x20)
        ctx.set(dut.write_data, 0x12345678)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0x12345678, "Test 2a failed: write with enable=1"

        ctx.set(dut.write_data, 0xAAAAAAAA)
        ctx.set(dut.write_enable, 0)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0x12345678, "Test 2b failed: data changed with enable=0"
        print(f"✓ Test 2 passed: Write enable control")

        # 测试3: 多地址写入和读取
        test_data = {
            0x00: 0x00000001,
            0x10: 0x11111111,
            0x20: 0x22222222,
            0x30: 0x33333333,
            0xFF: 0xFFFFFFFF,
        }

        for addr, data in test_data.items():
            ctx.set(dut.addr, addr)
            ctx.set(dut.write_data, data)
            ctx.set(dut.write_enable, 1)
            await ctx.tick()

        ctx.set(dut.write_enable, 0)
        for addr, expected in test_data.items():
            ctx.set(dut.addr, addr)
            await ctx.tick()
            read_val = ctx.get(dut.read_data)
            assert read_val == expected, (
                f"Test 3 failed at addr 0x{addr:02X}: expected 0x{expected:08X}, got 0x{read_val:08X}"
            )
        print(f"✓ Test 3 passed: Multiple address write/read")

        # 测试4: 透明写（写入时立即读取）
        ctx.set(dut.addr, 0x50)
        ctx.set(dut.write_data, 0xCAFEBABE)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xCAFEBABE, "Test 4 failed: transparent write"
        print(f"✓ Test 4 passed: Transparent write")

        # 测试5: 数据持久性
        ctx.set(dut.addr, 0x42)
        ctx.set(dut.write_data, 0xBEEFCAFE)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()

        ctx.set(dut.addr, 0x43)
        ctx.set(dut.write_data, 0x99999999)
        await ctx.tick()

        ctx.set(dut.addr, 0x42)
        ctx.set(dut.write_enable, 0)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xBEEFCAFE, "Test 5 failed: data not persistent"
        print(f"✓ Test 5 passed: Data persistence")

        # 测试6: 边界地址
        ctx.set(dut.addr, 0)
        ctx.set(dut.write_data, 0x00000000)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0x00000000, "Test 6a failed: address 0"

        ctx.set(dut.addr, 255)
        ctx.set(dut.write_data, 0xFFFFFFFF)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xFFFFFFFF, "Test 6b failed: address 255"
        print(f"✓ Test 6 passed: Boundary addresses")

        # 测试7: 覆盖写入
        ctx.set(dut.addr, 0x80)
        ctx.set(dut.write_data, 0x11111111)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()

        ctx.set(dut.write_data, 0x22222222)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0x22222222, "Test 7 failed: overwrite"
        print(f"✓ Test 7 passed: Overwrite data")

        # 测试8: 顺序写入
        ctx.set(dut.write_enable, 1)
        for i in range(16):
            ctx.set(dut.addr, i)
            ctx.set(dut.write_data, i * 0x11111111)
            await ctx.tick()

        ctx.set(dut.write_enable, 0)
        for i in range(16):
            ctx.set(dut.addr, i)
            await ctx.tick()
            read_val = ctx.get(dut.read_data)
            expected = (i * 0x11111111) & 0xFFFFFFFF
            assert read_val == expected, f"Test 8 failed at addr {i}"
        print(f"✓ Test 8 passed: Sequential writes")

        print("\n✓ All tests passed!")

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    with sim.write_vcd("memory.vcd"):
        sim.run()
