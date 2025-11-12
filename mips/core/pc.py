from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class PC(wiring.Component):
    enable: In(1)
    addr_in: In(32)
    addr_out: Out(32)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # PC寄存器：只存储高30位（强制4字节对齐）
        pc_reg = Signal(30, reset=0)

        # 输出：拼接2个0到低位，恢复32位地址
        m.d.comb += self.addr_out.eq(pc_reg << 2)

        # 更新逻辑：enable时写入新值（取addr_in的高30位）
        with m.If(self.enable):
            m.d.sync += pc_reg.eq(self.addr_in >> 2)

        return m


if __name__ == "__main__":
    from amaranth.sim import Simulator

    dut = PC()

    async def bench(ctx):
        # 测试1: 初始化后读取PC值（应该为0）
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0, f"Test 1 failed: expected 0, got 0x{pc_val:08X}"
        print(f"✓ Test 1 passed: Initial PC value is 0")

        # 测试2: 写入新的PC值
        ctx.set(dut.addr_in, 0x1000)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x1000, f"Test 2 failed: expected 0x1000, got 0x{pc_val:08X}"
        print(f"✓ Test 2 passed: Write PC value 0x1000")

        # 测试3: 写入下一个PC值（模拟PC+4）
        ctx.set(dut.addr_in, 0x1004)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x1004, f"Test 3 failed: expected 0x1004, got 0x{pc_val:08X}"
        print(f"✓ Test 3 passed: Update PC to 0x1004")

        # 测试4: 连续更新多次（模拟顺序执行）
        for i in range(5):
            expected = 0x1004 + (i + 1) * 4
            ctx.set(dut.addr_in, expected)
            ctx.set(dut.enable, 1)
            await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x1018, f"Test 4 failed: expected 0x1018, got 0x{pc_val:08X}"
        print(f"✓ Test 4 passed: Multiple sequential updates to 0x1018")

        # 测试5: 跳转到新地址
        ctx.set(dut.addr_in, 0x2000)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x2000, f"Test 5 failed: expected 0x2000, got 0x{pc_val:08X}"
        print(f"✓ Test 5 passed: Jump to 0x2000")

        # 测试6: 写入时忽略最低2位（4字节对齐）
        ctx.set(dut.addr_in, 0x3003)  # 非对齐地址
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x3000, (
            f"Test 6 failed: expected 0x3000 (aligned), got 0x{pc_val:08X}"
        )
        print(f"✓ Test 6 passed: Address alignment (0x3003 -> 0x3000)")

        # 测试7: enable=0时PC保持不变
        current_pc = pc_val
        ctx.set(dut.addr_in, 0x9999)
        ctx.set(dut.enable, 0)
        await ctx.tick()
        await ctx.tick()
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == current_pc, (
            f"Test 7 failed: PC changed when enable=0, got 0x{pc_val:08X}"
        )
        print(f"✓ Test 7 passed: PC unchanged when enable=0")

        # 测试8: 边界值测试 - 写入大地址
        ctx.set(dut.addr_in, 0xFFFFFFFC)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0xFFFFFFFC, (
            f"Test 8 failed: expected 0xFFFFFFFC, got 0x{pc_val:08X}"
        )
        print(f"✓ Test 8 passed: Large address 0xFFFFFFFC")

        # 测试9: 溢出处理（30位寄存器）
        # 输入最大32位对齐地址，观察30位存储后的结果
        ctx.set(dut.addr_in, 0xFFFFFFFC)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        expected = 0xFFFFFFFC  # 30位全1，左移2位 = 0xFFFFFFFC
        assert pc_val == expected, (
            f"Test 9 failed: expected 0x{expected:08X}, got 0x{pc_val:08X}"
        )
        print(f"✓ Test 9 passed: Maximum address handling")

        # 测试10: 写入0地址
        ctx.set(dut.addr_in, 0x0)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x0, f"Test 10 failed: expected 0x0, got 0x{pc_val:08X}"
        print(f"✓ Test 10 passed: Write zero address")

        # 测试11: 模拟真实场景 - 函数调用和返回
        # 执行几条指令
        ctx.set(dut.addr_in, 0x1000)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.addr_in, 0x1004)
        await ctx.tick()

        # 函数调用：跳转到0x5000
        ctx.set(dut.addr_in, 0x5000)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x5000, f"Test 11a failed: call to 0x5000"

        # 函数返回：跳回0x1008
        ctx.set(dut.addr_in, 0x1008)
        ctx.set(dut.enable, 1)
        await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x1008, f"Test 11b failed: return to 0x1008"
        print(f"✓ Test 11 passed: Function call/return simulation")

        # 测试12: 快速连续更新（无gap）
        ctx.set(dut.enable, 1)
        for i in range(10):
            ctx.set(dut.addr_in, 0x2000 + i * 4)
            await ctx.tick()
        ctx.set(dut.enable, 0)
        await ctx.tick()
        pc_val = ctx.get(dut.addr_out)
        assert pc_val == 0x2024, f"Test 12 failed: expected 0x2024, got 0x{pc_val:08X}"
        print(f"✓ Test 12 passed: Continuous updates")

        print("\n✓ All tests passed!")

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    with sim.write_vcd("pc.vcd"):
        sim.run()
