from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Tuple

from mips.core.cpu import Opcode, Funct

WORD_BYTES = 4
MASK32 = (1 << 32) - 1


def encode_r_type(opcode: int, rs: int, rt: int, rd: int, shamt: int, funct: int) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((rs & 0x1F) << 21)
        | ((rt & 0x1F) << 16)
        | ((rd & 0x1F) << 11)
        | ((shamt & 0x1F) << 6)
        | (funct & 0x3F)
    )


def encode_i_type(opcode: int, rs: int, rt: int, imm: int) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((rs & 0x1F) << 21)
        | ((rt & 0x1F) << 16)
        | (imm & 0xFFFF)
    )


def encode_j_type(opcode: int, addr: int) -> int:
    return ((opcode & 0x3F) << 26) | (addr & 0x3FFFFFF)


def nop() -> int:
    return 0


@dataclass
class ProgramArtifact:
    words: List[int]
    done_pc: int


class ProgramBuilder:
    def __init__(self):
        self.instructions: List[int] = []
        self.labels: Dict[str, int] = {}
        self.patches: List[Tuple[str, ...]] = []
        self._finalized = False

    def _assert_mutable(self) -> None:
        if self._finalized:
            raise RuntimeError("Program already finalized")

    def label(self, name: str) -> None:
        self._assert_mutable()
        if name in self.labels:
            raise ValueError(f"Label '{name}' already defined")
        self.labels[name] = len(self.instructions)

    def _emit(self, word: int) -> None:
        self.instructions.append(word & MASK32)

    def emit_r_type(self, opcode: int, rs: int, rt: int, rd: int, shamt: int, funct: int) -> None:
        self._assert_mutable()
        self._emit(encode_r_type(opcode, rs, rt, rd, shamt, funct))

    def emit_i_type(self, opcode: int, rs: int, rt: int, imm: int) -> None:
        self._assert_mutable()
        self._emit(encode_i_type(opcode, rs, rt, imm))

    def emit_branch(self, opcode: int, rs: int, rt: int, label: str) -> None:
        self._assert_mutable()
        idx = len(self.instructions)
        self.instructions.append(nop())
        self.patches.append(("branch", idx, opcode, rs, rt, label))

    def emit_jump(self, opcode: int, label: str) -> None:
        self._assert_mutable()
        idx = len(self.instructions)
        self.instructions.append(nop())
        self.patches.append(("jump", idx, opcode, label))

    def finalize(self) -> None:
        if self._finalized:
            return
        for patch in self.patches:
            kind = patch[0]
            if kind == "branch":
                _, idx, opcode, rs, rt, label = patch
                if label not in self.labels:
                    raise ValueError(f"Undefined label '{label}'")
                target = self.labels[label]
                offset = target - (idx + 1)
                self.instructions[idx] = encode_i_type(opcode, rs, rt, offset)
            else:
                _, idx, opcode, label = patch
                if label not in self.labels:
                    raise ValueError(f"Undefined label '{label}'")
                target = self.labels[label]
                self.instructions[idx] = encode_j_type(opcode, target)
        self._finalized = True

    def program(self) -> List[int]:
        self.finalize()
        return list(self.instructions)

    def address_of(self, label: str) -> int:
        if label not in self.labels:
            raise ValueError(f"Undefined label '{label}'")
        return self.labels[label]


