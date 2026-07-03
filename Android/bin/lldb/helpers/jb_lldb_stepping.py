from __future__ import annotations

import lldb

from stepping.jb_lldb_abstract_thread_plan_with_lazy_context import AbstractThreadPlanWithLazyContext, with_reset_context
from stepping.jb_lldb_address_range import AddressRange
from stepping.jb_lldb_delegate_step import DelegateStep
from stepping.jb_lldb_instructions_reader import InstructionsReader
from stepping.jb_lldb_line_spec import LineSpec

"""
Why do we need custom stepping? This is kind of a mystery.

Here are the known reasons:
- MSVC C++ exceptions: The NonLocalGotoDispatchGuardThreadPlan and NonLocalGotoReturnGuardThreadPlan plans handles C++ exception.
- Incremental linkage: For some reason, the native LLDB StepInto cannot step into a function if the binary is built with
                       the incremental linkage (see https://youtrack.jetbrains.com/issue/CPP-36647).
- Magic line numbers: The SpecialLinesGuardThreadPlan plan handles the magic line numbers
                      (see llvm-project/llvm/include/llvm/DebugInfo/CodeView/Line.h:24).

There may be other unknown use cases. If you find any, please add them to the list!
"""


def get_full_step_name(step_name: str) -> str:
    return f"{__name__}.{step_name}"


class StepThroughInstruction(AbstractThreadPlanWithLazyContext):
    def __init__(self, thread_plan, internal_dict):
        super().__init__(thread_plan, internal_dict)
        self.start_pc = self.top_frame.GetPC()

    def explains_stop(self, event: lldb.SBEvent) -> bool:
        return self.thread.GetStopReason() == lldb.eStopReasonTrace

    @with_reset_context
    def should_stop(self, event: lldb.SBEvent) -> bool:
        if self.top_frame.GetPC() == self.start_pc:
            return False

        self.original_thread_plan.SetPlanComplete(True)
        return True

    # noinspection PyMethodMayBeStatic
    def should_step(self) -> bool:
        return True


class StepOverInstruction(DelegateStep):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, True, internal_dict)

        self.instruction_reader = InstructionsReader(self.target)
        self.start_pc_address: lldb.SBAddress = self.top_frame.GetPCAddress()

        self.run_to_address: lldb.SBAddress | None = None
        self.sp_limit = None
        self.cfa = None
        instruction = self.instruction_reader.read_instruction(self.start_pc_address)
        if instruction is not None and instruction.IsCall():
            self.run_to_address = self.start_pc_address
            self.run_to_address.OffsetAddress(instruction.GetByteSize())
            self.sp_limit = self.top_frame.GetSP()
            self.cfa = self.top_frame.GetCFA()

        self.enable_thread_plan()

    @with_reset_context
    def queue_next_thread_plan(self) -> lldb.SBThreadPlan | None:
        next_instruction_address: lldb.SBAddress = self.top_frame.GetPCAddress()

        if self.run_to_address is not None:
            if next_instruction_address == self.run_to_address:
                if self.top_frame.GetSP() >= self.sp_limit or self.top_frame.GetCFA() == self.cfa:
                    return None

                return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepThroughInstruction'))

            return self.original_thread_plan.QueueThreadPlanForRunToAddress(self.run_to_address)

        if next_instruction_address != self.start_pc_address:
            return None

        return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepThroughInstruction'))


