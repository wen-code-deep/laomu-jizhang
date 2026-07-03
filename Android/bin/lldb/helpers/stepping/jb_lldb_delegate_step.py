from __future__ import annotations

import lldb

from stepping.jb_lldb_abstract_thread_plan_with_lazy_context import AbstractThreadPlanWithLazyContext


class DelegateStep(AbstractThreadPlanWithLazyContext):
    def __init__(self, thread_plan: lldb.SBThreadPlan, composite: bool, internal_dict):
        super().__init__(thread_plan, internal_dict)

        self._composite = composite
        self._active_thread_plan: lldb.SBThreadPlan | None = None

    def enable_thread_plan(self):
        """
        Call this method to activate the delegated thread plan. It must be called only after full initialization.
        """
        self._active_thread_plan = self.queue_next_thread_plan()

    def queue_next_thread_plan(self) -> lldb.SBThreadPlan | None:
        """
        Create and queue the next active thread plan. This thread plan will remain active until it is complete.
        When the active thread plan is complete, there are two options:
            - If the delegate step is composite, create and queue the next active thread plan.
            - If the delegate step is not composite, mark the original thread plan as complete and stop the thread.
        If this method returns None, the original thread plan will be considered as complete and the thread will be stopped.
        """
        return None

    def explains_stop(self, event: lldb.SBEvent) -> bool:
        return self._active_thread_plan is None

    def should_stop(self, event: lldb.SBEvent) -> bool:
        if self._active_thread_plan is not None:
            if not self._active_thread_plan.IsPlanComplete():
                return False

            if self._composite:
                self._active_thread_plan = self.queue_next_thread_plan()
                if self._active_thread_plan is not None:
                    return False

        self.original_thread_plan.SetPlanComplete(True)
        return True

    def should_step(self) -> bool:
        return self._active_thread_plan is None
