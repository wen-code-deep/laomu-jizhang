from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from jb_declarative_formatters.type_name_template import TypeNameTemplate
from jb_declarative_formatters.type_viz_expression import get_custom_view_spec_id_by_name, TypeVizExpression, \
    TypeVizCondition
from jb_declarative_formatters.type_viz_intrinsic import IntrinsicsScope
from jb_declarative_formatters.type_viz_summary import TypeVizSummary
from lldb.formatters.Logger import Logger


class TypeVizName(object):
    def __init__(self, type_name: str, type_name_template: TypeNameTemplate):
        self.type_name: str = type_name
        self.type_name_template: TypeNameTemplate = type_name_template

    @property
    def has_wildcard(self) -> bool:
        return self.type_name_template.has_wildcard

    def __str__(self) -> str:
        return self.type_name


class TypeVizSmartPointer(object):
    class Usage(Enum):
        Minimal = auto()
        Indexable = auto()
        # There is one more usage: 'Full'.
        # The 'Full' usage means that the smart pointer contains a conversion operator to the underlying pointer.
        # LLDB is unable to declare the conversion operator properly. TODO: It can be fixed in LLDB.
        # Neither 'stl.natvis' nor 'Unreal.natvis' contains the 'Full' usage; therefore, consider 'Full' as 'Indexed'.

    def __init__(self, expression: TypeVizExpression, usage: Usage):
        self.expression = expression
        self.usage = usage


class TypeVizStringView(object):
    def __init__(self, expression: TypeVizExpression, condition: TypeVizCondition):
        self.expression = expression
        self.condition = condition


class AbstractTypeViz:
    def __init__(self,
                 global_intrinsics: IntrinsicsScope,
                 type_intrinsics: IntrinsicsScope):
        self.summaries: list[TypeVizSummary] = []
        self.item_providers = None
        self.global_lazy_intrinsics = global_intrinsics.retain_only_lazy()
        self.global_all_intrinsics = global_intrinsics
        self.type_lazy_intrinsics = type_intrinsics.retain_only_lazy()
        self.type_all_intrinsics = type_intrinsics
        self.hide_raw_view: bool = False
        self.string_views: list[TypeVizStringView] = []


class TypeViz(AbstractTypeViz):
    def __init__(self,
                 type_viz_names: list[TypeVizName],
                 is_inheritable: bool,
                 include_view: str,
                 exclude_view: str,
                 priority: int,
                 global_intrinsics: IntrinsicsScope,
                 type_intrinsics: IntrinsicsScope,
                 logger: Logger = None):
        super().__init__(global_intrinsics, type_intrinsics)

        self.logger = logger  # TODO: or stub

        self.type_viz_names = type_viz_names
        self.is_inheritable = is_inheritable
        self.include_view = include_view
        self.include_view_id = get_custom_view_spec_id_by_name(include_view)
        self.exclude_view = exclude_view
        self.exclude_view_id = get_custom_view_spec_id_by_name(exclude_view)
        self.priority = priority
        self.smart_pointer: Optional[TypeVizSmartPointer] = None


class TypeVizSyntheticItem(AbstractTypeViz):
    def __init__(self,
                 name: str,
                 add_watch_expr: str | None,
                 summaries: list[TypeVizSummary],
                 item_providers: list | None,
                 string_views: list[TypeVizStringView],
                 global_intrinsics: IntrinsicsScope,
                 type_intrinsics: IntrinsicsScope):
        super().__init__(global_intrinsics, type_intrinsics)
        self.name = name
        self.add_watch_expr = add_watch_expr
        self.summaries = summaries
        self.item_providers = item_providers
        # VS never shows "Raw View" for Synthetic items
        self.hide_raw_view = True
        self.string_views = string_views