class StepLineBase(DelegateStep):
    def __init__(self, thread_plan: lldb.SBThreadPlan, force: bool, internal_dict):
        super().__init__(thread_plan, True, internal_dict)

        self.instruction_reader = InstructionsReader(self.target)
        self.force = force
        self.sp_limit = self.top_frame.GetSP()
        self.start_line = LineSpec.from_line_entry(self.current_line_entry)

    @with_reset_context
    def queue_next_thread_plan(self) -> lldb.SBThreadPlan | None:
        current_line = LineSpec.from_line_entry(self.current_line_entry)

        if current_line is None:
            return self.get_plan_for_unknown_line()

        if current_line != self.start_line:
            return self.get_plan_for_new_line()

        self.update_sp_limit()
        return self.get_skip_instructions_plan()

    def update_sp_limit(self):
        sp = self.top_frame.GetSP()
        if sp > self.sp_limit:
            self.sp_limit = sp

    def get_plan_for_unknown_line(self) -> lldb.SBThreadPlan | None:
        if self.force:
            return None

        sp = self.top_frame.GetSP()
        if sp > self.sp_limit:
            # Skip top frame, go to nearest line frame with valid line entry
            for i in range(1, self.thread.GetNumFrames()):
                frame: lldb.SBFrame = self.thread.GetFrameAtIndex(i)
                if frame.GetLineEntry().IsValid():
                    return self.original_thread_plan.QueueThreadPlanForRunToAddress(frame.GetPCAddress())

            return None

        return self.get_skip_instructions_plan(True)

    def get_plan_for_new_line(self) -> lldb.SBThreadPlan | None:
        return None

    def get_skip_instructions_plan(self, current_line_is_unknown: bool = False) -> lldb.SBThreadPlan:
        next_instruction_address: lldb.SBAddress = self.top_frame.GetPCAddress()
        next_interesting_instruction_address = self.find_next_interesting_instruction_address(next_instruction_address)

        if next_interesting_instruction_address and next_instruction_address != next_interesting_instruction_address:
            # Skip the next instructions as much as possible
            return self.original_thread_plan.QueueThreadPlanForRunToAddress(next_interesting_instruction_address)

        next_instruction = self.instruction_reader.read_instruction(next_instruction_address)
        if next_instruction and not next_instruction.IsCall():
            # This is a kind of optimization, since the next instruction is not a call, there is no need to perform a step over
            return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepThroughInstruction'))

        if current_line_is_unknown:
            # Force a step over because we don't want to step into an unknown line
            return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepOverInstruction'))

        return self.get_step_next_instruction_plan()

    def find_next_interesting_instruction_address(self, start_from: lldb.SBAddress) -> lldb.SBAddress | None:
        for instruction in self.instruction_reader.read_instructions(start_from):
            instruction_address: lldb.SBAddress = instruction.GetAddress()
            if instruction.DoesBranch():
                return instruction_address

            if self.is_interesting_instruction_address(instruction_address):
                return instruction_address

        return None

    def is_interesting_instruction_address(self, instruction_address: lldb.SBAddress) -> bool:
        line_entry: lldb.SBLineEntry = instruction_address.GetLineEntry()
        instruction_line = LineSpec.from_line_entry(line_entry)
        return instruction_line != self.start_line

    def get_step_next_instruction_plan(self) -> lldb.SBThreadPlan:
        return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepThroughInstruction'))


class StepOverLineBase(StepLineBase):
    def __init__(self, thread_plan: lldb.SBThreadPlan, force: bool, internal_dict):
        super().__init__(thread_plan, force, internal_dict)

        self.start_line_address_range = AddressRange.from_line_entry(self.target, self.current_line_entry)
        self.start_block_address_ranges = {r for r in AddressRange.block_ranges(self.target, self.top_frame.GetBlock())}

    def get_plan_for_new_line(self) -> lldb.SBThreadPlan | None:
        if self.start_line_address_range is not None:
            next_instruction_address = self.top_frame.GetPC()
            # Check whether the next instruction is on the line where the stepping started
            if self.start_line_address_range.contains(next_instruction_address):
                self.update_sp_limit()
                return self.get_skip_instructions_plan()

        if not self.start_block_address_ranges:
            return None

        if not self.top_frame.IsInlined():
            return None

        plan_for_top_frame = self.get_plan_for_skipping_inlined_frame(self.top_frame)
        if plan_for_top_frame is not None:
            return plan_for_top_frame

        # This is kind of optimization, do not merge with top_frame checking
        for i in range(1, self.thread.GetNumFrames()):
            inlined_frame: lldb.SBFrame = self.thread.GetFrameAtIndex(i)
            if not inlined_frame.IsInlined():
                break

            plan_for_inlined_frame = self.get_plan_for_skipping_inlined_frame(inlined_frame)
            if plan_for_inlined_frame is not None:
                return plan_for_inlined_frame

        return None

    def get_plan_for_skipping_inlined_frame(self, inlined_frame: lldb.SBFrame) -> lldb.SBThreadPlan | None:
        inlined_into_starting = False
        for inlined_range in AddressRange.block_ranges(self.target, inlined_frame.GetBlock()):
            # Stopped in the same function
            if inlined_range in self.start_block_address_ranges:
                return None

            # Stopped in the function which is inlined into the starting block
            inlined_into_starting = inlined_into_starting or \
                                    any(r.contains_range(inlined_range) for r in self.start_block_address_ranges)

        if inlined_into_starting:
            self.update_sp_limit()
            return self.get_skip_instructions_plan()

        return None

    def is_interesting_instruction_address(self, instruction_address: lldb.SBAddress) -> bool:
        if self.start_line_address_range is not None:
            # This check optimizes the number of implicit steps to addresses
            # where we won't stop because they are in inlined function calls
            instruction_load_address = instruction_address.GetLoadAddress(self.target)
            if self.start_line_address_range.contains(instruction_load_address):
                return False

        return super().is_interesting_instruction_address(instruction_address)

    def get_step_next_instruction_plan(self) -> lldb.SBThreadPlan:
        return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepOverInstruction'))


