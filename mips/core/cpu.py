from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, Signature
from amaranth.lib.wiring import connect, flipped
from amaranth.lib.coding import Encoder
from enum import IntEnum

from .alu import ALU


def _connect_interface(m, source, target, *, domain="comb"):
    """Assign every field from one interface to another."""
    drive = getattr(m.d, domain)
    for name, member in target.signature.members.items():
        src_field = getattr(source, name)
        dst_field = getattr(target, name)
        if isinstance(member.shape, Signature):
            _connect_interface(m, src_field, dst_field, domain=domain)
        else:
            drive += dst_field.eq(src_field)


# ========== 操作码枚举 ==========
class Opcode(IntEnum):
    """6位操作码定义"""

    # R型指令 (通过funct区分具体操作)
    R_TYPE = 0b000000

    # I型指令
    ADDI = 0b001000
    ANDI = 0b001100
    ORI = 0b001101
    SLTI = 0b001010
    XORI = 0b001110
    LUI = 0b001111

    LW = 0b100011
    SW = 0b101011
    LB = 0b100000
    LBU = 0b100100
    LH = 0b100001
    SB = 0b101000
    SH = 0b101001

    BEQ = 0b000100
    BNE = 0b000101

    # J型指令
    J = 0b000010
    JAL = 0b000011


# ========== R型指令功能码枚举 ==========
class Funct(IntEnum):
    """6位功能码定义 (R型指令使用)"""

    # 算术运算
    ADD = 0b100000
    SUB = 0b100010

    # 逻辑运算
    AND = 0b100100
    OR = 0b100101
    XOR = 0b100110
    NOR = 0b100111

    # 比较运算
    SLT = 0b101010

    # 移位运算
    SLL = 0b000000
    SRL = 0b000010
    SRA = 0b000011

    # 跳转指令
    JR = 0b001000
    JALR = 0b001001


# ========== PC 和寄存器文件类 ==========
class PC(wiring.Component):
    """程序计数器"""

    enable: In(1)
    reset: In(1)
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

        # 更新逻辑：reset时复位到0，enable时写入新值
        with m.If(self.reset):
            m.d.sync += pc_reg.eq(0)
        with m.Elif(self.enable):
            m.d.sync += pc_reg.eq(self.addr_in >> 2)

        return m


class PCController(wiring.Component):
    input: In(PCControllerInput())
    output: Out(PCRegisterInput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.input.stall == 1):
            m.d.comb += self.output.enable.eq(0)
        with m.Else():
            m.d.comb += self.output.enable.eq(1)
            m.d.comb += self.output.addr_in.eq(self.input.id_next_pc)

        return m


class RegFile(wiring.Component):
    """MIPS 寄存器文件（双读单写）"""

    # 读端口0
    rd_addr0: In(5)
    rd_data0: Out(32)

    # 读端口1
    rd_addr1: In(5)
    rd_data1: Out(32)

    # 写端口
    wr_addr: In(5)
    wr_data: In(32)
    wr_en: In(1)

    def __init__(self, depth=32):
        self.depth = depth
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        regs = Array(Signal(32, name=f"r{i}", reset=0) for i in range(self.depth))

        # 读寄存器0时总是返回0
        # 实现"写优先"：如果同时读写同一寄存器，返回写入的值
        rd_data0_reg = Mux(self.rd_addr0 == 0, 0, regs[self.rd_addr0])
        rd_data1_reg = Mux(self.rd_addr1 == 0, 0, regs[self.rd_addr1])

        # 写优先转发
        with m.If(self.wr_en & (self.wr_addr != 0) & (self.wr_addr == self.rd_addr0)):
            m.d.comb += self.rd_data0.eq(self.wr_data)
        with m.Else():
            m.d.comb += self.rd_data0.eq(rd_data0_reg)

        with m.If(self.wr_en & (self.wr_addr != 0) & (self.wr_addr == self.rd_addr1)):
            m.d.comb += self.rd_data1.eq(self.wr_data)
        with m.Else():
            m.d.comb += self.rd_data1.eq(rd_data1_reg)

        # 连接写端口(寄存器0不可写)
        with m.If(self.wr_en & (self.wr_addr != 0)):
            m.d.sync += regs[self.wr_addr].eq(self.wr_data)

        return m


# ========== 流水线接口定义 ==========


class PCRegisterInput(Signature):
    """PC寄存器的写接口：提供写使能与要写入的下一条PC地址。"""

    def __init__(self):
        super().__init__(
            {
                "enable": In(1),  # PC写使能，高电平时更新PC
                "addr_in": In(32),  # 要写入PC的新地址
                "addr_out": Out(32),  # 当前PC输出给取指阶段
            }
        )


class PCControllerInput(Signature):
    """PC控制器输入：提供流水线暂停信号以及ID阶段计算出的下一PC。"""

    def __init__(self):
        super().__init__(
            {
                "stall": In(1),  # 流水线暂停请求
                "id_next_pc": In(32),  # ID阶段给出的下一条PC
            }
        )


class IFStageBus(Signature):
    """IF→ID流水寄存器总线：携带取出的指令和对应的PC。"""

    def __init__(self):
        super().__init__(
            {
                "inst_word": Out(32),  # 取出的指令字
                "next_pc": Out(32),  # 预测的下一条PC地址
                "current_pc": Out(32),  # 当前指令的PC地址
            }
        )