def build_hamming_program() -> ProgramArtifact:
    b = ProgramBuilder()

    def add(rd: int, rs: int, rt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, rs, rt, rd, 0, Funct.ADD)

    def addi(rt: int, rs: int, imm: int) -> None:
        b.emit_i_type(Opcode.ADDI, rs, rt, imm)

    def ori(rt: int, rs: int, imm: int) -> None:
        b.emit_i_type(Opcode.ORI, rs, rt, imm)

    def andi(rt: int, rs: int, imm: int) -> None:
        b.emit_i_type(Opcode.ANDI, rs, rt, imm)

    def sll(rd: int, rt: int, shamt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, 0, rt, rd, shamt, Funct.SLL)

    def srl(rd: int, rt: int, shamt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, 0, rt, rd, shamt, Funct.SRL)

    def band(rd: int, rs: int, rt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, rs, rt, rd, 0, Funct.AND)

    def bor(rd: int, rs: int, rt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, rs, rt, rd, 0, Funct.OR)

    def sub(rd: int, rs: int, rt: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, rs, rt, rd, 0, Funct.SUB)

    def jr(rs: int) -> None:
        b.emit_r_type(Opcode.R_TYPE, rs, 0, 0, 0, Funct.JR)

    def sw(rt: int, base: int, offset: int) -> None:
        b.emit_i_type(Opcode.SW, base, rt, offset)

    def beq(rs: int, rt: int, label: str) -> None:
        b.emit_branch(Opcode.BEQ, rs, rt, label)

    def j(label: str) -> None:
        b.emit_jump(Opcode.J, label)

    def jal(label: str) -> None:
        b.emit_jump(Opcode.JAL, label)

    b.label("main")
    addi(23, 0, -1)
    sll(23, 23, 16)

    add(4, 0, 0)
    jal("run_test")

    addi(4, 0, 1)
    jal("run_test")

    ori(4, 0, 0x0017)
    jal("run_test")

    b.label("end_loop")
    j("end_loop")

    b.label("run_test")
    add(20, 31, 0)
    add(17, 0, 0)
    add(16, 4, 0)

    ori(8, 0, 0x5555)
    band(9, 16, 8)
    add(2, 0, 0)
    addi(10, 0, 16)

    b.label("s1_loop")
    beq(10, 0, "s1_done")
    andi(11, 9, 1)
    add(2, 2, 11)
    srl(9, 9, 1)
    addi(10, 10, -1)
    j("s1_loop")

    b.label("s1_done")
    andi(2, 2, 1)
    bor(17, 17, 2)

    ori(8, 0, 0x6666)
    band(9, 16, 8)
    add(2, 0, 0)
    addi(10, 0, 16)

    b.label("s2_loop")
    beq(10, 0, "s2_done")
    andi(11, 9, 1)
    add(2, 2, 11)
    srl(9, 9, 1)
    addi(10, 10, -1)
    j("s2_loop")

    b.label("s2_done")
    andi(2, 2, 1)
    sll(2, 2, 1)
    bor(17, 17, 2)

    ori(8, 0, 0x7878)
    band(9, 16, 8)
    add(2, 0, 0)
    addi(10, 0, 16)

    b.label("s4_loop")
    beq(10, 0, "s4_done")
    andi(11, 9, 1)
    add(2, 2, 11)
    srl(9, 9, 1)
    addi(10, 10, -1)
    j("s4_loop")

    b.label("s4_done")
    andi(2, 2, 1)
    sll(2, 2, 2)
    bor(17, 17, 2)

    ori(8, 0, 0x7F80)
    band(9, 16, 8)
    add(2, 0, 0)
    addi(10, 0, 16)

    b.label("s8_loop")
    beq(10, 0, "s8_done")
    andi(11, 9, 1)
    add(2, 2, 11)
    srl(9, 9, 1)
    addi(10, 10, -1)
    j("s8_loop")

    b.label("s8_done")
    andi(2, 2, 1)
    sll(2, 2, 3)
    bor(17, 17, 2)

    beq(17, 0, "is_right")

    sw(17, 23, 4)
    addi(10, 17, -1)
    addi(11, 0, 1)
    add(12, 0, 0)

    b.label("fix_shift")
    beq(12, 10, "fix_now")
    sll(11, 11, 1)
    addi(12, 12, 1)
    j("fix_shift")

    b.label("fix_now")
    bor(13, 16, 11)
    band(14, 16, 11)
    addi(15, 0, -1)
    sub(14, 15, 14)
    band(16, 13, 14)

    sw(16, 23, 8)
    j("test_done")

    b.label("is_right")
    ori(9, 0, 0x5247)
    sll(9, 9, 16)
    ori(10, 0, 0x4854)
    bor(9, 9, 10)
    sw(9, 23, 4)
    sw(16, 23, 8)

    b.label("test_done")
    add(31, 20, 0)
    jr(31)

    words = b.program()
    done_pc = b.address_of("end_loop") * WORD_BYTES
    return ProgramArtifact(words=words, done_pc=done_pc)


__all__ = ["ProgramArtifact", "build_hamming_program"]
