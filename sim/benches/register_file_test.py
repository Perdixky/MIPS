import random
from mips.core.cpu import RegFile
from sim.test_utils import SimulationSpec, SimulationTest, run_tests_cli


def build_register_file_spec() -> SimulationSpec:
    dut = RegFile()
    rng = random.Random(0)

    async def bench(ctx):
        # 测试1: 初始状态，所有寄存器应该为0
        print("测试1: 初始读取")
        for _ in range(5):
            reg = rng.randint(0, 31)
            ctx.set(dut.rd_addr0, reg)
            await ctx.tick()
            value = ctx.get(dut.rd_data0)
            print(f"  寄存器 x{reg} = {value}")
            assert value == 0, f"寄存器 x{reg} 初始值应为0"

        # 测试2: 写入并读取（测试非零寄存器）
        print("\n测试2: 写入和读取")
        test_data = {
            1: 0x12345678,
            5: 0xDEADBEEF,
            10: 0xCAFEBABE,
            31: 0xFFFFFFFF,
        }

        for reg, value in test_data.items():
            ctx.set(dut.wr_addr, reg)
            ctx.set(dut.wr_data, value)
            ctx.set(dut.wr_en, 1)
            await ctx.tick()
            ctx.set(dut.wr_en, 0)

            ctx.set(dut.rd_addr0, reg)
            await ctx.tick()
            read_value = ctx.get(dut.rd_data0)
            print(f"  写入 x{reg} = 0x{value:08X}, 读取 = 0x{read_value:08X}")
            assert read_value == value, f"寄存器 x{reg} 读写不匹配"

        # 测试3: 寄存器0永远为0
        print("\n测试3: x0 寄存器保护")
        ctx.set(dut.wr_addr, 0)
        ctx.set(dut.wr_data, 0xDEADBEEF)
        ctx.set(dut.wr_en, 1)
        await ctx.tick()
        ctx.set(dut.wr_en, 0)

        ctx.set(dut.rd_addr0, 0)
        await ctx.tick()
        value = ctx.get(dut.rd_data0)
        print(f"  尝试写入 x0 = 0xDEADBEEF, 实际读取 = 0x{value:08X}")
        assert value == 0, "x0 必须永远为0"

        # 测试4: 双端口同时读取
        print("\n测试4: 双端口同时读取")
        ctx.set(dut.rd_addr0, 1)
        ctx.set(dut.rd_addr1, 5)
        await ctx.tick()
        data0 = ctx.get(dut.rd_data0)
        data1 = ctx.get(dut.rd_data1)
        print(f"  端口0: x1 = 0x{data0:08X}")
        print(f"  端口1: x5 = 0x{data1:08X}")
        assert data0 == 0x12345678
        assert data1 == 0xDEADBEEF

        # 测试5: 写后立即读取
        print("\n测试5: 写后立即读取（透明度测试）")
        ctx.set(dut.wr_addr, 7)
        ctx.set(dut.wr_data, 0xABCD1234)
        ctx.set(dut.wr_en, 1)
        ctx.set(dut.rd_addr0, 7)
        await ctx.tick()

        value = ctx.get(dut.rd_data0)
        print(f"  写入并立即读取 x7 = 0x{value:08X}")
        assert value == 0xABCD1234, "透明端口应该能读到刚写入的值"

        # 测试6: 随机读写测试
        print("\n测试6: 随机读写测试")
        golden_regs = [0] * 32
        golden_regs[1] = 0x12345678
        golden_regs[5] = 0xDEADBEEF
        golden_regs[7] = 0xABCD1234
        golden_regs[10] = 0xCAFEBABE
        golden_regs[31] = 0xFFFFFFFF

        for _ in range(100):
            if rng.random() > 0.5:
                reg = rng.randint(0, 31)
                value = rng.randint(0, 0xFFFFFFFF)
                ctx.set(dut.wr_addr, reg)
                ctx.set(dut.wr_data, value)
                ctx.set(dut.wr_en, 1)

                if reg != 0:
                    golden_regs[reg] = value
            else:
                ctx.set(dut.wr_en, 0)

            reg0 = rng.randint(0, 31)
            reg1 = rng.randint(0, 31)
            ctx.set(dut.rd_addr0, reg0)
            ctx.set(dut.rd_addr1, reg1)

            await ctx.tick()

            data0 = ctx.get(dut.rd_data0)
            data1 = ctx.get(dut.rd_data1)

            assert data0 == golden_regs[reg0], (
                f"x{reg0} 不匹配: 期望 0x{golden_regs[reg0]:08X}, 实际 0x{data0:08X}"
            )
            assert data1 == golden_regs[reg1], (
                f"x{reg1} 不匹配: 期望 0x{golden_regs[reg1]:08X}, 实际 0x{data1:08X}"
            )

        print("  100次随机读写测试通过!")
        print("\n✅ 所有测试通过!")

    return SimulationSpec(dut=dut, bench=bench, vcd_path="regfile.vcd")


def get_tests() -> list[SimulationTest]:
    return [
        SimulationTest(
            key="regfile",
            name="Register File Exhaustive",
            description="覆盖x0保护、双读口和随机压力的寄存器文件测试。",
            build=build_register_file_spec,
            tags=("regfile", "core"),
        )
    ]


def main() -> int:
    return run_tests_cli(get_tests())


if __name__ == "__main__":
    raise SystemExit(main())
