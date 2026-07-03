from __future__ import annotations

from typing import NamedTuple, Iterable

import lldb


class AddressRange(NamedTuple):
    start: int
    end: int

    @staticmethod
    def from_line_entry(target: lldb.SBTarget, line_entry: lldb.SBLineEntry) -> AddressRange | None:
        if not line_entry.IsValid():
            return None
        return AddressRange(line_entry.GetStartAddress().GetLoadAddress(target), line_entry.GetEndAddress().GetLoadAddress(target))

    @staticmethod
    def block_ranges(target: lldb.SBTarget, block: lldb.SBBlock) -> Iterable[AddressRange]:
        for range_index in range(block.GetNumRanges()):
            start = block.GetRangeStartAddress(range_index).GetLoadAddress(target)
            end = block.GetRangeEndAddress(range_index).GetLoadAddress(target)
            if start and end:
                yield AddressRange(start, end)

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end

    def contains_range(self, other: AddressRange) -> bool:
        return self.start <= other.start and other.end <= self.end

    def __str__(self) -> str:
        # For debugging
        return f"[0x{self.start:x}, 0x{self.end:x})"
