from __future__ import annotations

import lldb


class AbstractScriptedThreadPlan:
    """
    A Thread Plan represents a logical step or action that the debugger wants a thread to execute. Examples include:
    - Single-stepping over an instruction
    - Running until a breakpoint is hit
    - Running until a specific condition is met

    When you debug a program, many thread plans may be stacked on a single thread, each with specific objectives,
    such as finishing a function, reaching a breakpoint, or satisfying a custom condition.

    https://lldb.llvm.org/python_api/lldb.plugins.scripted_thread_plan.ScriptedThreadPlan.html
    """

    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        return

    def explains_stop(self, event: lldb.SBEvent) -> bool:
        """
        Determine if the current thread plan is responsible for the process stop.

        When a process or thread stops (e.g., due to a breakpoint, an exception, or another event),
        LLDB doesn't immediately know which action or plan caused the stop. If multiple thread plans are active on a thread,
        LLDB will go through each one - from the most recent (youngest) to the oldest,
        to see if any of them "explains" or claims responsibility for the stop.

        In a complex debugging session, multiple thread plans might be layered on a single thread
        (e.g., one plan might be for stepping into a function, while another plan could be for a breakpoint).
        "explains_stop()" helps LLDB understand which specific plan caused the stop by allowing only the relevant plan to claim the stop.

        :param event: The process stop event.
        :return: True if the plan considers the stop to be relevant to its purpose, meaning that it "explains" the stop.
                 Otherwise, it returns False, allowing LLDB to continue down the stack of plans.
                 Defaults to True.
        """
        return True

    def is_stale(self) -> bool:
        """
        Determine if the thread plan is no longer relevant (i.e., "stale") and should be removed from the stack.

        A thread plan can become "stale" when the conditions it depends on change, making it irrelevant. For example:
        - The stack frame it was monitoring is no longer active.
        - Another operation completed or superseded this plan’s intended action.

        :return: True if this thread plan is stale, then LLDB will automatically remove this plan from the thread's plan stack,
                 freeing up resources and removing potential conflicts with other thread plans.
                 Defaults to False.
        """
        return False

    def should_step(self) -> bool:
        """
        Decide if the thread plan should proceed with a single instruction step or continue running until a stop condition is met.

        This method tells LLDB how to execute the plan's instructions:
        - "single instruction step" is useful when you need fine-grained control, such as examining changes instruction by instruction.
        - "continue running until a stop condition" is efficient for moving quickly through code until a significant event occurs.

        :return: If returns True, LLDB will advance the thread by one instruction at a time,
                 otherwise LLDB will allow the thread to run freely until it hits another breakpoint or stop condition.
                 Defaults to True.
        """
        return True

    def should_stop(self, event: lldb.SBEvent) -> bool:
        """
        Determine if the thread plan should stop and return control to the user, or continue with the plan's execution.

        This method is often used when the plan has reached a desired state or completed its objectives.
        You may also call "SetPlanComplete()" within "should_stop()" to mark the plan as complete,
        meaning it has fulfilled its purpose and will be removed from the stack on the next stop.

        :param event: The process stop event.
        :return: If returns True, LLDB will halt and return control to the user,
                 otherwise the plan continues executing according to its logic.
                 Defaults to False.
        """
        return False

    def stop_description(self, stream: lldb.SBStream) -> None:
        """
        Customize the thread plan stop reason when the thread plan is complete.

        :param stream: The stream containing the stop description.
        :return: None
        """
        return None

    def will_pop(self) -> bool:
        """
        This is a non-standard extension, implemented only in our fork of LLDB 9.

        The method is called before the thread plan is removed from the stack.
        It can be used to perform any necessary cleanup or finalization steps.

        :return: Seems to be always True.
        """
        return True
