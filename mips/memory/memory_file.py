from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory


class MemoryFile(wiring.Component):
    read_addr: In(32)
    write_addr: In(32)
    read_data: Out(32)
    write_data: In(32)
    write_enable: In(1)

    def __init__(self, depth=4096, sync_read=True):
        self.depth = depth
        self.sync_read = sync_read

        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.submodules.mem = mem = Memory(shape=unsigned(32), depth=self.depth, init=[])

        # 写端口总是同步的
        wr_port = mem.write_port(domain="sync")

        # 读端口可以是同步或组合，取决于sync_read参数
        # 同步读：读地址可以在EX阶段发出，MEM阶段得到数据，缩短关键路径
        # 组合读：适用于指令内存，IF阶段立即得到指令
        if self.sync_read:
            rd_port = mem.read_port(domain="sync", transparent_for=[wr_port])
        else:
            rd_port = mem.read_port(domain="comb")

        addr_width = len(wr_port.addr)
        read_addr_index = self.read_addr[:addr_width]
        write_addr_index = self.write_addr[:addr_width]

        m.d.comb += [
            wr_port.addr.eq(write_addr_index),
            wr_port.data.eq(self.write_data),
            wr_port.en.eq(self.write_enable),
            rd_port.addr.eq(read_addr_index),
            self.read_data.eq(rd_port.data),
        ]

        return m


if __name__ == "__main__":
    from amaranth.sim import Simulator

    dut = MemoryFile(depth=256)

    async def bench(ctx):
        # 测试1: 基本同步读写（一周期写入，下周期读取）
        ctx.set(dut.read_addr, 0x10)
        ctx.set(dut.write_addr, 0x10)
        ctx.set(dut.write_data, 0xDEADBEEF)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        # 同步读：数据在下一周期可用
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xDEADBEEF, (
            f"Test 1 failed: expected 0xDEADBEEF, got 0x{read_val:08X}"
        )
        print(f"✓ Test 1 passed: Basic synchronous write/read at addr 0x10")

        # 测试2: 写使能控制
        ctx.set(dut.read_addr, 0x20)
        ctx.set(dut.write_addr, 0x20)
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
            ctx.set(dut.write_addr, addr)
            ctx.set(dut.write_data, data)
            ctx.set(dut.write_enable, 1)
            await ctx.tick()

        ctx.set(dut.write_enable, 0)
        for addr, expected in test_data.items():
            ctx.set(dut.read_addr, addr)
            await ctx.tick()
            read_val = ctx.get(dut.read_data)
            assert read_val == expected, (
                f"Test 3 failed at addr 0x{addr:02X}: expected 0x{expected:08X}, got 0x{read_val:08X}"
            )
        print(f"✓ Test 3 passed: Multiple address write/read")

        # 测试4: 透明写（同时写入和读取同一地址）
        ctx.set(dut.read_addr, 0x50)
        ctx.set(dut.write_addr, 0x50)
        ctx.set(dut.write_data, 0xCAFEBABE)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xCAFEBABE, "Test 4 failed: transparent write"
        print(f"✓ Test 4 passed: Transparent write")

        # 测试5: 数据持久性
        ctx.set(dut.write_addr, 0x42)
        ctx.set(dut.write_data, 0xBEEFCAFE)
        ctx.set(dut.write_enable, 1)
        await ctx.tick()

        ctx.set(dut.write_addr, 0x43)
        ctx.set(dut.write_data, 0x99999999)
        await ctx.tick()

        ctx.set(dut.read_addr, 0x42)
        ctx.set(dut.write_enable, 0)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xBEEFCAFE, "Test 5 failed: data not persistent"
        print(f"✓ Test 5 passed: Data persistence")

        # 测试6: 独立读写地址（读写不同地址）
        # 写入地址0x60
        ctx.set(dut.write_addr, 0x60)
        ctx.set(dut.write_data, 0x11223344)
        ctx.set(dut.write_enable, 1)
        # 同时读取地址0x42（之前写入的数据）
        ctx.set(dut.read_addr, 0x42)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0xBEEFCAFE, "Test 6a failed: read old data while writing new"

        # 验证新写入的数据
        ctx.set(dut.read_addr, 0x60)
        ctx.set(dut.write_enable, 0)
        await ctx.tick()
        read_val = ctx.get(dut.read_data)
        assert read_val == 0x11223344, "Test 6b failed: new data not written"
        print(f"✓ Test 6 passed: Independent read/write addresses")

        print("\n✓ All tests passed!")

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    with sim.write_vcd("memory.vcd"):
        sim.run()
