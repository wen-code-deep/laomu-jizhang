from __future__ import annotations

from typing import NamedTuple

import lldb


class LineSpec(NamedTuple):
    file_spec: lldb.SBFileSpec
    line: int

    @staticmethod
    def from_line_entry(line_entry: lldb.SBLineEntry) -> LineSpec | None:
        if not line_entry.IsValid():
            return None
        return LineSpec(line_entry.GetFileSpec(), line_entry.GetLine())

    def __str__(self) -> str:
        # For debugging
        return f"{self.file_spec.GetFilename()}:{self.line}"