class IDStageBus(Signature):
    """ID→EX总线：传递寄存器索引/数值、立即数及细粒度控制信号。"""

    def __init__(self):
        super().__init__(
            {
                "rs_index": Out(5),  # 源寄存器rs编号
                "rt_index": Out(5),  # 源/目的寄存器rt编号
                "rs_value": Out(32),  # rs读出的数据
                "rt_value": Out(32),  # rt读出的数据
                "imm_value": Out(16),  # 立即数字段
                "shift_amount": Out(5),  # 移位指令的shamt
                # 控制信号
                "alu_opcode": Out(4),  # ALU操作码
                "alu_operand_sel": Out(1),  # ALU第二操作数选择（立即数/寄存器）
                "mem_read_en": Out(1),  # 数据存储器读使能
                "mem_write_en": Out(1),  # 数据存储器写使能
                "dest_reg": Out(5),  # 将要写回的目标寄存器
                "reg_write_en": Out(1),  # 寄存器写回使能
                "mem_to_reg_sel": Out(1),  # 写回数据来源（1=内存，0=ALU）
                "next_pc": Out(32),  # ID阶段计算出的下一条PC
            }
        )


class EXStageBus(Signature):
    """EX→MEM总线：输出ALU结果、访存控制以及写回相关信息。"""

    def __init__(self):
        super().__init__(
            {
                "alu_result_value": Out(32),  # ALU运算结果
                "store_data": Out(32),  # SW等写存指令的数据
                "mem_read_en": Out(1),  # 是否在MEM阶段执行读
                "mem_write_en": Out(1),  # 是否在MEM阶段执行写
                "dest_reg": Out(5),  # 目标寄存器编号
                "reg_write_en": Out(1),  # 写回使能
                "mem_to_reg_sel": Out(1),  # MEM阶段读数据是否写回
            }
        )


class MEMStageBus(Signature):
    """MEM→WB总线：提供访存读取数据或ALU结果以及写回控制。"""

    def __init__(self):
        super().__init__(
            {
                "alu_result_value": Out(32),  # 从EX阶段传下来的ALU结果
                "load_data": Out(32),  # 数据存储器返回的数据
                "dest_reg": Out(5),  # 即将写回的寄存器编号
                "reg_write_en": Out(1),  # 是否需要写回寄存器
                "mem_to_reg_sel": Out(1),  # 写回数据来源选择
            }
        )


class WBStageBus(Signature):
    """写回阶段输出：驱动寄存器文件写口的数据、目标寄存器与使能。"""

    def __init__(self):
        super().__init__(
            {
                "write_back_data": Out(32),  # 准备写回寄存器的数据
                "dest_reg": Out(5),  # 目标寄存器地址
                "reg_write_en": Out(1),  # 写使能信号
            }
        )


class ForwardingSourceBus(Signature):
    """汇聚EX/MEM与MEM/WB阶段可用于转发的写回信息。"""

    def __init__(self):
        super().__init__(
            {
                # EX/MEM阶段
                "ex_mem_reg_write_en": Out(1),  # EX/MEM阶段是否写寄存器
                "ex_mem_dest_reg": Out(5),  # EX/MEM阶段目标寄存器
                "ex_mem_forward_value": Out(32),  # 可转发的数据（一般为ALU结果）
                # MEM/WB阶段
                "mem_wb_reg_write_en": Out(1),  # MEM/WB阶段是否写寄存器
                "mem_wb_dest_reg": Out(5),  # MEM/WB阶段目标寄存器
                "mem_wb_forward_value": Out(32),  # 可供转发的写回数据
            }
        )


class ForwardingInput(Signature):
    """ForwardingUnit输入：包含当前操作数需求以及共享的前递源。"""

    def __init__(self):
        super().__init__(
            {
                # 当前操作数信息（每个ForwardingUnit独立）
                "src_reg": In(5),  # ID或EX阶段当前需要的寄存器编号
                "fallback_data": In(32),  # 未转发时可使用的寄存器读数值
                # 共享的转发源
                "forwarding_source": In(
                    ForwardingSourceBus()
                ),  # EX/MEM与MEM/WB提供的转发信息
            }
        )


class HazardDetectionSourceBus(Signature):
    """冒险检测共享源：广播ID/EX阶段load指令的目标寄存器。"""

    def __init__(self):
        super().__init__(
            {
                "id_ex_mem_read_en": Out(1),  # 当前ID/EX是否执行load
                "id_ex_dest_reg": Out(5),  # load指令准备写入的寄存器
                "id_ex_reg_write_en": Out(1),  # 当前ID/EX是否写回寄存器
                "ex_mem_reg_write_en": Out(1),  # EX/MEM阶段是否写回
                "ex_mem_dest_reg": Out(5),  # EX/MEM阶段目的寄存器
            }
        )


class HazardDetectionInput(Signature):
    """冒险检测输入：指定当前IF/ID阶段引用的源寄存器编号。"""

    def __init__(self):
        super().__init__(
            {
                # 当前源寄存器
                "if_id_src_reg": In(5),  # IF/ID 指令中的源寄存器（rs/rt）
                "opcode": In(6),  # 当前指令操作码
                # 共享的load信息
                "hazard_source": In(HazardDetectionSourceBus()),  # 来自ID/EX的load状态
            }
        )


