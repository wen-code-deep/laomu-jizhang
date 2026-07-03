from __future__ import annotations

import lldb

from stepping.jb_lldb_abstract_scripted_thread_plan import AbstractScriptedThreadPlan


class AbstractThreadPlanWithLazyContext(AbstractScriptedThreadPlan):
    def __init__(self, thread_plan: lldb.SBThreadPlan, internal_dict):
        super().__init__(thread_plan, internal_dict)

        self.original_thread_plan = thread_plan

        self._thread: lldb.SBThread | None = None
        self._process: lldb.SBProcess | None = None
        self._target: lldb.SBTarget | None = None
        self._top_frame: lldb.SBFrame | None = None
        self._line_entry: lldb.SBLineEntry | None = None

    def reset_context(self):
        # Do not clear self._thread, self._process, self._target because they don't change during one thread plan
        self._line_entry = None
        if self._top_frame is not None:
            self._top_frame.Clear()
            self._top_frame = None

    @property
    def thread(self) -> lldb.SBThread:
        if self._thread is None:
            self._thread = self.original_thread_plan.GetThread()
        return self._thread

    @property
    def process(self) -> lldb.SBProcess:
        if self._process is None:
            self._process = self.thread.GetProcess()
        return self._process

    @property
    def target(self) -> lldb.SBTarget:
        if self._target is None:
            self._target = self.process.GetTarget()
        return self._target

    @property
    def top_frame(self) -> lldb.SBFrame:
        if self._top_frame is None:
            self._top_frame = self.thread.GetFrameAtIndex(0)
        return self._top_frame

    @property
    def current_line_entry(self) -> lldb.SBLineEntry:
        if self._line_entry is None:
            self._line_entry = self.top_frame.GetLineEntry()
        return self._line_entry

    def will_pop(self) -> bool:
        self.reset_context()

        if self._target is not None:
            self._target.Clear()
            self._target = None

        if self._process is not None:
            self._process.Clear()
            self._process = None

        if self._thread is not None:
            self._thread.Clear()
            self._thread = None

        return True


def with_reset_context(method):
    def wrapper(self: AbstractThreadPlanWithLazyContext, *args, **kwargs):
        self.reset_context()
        return method(self, *args, **kwargs)

    return wrapper