class StepInLine(StepLineBase):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, False, internal_dict)
        self.enable_thread_plan()


class StepInLineForce(StepLineBase):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, True, internal_dict)
        self.enable_thread_plan()


class StepOverLine(StepOverLineBase):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, False, internal_dict)
        self.enable_thread_plan()


class StepOverLineForce(StepOverLineBase):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, True, internal_dict)
        self.enable_thread_plan()


class SpecialLinesGuardThreadPlan(AbstractThreadPlanWithLazyContext):
    # See llvm-project/llvm/include/llvm/DebugInfo/CodeView/Line.h:24
    ASI = 0xfeefee  # Always StepInto Line Number
    NSI = 0xf00f00  # Never StepInto Line Number

    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, internal_dict)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def explains_stop(self, event: lldb.SBEvent) -> bool:
        return False

    @with_reset_context
    def should_stop(self, event: lldb.SBEvent) -> bool:
        # GetLine() of invalid line_entry returns 0
        line: int = self.current_line_entry.GetLine()

        if line == self.ASI:
            self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepInLine'))
            return False

        if line == self.NSI:
            self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepOverLine'))
            return False

        self.original_thread_plan.SetPlanComplete(True)
        return True

    # noinspection PyMethodMayBeStatic
    def should_step(self) -> bool:
        return False


class NonLocalGotoReturnGuardThreadPlan(AbstractThreadPlanWithLazyContext):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, internal_dict)

        self.addresses = []
        for sym_ctx in self.target.FindSymbols(self.get_nlg_return_symbol_name()):
            bp_address = sym_ctx.GetSymbol().GetStartAddress().GetLoadAddress(self.target)
            if bp_address == lldb.LLDB_INVALID_ADDRESS:
                continue
            self.addresses.append(bp_address)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def explains_stop(self, event: lldb.SBEvent) -> bool:
        return False

    @with_reset_context
    def should_stop(self, event: lldb.SBEvent) -> bool:
        if self.top_frame.GetPC() in self.addresses:
            return False

        self.original_thread_plan.SetPlanComplete(True)
        return True

    # noinspection PyMethodMayBeStatic
    def should_step(self) -> bool:
        return False

    @staticmethod
    def get_nlg_return_symbol_name() -> str:
        return '_NLG_Return'