class HazardDetectionOutput(Signature):
    """冒险检测输出：表示该源寄存器是否触发暂停。"""

    def __init__(self):
        super().__init__(
            {
                "stall": Out(1),  # 如果需要插入气泡则拉高
            }
        )


class ForwardingOutput(Signature):
    """转发单元输出：提供最终选出的操作数值。"""

    def __init__(self):
        super().__init__(
            {
                "forwarded_value": Out(32),  # 转发后的数据（给EX阶段使用）
            }
        )


class BranchTargetBuffer(wiring.Component):
    """BTB"""

    lookup_addr: In(32)
    hit: Out(1)
    target_addr: Out(32)
    predicted: Out(1)

    update_addr: In(32)
    update_target: In(32)
    update_enable: In(1)

    def __init__(self, size=16):
        self.size = size
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        index = Signal(self.size.bit_length(), reset=0)
        tag_array = Array(
            Signal(30, name=f"tag_{i}", reset=0) for i in range(self.size)
        )
        target_array = Array(
            Signal(30, name=f"target_{i}", reset=0) for i in range(self.size)
        )
        predicted_array = Array(
            Signal(1, name=f"predicted_{i}", reset=0) for i in range(self.size)
        )

        lookup_match = Signal(self.size)
        for i in range(self.size):
            m.d.comb += lookup_match[i].eq(lookup_addr == (tag_array[i] << 2))

        m.submodules.encoder = encoder = Encoder(self.size)
        m.d.comb += encoder.i.eq(lookup_match)

        m.d.comb += self.hit.eq(~encoder.n)
        m.d.comb += self.predicted.eq(predicted_array[encoder.o])

        with m.If(self.update_enable):
            update_match = Signal(self.length)
            for i in range(self.size):
                m.d.comb += update_match[i].eq(update_addr == (tag_array[i] << 2))

            m.submodules.encoder = encoder = Encoder(self.size)
            m.d.comb += encoder.i.eq(update_match)

            with m.If(encoder.n == 0):
                m.d.sync += tag_array[index].eq(update_addr >> 2)
                m.d.sync += target_array[index].eq(update_target >> 2)
                m.d.sync += index.eq(index + 1)

            with m.Else():
                m.d.sync += target_array[encoder.o].eq(update_target >> 2)

        return m


