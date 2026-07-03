from __future__ import annotations

from typing import Iterable

import lldb


class InstructionsReader:
    FIND_NEAREST_INSTRUCTION_STEP = 16

    def __init__(self, target: lldb.SBTarget):
        self.target = target
        self.instruction_cache: dict[int, lldb.SBInstruction] = {}

    def read_instruction(self, address: lldb.SBAddress) -> lldb.SBInstruction | None:
        load_address = address.GetLoadAddress(self.target)
        cached_instruction = self.instruction_cache.get(load_address)
        if cached_instruction is not None:
            return cached_instruction

        new_instructions = self._load_instructions_to_cache(address, 1)
        return new_instructions[0] if new_instructions else None

    def _load_instructions_to_cache(self, address: lldb.SBAddress, instructions_count: int) -> list[lldb.SBInstruction]:
        instructions: lldb.SBInstructionList = self.target.ReadInstructions(address, instructions_count, 'intel')
        new_instructions: list[lldb.SBInstruction] = []
        for instruction in instructions:
            new_instructions.append(instruction)
            load_address = instruction.GetAddress().GetLoadAddress(self.target)
            self.instruction_cache[load_address] = instruction
        return new_instructions

    @staticmethod
    def _next_instruction_address(instruction: lldb.SBInstruction) -> lldb.SBAddress | None:
        address = instruction.GetAddress()
        if address.OffsetAddress(instruction.GetByteSize()):
            return address
        return None

    def read_instructions(self, address: lldb.SBAddress) -> Iterable[lldb.SBInstruction]:
        while address is not None:
            instruction_address = address.GetLoadAddress(self.target)
            cached_instruction = self.instruction_cache.get(instruction_address)
            if cached_instruction is None:
                break
            yield cached_instruction
            address = self._next_instruction_address(cached_instruction)

        while address is not None:
            new_instructions = self._load_instructions_to_cache(address, self.FIND_NEAREST_INSTRUCTION_STEP)
            if not new_instructions:
                break
            yield from new_instructions
            address = self._next_instruction_address(new_instructions[-1])
