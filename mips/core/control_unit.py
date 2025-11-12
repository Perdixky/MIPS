from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, Signature
from amaranth.lib.wiring import connect, flipped
from enum import IntEnum

from .alu import ALU
from .pc import PC
from .register_file import RegFile


# ========== ????? ==========
class Opcode(IntEnum):
    """6??????"""

    # R??? (??funct??????)
    R_TYPE = 0b000000

    # I???
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

    # J???
    J = 0b000010
    JAL = 0b000011


# ========== R???????? ==========
class Funct(IntEnum):
    """6?????? (R?????)"""

    # ????
    ADD = 0b100000
    SUB = 0b100010

    # ????
    AND = 0b100100
    OR = 0b100101
    XOR = 0b100110
    NOR = 0b100111

    # ????
    SLT = 0b101010

    # ????
    SLL = 0b000000
    SRL = 0b000010
    SRA = 0b000011

    # ????
    JR = 0b001000
    JALR = 0b001001


# ========== ??????? ==========
class IFOutput(Signature):
    """IF??????"""
    def __init__(self):
        super().__init__({
            "instruction": Out(32),
            "pc": Out(32),
        })

class IDOutput(Signature):
    """ID??????"""
    def __init__(self):
        super().__init__({
            "rs": Out(5),
            "rt": Out(5),
            "rs_data": Out(32),
            "rt_data": Out(32),
            "imm": Out(16),
            "shamt": Out(5),
            # ????
            "alu_op": Out(4),
            "alu_src": Out(1),
            "mem_read": Out(1),
            "mem_write": Out(1),
            "write_reg": Out(5),
            "reg_write": Out(1),
            "mem_to_reg": Out(1),
            "pc": Out(32),
        })

class EXOutput(Signature):
    """EX??????"""
    def __init__(self):
        super().__init__({
            "alu_result": Out(32),
            "mem_write_data": Out(32),
            "mem_read": Out(1),
            "mem_write": Out(1),
            "write_reg": Out(5),
            "reg_write": Out(1),
            "mem_to_reg": Out(1),
        })

class MEMOutput(Signature):
    """MEM??????"""
    def __init__(self):
        super().__init__({
            "alu_result": Out(32),
            "mem_data": Out(32),
            "write_reg": Out(5),
            "reg_write": Out(1),
            "mem_to_reg": Out(1),
        })

class WBOutput(Signature):
    """WB??????"""
    def __init__(self):
        super().__init__({
            "write_data": Out(32),
            "write_reg": Out(5),
            "reg_write": Out(1),
        })