class NonLocalGotoDispatchGuardThreadPlan(AbstractThreadPlanWithLazyContext):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, internal_dict)

        self.is_x64 = self.process.GetAddressByteSize() == 8
        self.sp_limit = self.top_frame.GetSP()

        self.bp_addresses = []
        self.bp_ids = []
        for sym_ctx in self.target.FindSymbols(self.get_nlg_dispatch_symbol_name()):
            bp_address = sym_ctx.GetSymbol().GetStartAddress().GetLoadAddress(self.target)
            if bp_address == lldb.LLDB_INVALID_ADDRESS:
                continue
            self.bp_addresses.append(bp_address)

            bp: lldb.SBBreakpoint = self.target.BreakpointCreateByAddress(bp_address)
            bp.SetThreadID(self.thread.GetThreadID())
            self.bp_ids.append(bp.GetID())

    @with_reset_context
    def explains_stop(self, event: lldb.SBEvent) -> bool:
        return self.top_frame.GetPC() in self.bp_addresses

    @with_reset_context
    def should_stop(self, event: lldb.SBEvent) -> bool:
        if self.top_frame.GetPC() not in self.bp_addresses:
            self.original_thread_plan.SetPlanComplete(True)
            return True

        nlg_frame_register_value = self.get_register_value(self.get_nlg_frame_register_name())
        if nlg_frame_register_value is None or nlg_frame_register_value < self.sp_limit:
            return False

        nlg_address_register_value = self.get_register_value(self.get_nlg_address_register_name())
        if nlg_address_register_value is None:
            return False

        nlg_address: lldb.SBAddress = self.target.ResolveLoadAddress(nlg_address_register_value)
        if not nlg_address:
            return False

        if not nlg_address.GetLineEntry().IsValid():
            return False

        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoDispatchGuardThreadPlan'),
                                                                 lldb.SBError(),
                                                                 True)
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoReturnGuardThreadPlan'))
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('SpecialLinesGuardThreadPlan'))
        self.original_thread_plan.QueueThreadPlanForRunToAddress(nlg_address)

        return False

    # noinspection PyMethodMayBeStatic
    def should_step(self) -> bool:
        return False

    def will_pop(self) -> bool:
        for bp_id in self.bp_ids:
            self.target.BreakpointDelete(bp_id)

        return super().will_pop()

    def get_nlg_dispatch_symbol_name(self) -> str:
        return '__NLG_Dispatch2' if self.is_x64 else '_NLG_Dispatch2'

    def get_nlg_frame_register_name(self) -> str:
        return 'rdx' if self.is_x64 else 'ebp'

    def get_nlg_address_register_name(self) -> str:
        return 'rcx' if self.is_x64 else 'eax'

    def get_register_value(self, register_name: str) -> int | None:
        register: lldb.SBValue = self.top_frame.FindRegister(register_name)
        if not register.IsValid():
            return None

        # The value can be synthetic (see the 'type synthetic add' command).
        # However, the synthetic value may return an incorrect register value, so get the non-synthetic one.
        register_non_synth: lldb.SBValue = register.GetNonSyntheticValue()
        return register_non_synth.GetValueAsUnsigned()


class StepIn(DelegateStep):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, False, internal_dict)
        self.enable_thread_plan()

    @with_reset_context
    def queue_next_thread_plan(self) -> lldb.SBThreadPlan:
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoDispatchGuardThreadPlan'))
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoReturnGuardThreadPlan'))

        if not self.current_line_entry.IsValid():
            return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepThroughInstruction'))

        debugger: lldb.SBDebugger = self.target.GetDebugger()
        avoid_no_debug = debugger.GetInternalVariableValue('target.process.thread.step-in-avoid-nodebug',
                                                           debugger.GetInstanceName()).GetStringAtIndex(0)
        if avoid_no_debug == 'false':
            return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepInLineForce'))

        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('SpecialLinesGuardThreadPlan'))
        return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepInLine'))


class StepOver(DelegateStep):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, False, internal_dict)
        self.enable_thread_plan()

    @with_reset_context
    def queue_next_thread_plan(self) -> lldb.SBThreadPlan:
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoDispatchGuardThreadPlan'))
        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('NonLocalGotoReturnGuardThreadPlan'))

        if not self.current_line_entry.IsValid():
            return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepOverInstruction'))

        self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('SpecialLinesGuardThreadPlan'))
        return self.original_thread_plan.QueueThreadPlanForStepScripted(get_full_step_name('StepOverLine'))