class InstructionFetchStage(wiring.Component):
    """Instruction Fetch 阶段：根据 PC 取指并产生下一条指令的 PC。"""

    pc_current: In(32)

    btb_predicted: In(32)
    btb_hit: In(1)
    btb_predicted_taken: In(1)

    btb_lookup_addr: Out(32)

    imem_addr: Out(32)
    imem_data_in: In(32)
    flush_request: In(1)
    stall: In(1)
    reset: In(1)

    # 使用Signature接口输出
    output: Out(IFStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.btb_lookup_addr.eq(self.pc_current)

        # 保存前一个PC值，用于stall时重新取指
        prev_pc = Signal(32, reset=0)
        with m.If(self.reset):
            m.d.sync += prev_pc.eq(0)
        with m.Elif(~self.stall):
            m.d.sync += prev_pc.eq(self.pc_current)

        # 输出当前PC（供ID阶段使用）
        # stall时使用prev_pc，因为当前指令还没被处理
        with m.If(self.stall):
            m.d.comb += self.output.current_pc.eq(prev_pc)
        with m.Else():
            m.d.comb += self.output.current_pc.eq(self.pc_current)

        # 暂时禁用BTB预测，总是预测顺序执行
        with m.If(self.btb_hit & (self.btb_predicted_taken == 1)):
            m.d.comb += self.output.next_pc.eq(self.btb_predicted)
        with m.Else():
            m.d.comb += self.output.next_pc.eq(self.pc_current + 4)

        # 指令内存地址：stall时使用prev_pc重新取同一条指令
        with m.If(self.stall):
            m.d.comb += self.imem_addr.eq(prev_pc)
        with m.Else():
            m.d.comb += self.imem_addr.eq(self.pc_current)

        # 如果 reset 或 flush，输出NOP；否则输出读取的指令
        with m.If(self.reset | self.flush_request):
            m.d.comb += self.output.inst_word.eq(0)  # NOP instruction on reset/flush
        with m.Else():
            m.d.comb += self.output.inst_word.eq(self.imem_data_in)
        return m


class IFIDRegister(wiring.Component):
    """IF/ID 流水寄存器：缓存取指阶段产生的指令和 PC。"""

    input: In(IFStageBus())
    stall: In(1)  # 暂停信号
    output: Out(IFStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        with m.If(~self.stall):
            _connect_interface(m, self.input, self.output, domain="sync")
        return m


# class TwoBitPredictor(wiring.Component):
#     """两位饱和计数分支预测器。"""
#
#     input_bit: In(1)
#     output_bit: Out(1)
#
#     def __init__(self):
#         super().__init__()
#
#     def elaborate(self, platform):
#         m = Module()
#         counter = Signal(2)
#         with m.If(self.input_bit == 1):
#             with m.If(counter != 3):
#                 m.d.sync += counter.eq(counter + 1)
#         with m.Else():
#             with m.If(counter != 0):
#                 m.d.sync += counter.eq(counter - 1)


class HazardDetectionUnit(wiring.Component):
    input: In(HazardDetectionInput())
    output: Out(HazardDetectionOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 提取共享源信号
        haz_src = self.input.hazard_source

        # Load-Use冒险检测：ID/EX阶段是load指令且目标寄存器与当前源寄存器冲突
        load_use_hazard = (
            (haz_src.id_ex_mem_read_en == 1)  # ID/EX阶段是load指令
            & (haz_src.id_ex_dest_reg != 0)  # 目标寄存器不是$0
            & (haz_src.id_ex_dest_reg == self.input.if_id_src_reg)  # 寄存器冲突
        )

        # Branch Hazard检测：分支需要最新寄存器值，但ID阶段没有转发
        is_branch = (self.input.opcode == Opcode.BEQ) | (self.input.opcode == Opcode.BNE)

        branch_hazard_ex = (
            is_branch
            & (self.input.if_id_src_reg != 0)
            & haz_src.id_ex_reg_write_en
            & (haz_src.id_ex_dest_reg == self.input.if_id_src_reg)
        )

        branch_hazard_mem = (
            is_branch
            & (self.input.if_id_src_reg != 0)
            & haz_src.ex_mem_reg_write_en
            & (haz_src.ex_mem_dest_reg == self.input.if_id_src_reg)
        )

        m.d.comb += self.output.stall.eq(load_use_hazard | branch_hazard_ex | branch_hazard_mem)

        return m


class InstructionDecodeStage(wiring.Component):
    """Instruction Decode 阶段：解析指令并生成控制信号、寄存器源数据。"""

    # 输入接口
    input: In(IFStageBus())
    rs_value_in: In(32)
    rt_value_in: In(32)

    current_pc: In(32)

    # 输出接口
    output: Out(IDStageBus())
    pc_en_out: Out(1)
    forward_en_out: Out(1)

    flush_request: Out(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 提取所有指令都有的字段
        inst_word = self.input.inst_word
        pc_snapshot = self.input.next_pc

        opcode = inst_word[26:32]
        rs = inst_word[21:26]
        rt = inst_word[16:21]

        # 默认输出所有指令都有的字段
        m.d.comb += self.output.rs_index.eq(rs)
        m.d.comb += self.output.rt_index.eq(rt)
        m.d.comb += self.output.rs_value.eq(self.rs_value_in)
        m.d.comb += self.output.rt_value.eq(self.rt_value_in)

        # 默认控制信号
        m.d.comb += self.output.mem_read_en.eq(0)
        m.d.comb += self.output.mem_write_en.eq(0)
        m.d.comb += self.output.reg_write_en.eq(0)
        m.d.comb += self.output.mem_to_reg_sel.eq(0)
        m.d.comb += self.pc_en_out.eq(1)

        # 处理PC输出：J型指令跳转，其他指令PC+4
        with m.If((opcode == Opcode.J) | (opcode == Opcode.JAL)):
            jump_addr = Cat(Const(0, 2), inst_word[0:26], pc_snapshot[28:32])
            m.d.comb += self.output.next_pc.eq(jump_addr)
            with m.If(self.input.next_pc != jump_addr):
                m.d.comb += self.flush_request.eq(1)

        with m.Else():
            m.d.comb += self.output.next_pc.eq(self.input.next_pc)

        # 按指令类型分组处理
        with m.If(opcode == Opcode.R_TYPE):
            # R型指令：使用寄存器作为ALU操作数
            m.d.comb += self.output.alu_operand_sel.eq(0)

            rd = inst_word[11:16]
            shamt = inst_word[6:11]
            funct = inst_word[0:6]

            m.d.comb += self.output.shift_amount.eq(shamt)

            # R型指令写回rd，数据来自ALU
            m.d.comb += self.output.dest_reg.eq(rd)
            m.d.comb += self.output.reg_write_en.eq(1)
            m.d.comb += self.output.mem_to_reg_sel.eq(0)

            with m.Switch(funct):
                with m.Case(Funct.ADD):
                    m.d.comb += self.output.alu_opcode.eq(0b0000)
                with m.Case(Funct.SUB):
                    m.d.comb += self.output.alu_opcode.eq(0b0001)
                with m.Case(Funct.AND):
                    m.d.comb += self.output.alu_opcode.eq(0b0010)
                with m.Case(Funct.OR):
                    m.d.comb += self.output.alu_opcode.eq(0b0011)
                with m.Case(Funct.SLT):
                    m.d.comb += self.output.alu_opcode.eq(0b0100)
                with m.Case(Funct.SLL):
                    m.d.comb += self.output.alu_opcode.eq(0b0101)
                with m.Case(Funct.SRL):
                    m.d.comb += self.output.alu_opcode.eq(0b0110)

        with m.Elif(
            (opcode == Opcode.ADDI)
            | (opcode == Opcode.ANDI)
            | (opcode == Opcode.ORI)
            | (opcode == Opcode.SLTI)
            | (opcode == Opcode.LW)
            | (opcode == Opcode.SW)
        ):
            # I型算术/逻辑/访存指令：使用立即数作为ALU操作数
            m.d.comb += self.output.alu_operand_sel.eq(1)

            imm = inst_word[0:16]
            m.d.comb += self.output.imm_value.eq(imm)

            with m.Switch(opcode):
                with m.Case(Opcode.ADDI):
                    m.d.comb += self.output.alu_opcode.eq(0b0000)
                    m.d.comb += self.output.dest_reg.eq(rt)
                    m.d.comb += self.output.reg_write_en.eq(1)
                with m.Case(Opcode.ANDI):
                    m.d.comb += self.output.alu_opcode.eq(0b0010)
                    m.d.comb += self.output.dest_reg.eq(rt)
                    m.d.comb += self.output.reg_write_en.eq(1)
                with m.Case(Opcode.ORI):
                    m.d.comb += self.output.alu_opcode.eq(0b0011)
                    m.d.comb += self.output.dest_reg.eq(rt)
                    m.d.comb += self.output.reg_write_en.eq(1)
                with m.Case(Opcode.SLTI):
                    m.d.comb += self.output.alu_opcode.eq(0b0100)
                    m.d.comb += self.output.dest_reg.eq(rt)
                    m.d.comb += self.output.reg_write_en.eq(1)
                with m.Case(Opcode.LW):
                    m.d.comb += self.output.alu_opcode.eq(0b0000)
                    m.d.comb += self.output.mem_read_en.eq(1)
                    m.d.comb += self.output.dest_reg.eq(rt)
                    m.d.comb += self.output.reg_write_en.eq(1)
                    m.d.comb += self.output.mem_to_reg_sel.eq(1)
                with m.Case(Opcode.SW):
                    m.d.comb += self.output.alu_opcode.eq(0b0000)
                    m.d.comb += self.output.mem_write_en.eq(1)
                    # SW不写寄存器

        with m.Elif((opcode == Opcode.BEQ) | (opcode == Opcode.BNE)):
            # I型分支指令：比较两个寄存器
            m.d.comb += self.output.alu_operand_sel.eq(0)

            imm = inst_word[0:16]
            imm_ext = Cat(imm, imm[15].replicate(16))

            # 分支指令不写寄存器
            with m.Switch(opcode):
                with m.Case(Opcode.BEQ):
                    with m.If(self.rs_value_in == self.rt_value_in):
                        m.d.comb += self.output.next_pc.eq(
                            self.current_pc + 4 + (imm_ext << 2)
                        )
                        with m.If(self.input.next_pc != (self.current_pc + 4 + (imm_ext << 2))):
                            m.d.comb += self.flush_request.eq(1)

                with m.Case(Opcode.BNE):
                    with m.If(self.rs_value_in != self.rt_value_in):
                        m.d.comb += self.output.next_pc.eq(
                            self.current_pc + 4 + (imm_ext << 2)
                        )
                        with m.If(self.input.next_pc != (self.current_pc + 4 + (imm_ext << 2))):
                            m.d.comb += self.flush_request.eq(1)

        with m.Elif(opcode == Opcode.JAL):
            # JAL指令：写$31寄存器，数据来自PC+4
            m.d.comb += self.output.dest_reg.eq(31)
            m.d.comb += self.output.reg_write_en.eq(1)
            m.d.comb += self.output.mem_to_reg_sel.eq(0)

        return m


class IDEXRegister(wiring.Component):
    """ID/EX 流水寄存器：在译码与执行阶段之间传递控制/数据信号。"""

    input: In(IDStageBus())
    stall: In(1)  # 当stall时插入NOP
    output: Out(IDStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 始终传递数据信号
        m.d.sync += [
            self.output.rs_index.eq(self.input.rs_index),
            self.output.rt_index.eq(self.input.rt_index),
            self.output.rs_value.eq(self.input.rs_value),
            self.output.rt_value.eq(self.input.rt_value),
            self.output.imm_value.eq(self.input.imm_value),
            self.output.shift_amount.eq(self.input.shift_amount),
            self.output.alu_opcode.eq(self.input.alu_opcode),
            self.output.alu_operand_sel.eq(self.input.alu_operand_sel),
            self.output.dest_reg.eq(self.input.dest_reg),
            self.output.mem_to_reg_sel.eq(self.input.mem_to_reg_sel),
            self.output.next_pc.eq(self.input.next_pc),
        ]

        # 控制信号：stall时插入气泡
        with m.If(self.stall):
            m.d.sync += [
                self.output.mem_read_en.eq(0),
                self.output.mem_write_en.eq(0),
                self.output.reg_write_en.eq(0),
            ]
        with m.Else():
            m.d.sync += [
                self.output.mem_read_en.eq(self.input.mem_read_en),
                self.output.mem_write_en.eq(self.input.mem_write_en),
                self.output.reg_write_en.eq(self.input.reg_write_en),
            ]
        return m


class ForwardingUnit(wiring.Component):
    """
    转发单元（Forwarding Unit）

    功能：检测数据冒险并选择正确的操作数来源
    - 如果前一条指令（在EX/MEM阶段）会写当前需要的寄存器，从EX/MEM转发
    - 如果前前条指令（在MEM/WB阶段）会写当前需要的寄存器，从MEM/WB转发
    - 否则使用ID/EX流水线寄存器中的数据

    注意：$0寄存器永远不转发（因为$0恒为0）
    """

    input: In(ForwardingInput())
    output: Out(ForwardingOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 为了代码简洁，提取转发源信号
        fwd_src = self.input.forwarding_source

        # EX hazard: 前一条指令（在EX/MEM）写当前需要的寄存器
        ex_hazard = (
            (self.input.src_reg != 0)  # 不是$0
            & fwd_src.ex_mem_reg_write_en  # 前一条指令要写寄存器
            & (self.input.src_reg == fwd_src.ex_mem_dest_reg)  # 寄存器匹配
        )

        # MEM hazard: 前前条指令（在MEM/WB）写当前需要的寄存器
        mem_hazard = (
            (self.input.src_reg != 0)  # 不是$0
            & fwd_src.mem_wb_reg_write_en  # 前前条指令要写寄存器
            & (self.input.src_reg == fwd_src.mem_wb_dest_reg)  # 寄存器匹配
        )

        # 选择数据源（EX hazard优先级高于MEM hazard）
        with m.If(ex_hazard):
            # 从EX/MEM转发
            m.d.comb += self.output.forwarded_value.eq(fwd_src.ex_mem_forward_value)
        with m.Elif(mem_hazard):
            # 从MEM/WB转发
            m.d.comb += self.output.forwarded_value.eq(fwd_src.mem_wb_forward_value)
        with m.Else():
            # 使用ID/EX的数据（无冒险）
            m.d.comb += self.output.forwarded_value.eq(self.input.fallback_data)

        return m


class ExecuteStage(wiring.Component):
    """Execute 阶段：负责 ALU 计算并准备写回/访存数据。"""

    input: In(IDStageBus())
    output: Out(EXStageBus())

    # 转发数据输入（来自ForwardingUnit的输出）
    forwarding_rs: In(ForwardingOutput())
    forwarding_rt: In(ForwardingOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 实例化ALU作为子模块
        m.submodules.alu = alu = ALU()

        # ALU 第二操作数选择（立即数或转发后的寄存器）
        alu_b = Signal(signed(32))
        with m.If(self.input.alu_operand_sel == 1):
            # 逻辑立即数（ANDI/ORI）使用零扩展，其余指令符号扩展
            is_logic_imm = (self.input.alu_opcode == 0b0010) | (
                self.input.alu_opcode == 0b0011
            )
            with m.If(is_logic_imm):
                m.d.comb += alu_b.eq(Cat(self.input.imm_value, Const(0, 16)))
            with m.Else():
                imm_ext = Cat(
                    self.input.imm_value, self.input.imm_value[15].replicate(16)
                )
                m.d.comb += alu_b.eq(imm_ext)
        with m.Else():
            # 使用转发后的rt数据
            m.d.comb += alu_b.eq(self.forwarding_rt.forwarded_value)

        # 连接ALU输入（使用转发后的数据）
        m.d.comb += alu.a.eq(self.forwarding_rs.forwarded_value)
        m.d.comb += alu.b.eq(alu_b)
        m.d.comb += alu.shamt.eq(self.input.shift_amount)
        m.d.comb += alu.op.eq(self.input.alu_opcode)

        # 连接ALU输出到下一阶段
        m.d.comb += self.output.alu_result_value.eq(alu.result)

        # 传递其他信号（mem_write_data也需要使用转发后的rt）
        m.d.comb += self.output.store_data.eq(self.forwarding_rt.forwarded_value)
        m.d.comb += self.output.mem_read_en.eq(self.input.mem_read_en)
        m.d.comb += self.output.mem_write_en.eq(self.input.mem_write_en)
        m.d.comb += self.output.dest_reg.eq(self.input.dest_reg)
        m.d.comb += self.output.reg_write_en.eq(self.input.reg_write_en)
        m.d.comb += self.output.mem_to_reg_sel.eq(self.input.mem_to_reg_sel)

        return m


class EXMEMRegister(wiring.Component):
    """EX/MEM 流水寄存器：缓存执行结果供访存阶段使用。"""

    input: In(EXStageBus())
    output: Out(EXStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        _connect_interface(m, self.input, self.output, domain="sync")
        return m


class MemoryStage(wiring.Component):
    """Memory 阶段：与数据存储器交互并产生写回数据。"""

    input: In(EXStageBus())

    # 外部内存接口
    mem_addr_out: Out(32)
    mem_write_data_out: Out(32)
    mem_write_en_out: Out(1)
    mem_read_data_in: In(32)

    # 输出到下一阶段
    output: Out(MEMStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # 总是传递的信号
        m.d.comb += self.mem_addr_out.eq(self.input.alu_result_value)
        m.d.comb += self.output.alu_result_value.eq(self.input.alu_result_value)
        m.d.comb += self.output.dest_reg.eq(self.input.dest_reg)
        m.d.comb += self.output.reg_write_en.eq(self.input.reg_write_en)
        m.d.comb += self.output.mem_to_reg_sel.eq(self.input.mem_to_reg_sel)

        # 内存操作控制
        with m.If(self.input.mem_write_en == 1):
            m.d.comb += self.mem_write_data_out.eq(self.input.store_data)
            m.d.comb += self.mem_write_en_out.eq(1)
            m.d.comb += self.output.load_data.eq(0)  # 写操作时不需要读数据
        with m.Elif(self.input.mem_read_en == 1):
            m.d.comb += self.mem_write_en_out.eq(0)
            m.d.comb += self.output.load_data.eq(self.mem_read_data_in)
            m.d.comb += self.mem_write_data_out.eq(0)  # 读操作时不需要写数据
        with m.Else():
            # 既不读也不写
            m.d.comb += self.mem_write_en_out.eq(0)
            m.d.comb += self.output.load_data.eq(0)
            m.d.comb += self.mem_write_data_out.eq(0)

        return m


class MEMWBRegister(wiring.Component):
    """MEM/WB 流水寄存器：在访存和回写之间转发结果。"""

    input: In(MEMStageBus())
    output: Out(MEMStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        _connect_interface(m, self.input, self.output, domain="sync")
        return m


class WriteBackStage(wiring.Component):
    """Write Back 阶段：决定写回寄存器堆的数据来源。"""

    input: In(MEMStageBus())
    output: Out(WBStageBus())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.input.mem_to_reg_sel == 1):
            m.d.comb += self.output.write_back_data.eq(self.input.load_data)
        with m.Else():
            m.d.comb += self.output.write_back_data.eq(self.input.alu_result_value)

        m.d.comb += self.output.dest_reg.eq(self.input.dest_reg)
        m.d.comb += self.output.reg_write_en.eq(self.input.reg_write_en)

        return m


class CPU(wiring.Component):
    # 控制接口
    reset: In(1)

    # 指令内存接口
    imem_addr: Out(32)
    imem_rdata: In(32)

    # 数据内存接口（读写地址分离以支持同步内存）
    dmem_read_addr: Out(32)   # 读地址：来自EX阶段，提前一周期发出
    dmem_write_addr: Out(32)  # 写地址：来自MEM阶段
    dmem_wdata: Out(32)
    dmem_wen: Out(1)
    dmem_rdata: In(32)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # ========== 实例化所有子模块 ==========
        m.submodules.pc = pc = PC()
        m.submodules.pc_controller = pc_controller = PCController()
        m.submodules.regfile = regfile = RegFile()
        m.submodules.forwarding_unit_rs = forwarding_unit_rs = ForwardingUnit()
        m.submodules.forwarding_unit_rt = forwarding_unit_rt = ForwardingUnit()
        m.submodules.hazard_detection_rs = hazard_detection_rs = HazardDetectionUnit()
        m.submodules.hazard_detection_rt = hazard_detection_rt = HazardDetectionUnit()

        m.submodules.fetch_stage = fetch_stage = InstructionFetchStage()
        m.submodules.if_id_reg = if_id_reg = IFIDRegister()
        m.submodules.decode_stage = decode_stage = InstructionDecodeStage()
        m.submodules.id_ex_reg = id_ex_reg = IDEXRegister()
        m.submodules.execute_stage = execute_stage = ExecuteStage()
        m.submodules.ex_mem_reg = ex_mem_reg = EXMEMRegister()
        m.submodules.memory_stage = memory_stage = MemoryStage()
        m.submodules.mem_wb_reg = mem_wb_reg = MEMWBRegister()
        m.submodules.writeback_stage = writeback_stage = WriteBackStage()

        # ========== 使用 connect 连接流水线阶段 ==========
        connect(m, fetch_stage.output, if_id_reg.input)
        connect(m, if_id_reg.output, decode_stage.input)
        connect(m, decode_stage.output, id_ex_reg.input)
        connect(m, id_ex_reg.output, execute_stage.input)
        connect(m, execute_stage.output, ex_mem_reg.input)
        connect(m, ex_mem_reg.output, memory_stage.input)
        connect(m, memory_stage.output, mem_wb_reg.input)
        connect(m, mem_wb_reg.output, writeback_stage.input)

        # ========== 寄存器文件连接 ==========
        # 读端口（ID阶段）
        m.d.comb += [
            regfile.rd_addr0.eq(decode_stage.output.rs_index),
            regfile.rd_addr1.eq(decode_stage.output.rt_index),
            decode_stage.rs_value_in.eq(regfile.rd_data0),
            decode_stage.rt_value_in.eq(regfile.rd_data1),
            decode_stage.current_pc.eq(if_id_reg.output.current_pc),
        ]

        # 写端口（WB阶段）
        m.d.comb += [
            regfile.wr_addr.eq(writeback_stage.output.dest_reg),
            regfile.wr_data.eq(writeback_stage.output.write_back_data),
            regfile.wr_en.eq(writeback_stage.output.reg_write_en),
        ]

        # ========== 指令内存连接 ==========
        m.d.comb += [
            self.imem_addr.eq(fetch_stage.imem_addr),
            fetch_stage.imem_data_in.eq(self.imem_rdata),
        ]

        # ========== 数据内存连接 ==========
        # 读地址直接来自EX阶段（组合逻辑），在EX周期发出，MEM周期得到数据
        # 写地址来自MEM阶段（经过EX/MEM寄存器），与写数据同步
        m.d.comb += [
            self.dmem_read_addr.eq(execute_stage.output.alu_result_value),
            self.dmem_write_addr.eq(memory_stage.mem_addr_out),
            self.dmem_wdata.eq(memory_stage.mem_write_data_out),
            self.dmem_wen.eq(memory_stage.mem_write_en_out),
            memory_stage.mem_read_data_in.eq(self.dmem_rdata),
        ]

        # ========== ForwardingUnit连接（优雅版 - 使用嵌套接口避免重复） ==========

        # 连接共享的转发源到两个ForwardingUnit（只需连接一次！）
        for fu in [forwarding_unit_rs, forwarding_unit_rt]:
            m.d.comb += [
                # EX/MEM阶段转发源
                fu.input.forwarding_source.ex_mem_reg_write_en.eq(
                    ex_mem_reg.output.reg_write_en
                ),
                fu.input.forwarding_source.ex_mem_dest_reg.eq(
                    ex_mem_reg.output.dest_reg
                ),
                fu.input.forwarding_source.ex_mem_forward_value.eq(
                    ex_mem_reg.output.alu_result_value
                ),
                # MEM/WB阶段转发源
                fu.input.forwarding_source.mem_wb_reg_write_en.eq(
                    mem_wb_reg.output.reg_write_en
                ),
                fu.input.forwarding_source.mem_wb_dest_reg.eq(
                    mem_wb_reg.output.dest_reg
                ),
                fu.input.forwarding_source.mem_wb_forward_value.eq(
                    writeback_stage.output.write_back_data
                ),
            ]

        # 连接各自的源寄存器和备用数据
        m.d.comb += [
            # rs操作数
            forwarding_unit_rs.input.src_reg.eq(id_ex_reg.output.rs_index),
            forwarding_unit_rs.input.fallback_data.eq(id_ex_reg.output.rs_value),
            # rt操作数
            forwarding_unit_rt.input.src_reg.eq(id_ex_reg.output.rt_index),
            forwarding_unit_rt.input.fallback_data.eq(id_ex_reg.output.rt_value),
        ]

        # ForwardingUnit输出 → ExecuteStage
        connect(m, forwarding_unit_rs.output, execute_stage.forwarding_rs)
        connect(m, forwarding_unit_rt.output, execute_stage.forwarding_rt)

        # ========== HazardDetectionUnit连接（优雅版 - 使用嵌套接口避免重复） ==========

        # 连接共享的hazard源到两个HazardDetectionUnit（只需连接一次！）
        for hd in [hazard_detection_rs, hazard_detection_rt]:
            m.d.comb += [
                # ID/EX阶段的load信息
                hd.input.hazard_source.id_ex_mem_read_en.eq(
                    id_ex_reg.output.mem_read_en
                ),
                hd.input.hazard_source.id_ex_dest_reg.eq(id_ex_reg.output.dest_reg),
                hd.input.hazard_source.id_ex_reg_write_en.eq(
                    id_ex_reg.output.reg_write_en
                ),
                hd.input.hazard_source.ex_mem_reg_write_en.eq(
                    ex_mem_reg.output.reg_write_en
                ),
                hd.input.hazard_source.ex_mem_dest_reg.eq(ex_mem_reg.output.dest_reg),
            ]

        # 连接各自的源寄存器（IF/ID阶段）
        m.d.comb += [
            # rs操作数
            hazard_detection_rs.input.if_id_src_reg.eq(
                if_id_reg.output.inst_word[21:26]
            ),
            hazard_detection_rs.input.opcode.eq(if_id_reg.output.inst_word[26:32]),
            # rt操作数
            hazard_detection_rt.input.if_id_src_reg.eq(
                if_id_reg.output.inst_word[16:21]
            ),
            hazard_detection_rt.input.opcode.eq(if_id_reg.output.inst_word[26:32]),
        ]

        # 合并stall信号：任何一个检测到冒险就暂停流水线
        pipeline_stall = Signal()
        m.d.comb += pipeline_stall.eq(
            hazard_detection_rs.output.stall | hazard_detection_rt.output.stall
        )

        # 连接stall信号到IF/ID寄存器、ID/EX寄存器和fetch_stage
        m.d.comb += if_id_reg.stall.eq(pipeline_stall)
        m.d.comb += id_ex_reg.stall.eq(pipeline_stall)
        m.d.comb += fetch_stage.stall.eq(pipeline_stall)

        # 连接reset信号
        m.d.comb += fetch_stage.reset.eq(self.reset)

        # 连接flush_request信号
        m.d.comb += fetch_stage.flush_request.eq(decode_stage.flush_request)

        # ========== PC和PCController连接 ==========
        # PC输出连接到取指阶段
        m.d.comb += fetch_stage.pc_current.eq(pc.addr_out)

        # PCController输入连接
        # 当有分支/跳转时使用decode_stage的next_pc，否则使用fetch_stage的
        next_pc_sel = Signal(32)
        with m.If(decode_stage.flush_request):
            m.d.comb += next_pc_sel.eq(decode_stage.output.next_pc)
        with m.Else():
            m.d.comb += next_pc_sel.eq(fetch_stage.output.next_pc)

        m.d.comb += [
            pc_controller.input.stall.eq(pipeline_stall),
            pc_controller.input.id_next_pc.eq(next_pc_sel),
        ]

        # PCController输出连接到PC
        m.d.comb += [
            pc.enable.eq(pc_controller.output.enable),
            pc.addr_in.eq(pc_controller.output.addr_in),
            pc.reset.eq(self.reset),
        ]

        return m