class IF_Stage(wiring.Component):
    pc_in: In(32)
    memory_addr: Out(32)
    memory_read: In(32)
    flush: In(1)

    # ??Signature????
    output: Out(IFOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.output.pc.eq(self.pc_in + 4)
        with m.If(self.flush):
            m.d.comb += self.output.instruction.eq(0)  # NOP instruction on flush
        with m.Else():
            m.d.comb += self.memory_addr.eq(self.pc_in)
            m.d.comb += self.output.instruction.eq(self.memory_read)
        return m


class IF_ID_Pipeline_Reg(wiring.Component):
    input: In(IFOutput())
    output: Out(IFOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        # ???????????????????????????????
        m.d.comb += self.output.eq(self.input)
        return m


class TwoBitRredictor(wiring.Component):
    input_bit: In(1)
    output_bit: Out(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        counter = Signal(2)
        with m.If(self.input_bit == 1):
            with m.If(counter != 3):
                m.d.sync += counter.eq(counter + 1)
        with m.Else():
            with m.If(counter != 0):
                m.d.sync += counter.eq(counter - 1)


class ID_Stage(wiring.Component):
    # ????
    input: In(IFOutput())
    rs_data_in: In(32)
    rt_data_in: In(32)

    # ????
    output: Out(IDOutput())
    pc_en_out: Out(1)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # ???????????
        instruction = self.input.instruction
        pc_in = self.input.pc

        opcode = instruction[26:32]
        rs = instruction[21:26]
        rt = instruction[16:21]

        # ?????????????
        m.d.comb += self.output.rs.eq(rs)
        m.d.comb += self.output.rt.eq(rt)
        m.d.comb += self.output.rs_data.eq(self.rs_data_in)
        m.d.comb += self.output.rt_data.eq(self.rt_data_in)

        # ??????
        m.d.comb += self.output.mem_read.eq(0)
        m.d.comb += self.output.mem_write.eq(0)
        m.d.comb += self.output.reg_write.eq(0)
        m.d.comb += self.output.mem_to_reg.eq(0)
        m.d.comb += self.pc_en_out.eq(1)

        # ??PC???J??????????PC+4
        with m.If((opcode == Opcode.J) | (opcode == Opcode.JAL)):
            jump_addr = Cat(Const(0, 2), instruction[0:26], pc_in[28:32])
            m.d.comb += self.output.pc.eq(jump_addr)
        with m.Else():
            m.d.comb += self.output.pc.eq(pc_in + 4)

        # ?????????
        with m.If(opcode == Opcode.R_TYPE):
            # R???????????ALU???
            m.d.comb += self.output.alu_src.eq(0)

            rd = instruction[11:16]
            shamt = instruction[6:11]
            funct = instruction[0:6]

            m.d.comb += self.output.shamt.eq(shamt)

            # R?????rd?????ALU
            m.d.comb += self.output.write_reg.eq(rd)
            m.d.comb += self.output.reg_write.eq(1)
            m.d.comb += self.output.mem_to_reg.eq(0)

            with m.Switch(funct):
                with m.Case(Funct.ADD):
                    m.d.comb += self.output.alu_op.eq(0b0000)
                with m.Case(Funct.SUB):
                    m.d.comb += self.output.alu_op.eq(0b0001)
                with m.Case(Funct.AND):
                    m.d.comb += self.output.alu_op.eq(0b0010)
                with m.Case(Funct.OR):
                    m.d.comb += self.output.alu_op.eq(0b0011)
                with m.Case(Funct.SLT):
                    m.d.comb += self.output.alu_op.eq(0b0100)
                with m.Case(Funct.SLL):
                    m.d.comb += self.output.alu_op.eq(0b0101)
                with m.Case(Funct.SRL):
                    m.d.comb += self.output.alu_op.eq(0b0110)

        with m.Elif(
            (opcode == Opcode.ADDI)
            | (opcode == Opcode.ANDI)
            | (opcode == Opcode.ORI)
            | (opcode == Opcode.SLTI)
            | (opcode == Opcode.LW)
            | (opcode == Opcode.SW)
        ):
            # I???/??/????????????ALU???
            m.d.comb += self.output.alu_src.eq(1)

            imm = instruction[0:16]
            m.d.comb += self.output.imm.eq(imm)

            with m.Switch(opcode):
                with m.Case(Opcode.ADDI):
                    m.d.comb += self.output.alu_op.eq(0b0000)
                    m.d.comb += self.output.write_reg.eq(rt)
                    m.d.comb += self.output.reg_write.eq(1)
                with m.Case(Opcode.ANDI):
                    m.d.comb += self.output.alu_op.eq(0b0010)
                    m.d.comb += self.output.write_reg.eq(rt)
                    m.d.comb += self.output.reg_write.eq(1)
                with m.Case(Opcode.ORI):
                    m.d.comb += self.output.alu_op.eq(0b0011)
                    m.d.comb += self.output.write_reg.eq(rt)
                    m.d.comb += self.output.reg_write.eq(1)
                with m.Case(Opcode.SLTI):
                    m.d.comb += self.output.alu_op.eq(0b0100)
                    m.d.comb += self.output.write_reg.eq(rt)
                    m.d.comb += self.output.reg_write.eq(1)
                with m.Case(Opcode.LW):
                    m.d.comb += self.output.alu_op.eq(0b0000)
                    m.d.comb += self.output.mem_read.eq(1)
                    m.d.comb += self.output.write_reg.eq(rt)
                    m.d.comb += self.output.reg_write.eq(1)
                    m.d.comb += self.output.mem_to_reg.eq(1)
                with m.Case(Opcode.SW):
                    m.d.comb += self.output.alu_op.eq(0b0000)
                    m.d.comb += self.output.mem_write.eq(1)
                    # SW?????

        with m.Elif((opcode == Opcode.BEQ) | (opcode == Opcode.BNE)):
            # I?????????????
            m.d.comb += self.output.alu_src.eq(0)

            imm = instruction[0:16]
            m.d.comb += self.output.imm.eq(imm)

            # ?????????
            with m.Switch(opcode):
                with m.Case(Opcode.BEQ):
                    m.d.comb += self.output.alu_op.eq(0b0001)
                with m.Case(Opcode.BNE):
                    m.d.comb += self.output.alu_op.eq(0b0001)

        with m.Elif(opcode == Opcode.JAL):
            # JAL????$31????????PC+4
            m.d.comb += self.output.write_reg.eq(31)
            m.d.comb += self.output.reg_write.eq(1)
            m.d.comb += self.output.mem_to_reg.eq(0)

        return m


class ID_EX_Pipeline_Reg(wiring.Component):
    input: In(IDOutput())
    output: Out(IDOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.output.eq(self.input)
        return m


class EX_Stage(wiring.Component):
    input: In(IDOutput())
    output: Out(EXOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # ???ALU?????
        m.submodules.alu = alu = ALU()

        # ALU ????????????????
        alu_b = Signal(signed(32))
        with m.If(self.input.alu_src == 1):
            # ???????
            imm_ext = Cat(self.input.imm, Repl(self.input.imm[15], 16))
            m.d.comb += alu_b.eq(imm_ext)
        with m.Else():
            m.d.comb += alu_b.eq(self.input.rt_data)

        # ??ALU??
        m.d.comb += alu.a.eq(self.input.rs_data)
        m.d.comb += alu.b.eq(alu_b)
        m.d.comb += alu.op.eq(self.input.alu_op)

        # ??ALU???????
        m.d.comb += self.output.alu_result.eq(alu.result)

        # ??????
        m.d.comb += self.output.mem_write_data.eq(self.input.rt_data)
        m.d.comb += self.output.mem_read.eq(self.input.mem_read)
        m.d.comb += self.output.mem_write.eq(self.input.mem_write)
        m.d.comb += self.output.write_reg.eq(self.input.write_reg)
        m.d.comb += self.output.reg_write.eq(self.input.reg_write)
        m.d.comb += self.output.mem_to_reg.eq(self.input.mem_to_reg)

        return m

class EX_MEM_Pipeline_Reg(wiring.Component):
    input: In(EXOutput())
    output: Out(EXOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.output.eq(self.input)
        return m

class MEM_Stage(wiring.Component):
    input: In(EXOutput())

    # ??????
    mem_addr_out: Out(32)
    mem_write_data_out: Out(32)
    mem_write_en_out: Out(1)
    mem_read_data_in: In(32)

    # ???????
    output: Out(MEMOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # ???????
        m.d.comb += self.mem_addr_out.eq(self.input.alu_result)
        m.d.comb += self.output.alu_result.eq(self.input.alu_result)
        m.d.comb += self.output.write_reg.eq(self.input.write_reg)
        m.d.comb += self.output.reg_write.eq(self.input.reg_write)
        m.d.comb += self.output.mem_to_reg.eq(self.input.mem_to_reg)

        # ??????
        with m.If(self.input.mem_write == 1):
            m.d.comb += self.mem_write_data_out.eq(self.input.mem_write_data)
            m.d.comb += self.mem_write_en_out.eq(1)
            m.d.comb += self.output.mem_data.eq(0)  # ??????????
        with m.Elif(self.input.mem_read == 1):
            m.d.comb += self.mem_write_en_out.eq(0)
            m.d.comb += self.output.mem_data.eq(self.mem_read_data_in)
            m.d.comb += self.mem_write_data_out.eq(0)  # ??????????
        with m.Else():
            # ??????
            m.d.comb += self.mem_write_en_out.eq(0)
            m.d.comb += self.output.mem_data.eq(0)
            m.d.comb += self.mem_write_data_out.eq(0)

        return m


class MEM_WB_Pipeline_Reg(wiring.Component):
    input: In(MEMOutput())
    output: Out(MEMOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.output.eq(self.input)
        return m

class WB_Stage(wiring.Component):
    input: In(MEMOutput())
    output: Out(WBOutput())

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.input.mem_to_reg == 1):
            m.d.comb += self.output.write_data.eq(self.input.mem_data)
        with m.Else():
            m.d.comb += self.output.write_data.eq(self.input.alu_result)

        m.d.comb += self.output.write_reg.eq(self.input.write_reg)
        m.d.comb += self.output.reg_write.eq(self.input.reg_write)

        return m

class CPU(wiring.Component):
    # ??????
    imem_addr: Out(32)
    imem_rdata: In(32)

    # ??????
    dmem_addr: Out(32)
    dmem_wdata: Out(32)
    dmem_wen: Out(1)
    dmem_rdata: In(32)

    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # ========== ???????? ==========
        m.submodules.pc = pc = PC()
        m.submodules.regfile = regfile = RegFile()

        m.submodules.if_stage = if_stage = IF_Stage()
        m.submodules.if_id_reg = if_id_reg = IF_ID_Pipeline_Reg()
        m.submodules.id_stage = id_stage = ID_Stage()
        m.submodules.id_ex_reg = id_ex_reg = ID_EX_Pipeline_Reg()
        m.submodules.ex_stage = ex_stage = EX_Stage()
        m.submodules.ex_mem_reg = ex_mem_reg = EX_MEM_Pipeline_Reg()
        m.submodules.mem_stage = mem_stage = MEM_Stage()
        m.submodules.mem_wb_reg = mem_wb_reg = MEM_WB_Pipeline_Reg()
        m.submodules.wb_stage = wb_stage = WB_Stage()

        # ========== ?? connect ??????? ==========
        connect(m, if_stage.output, if_id_reg.input)
        connect(m, if_id_reg.output, id_stage.input)
        connect(m, id_stage.output, id_ex_reg.input)
        connect(m, id_ex_reg.output, ex_stage.input)
        connect(m, ex_stage.output, ex_mem_reg.input)
        connect(m, ex_mem_reg.output, mem_stage.input)
        connect(m, mem_stage.output, mem_wb_reg.input)
        connect(m, mem_wb_reg.output, wb_stage.input)

        # ========== PC ?? ==========
        m.d.comb += if_stage.pc_in.eq(pc.addr_out)
        # PC ???????????????????
        with m.If(id_stage.pc_en_out):
            m.d.comb += pc.pc_in.eq(id_stage.output.pc)
        with m.Else():
            m.d.comb += pc.pc_in.eq(pc.pc_out)  # ??

        # ========== ??????? ==========
        # ????ID???
        m.d.comb += [
            regfile.rd_addr0.eq(id_stage.output.rs),
            regfile.rd_addr1.eq(id_stage.output.rt),
            id_stage.rs_data_in.eq(regfile.rd_data0),
            id_stage.rt_data_in.eq(regfile.rd_data1),
        ]

        # ????WB???
        m.d.comb += [
            regfile.wr_addr.eq(wb_stage.output.write_reg),
            regfile.wr_data.eq(wb_stage.output.write_data),
            regfile.wr_en.eq(wb_stage.output.reg_write),
        ]

        # ========== ?????? ==========
        m.d.comb += [
            self.imem_addr.eq(if_stage.memory_addr),
            if_stage.memory_read.eq(self.imem_rdata),
        ]

        # ========== ?????? ==========
        m.d.comb += [
            self.dmem_addr.eq(mem_stage.mem_addr_out),
            self.dmem_wdata.eq(mem_stage.mem_write_data_out),
            self.dmem_wen.eq(mem_stage.mem_write_en_out),
            mem_stage.mem_read_data_in.eq(self.dmem_rdata),
        ]

        return m

