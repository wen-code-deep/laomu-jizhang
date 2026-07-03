from __future__ import annotations

from typing import Optional, List, Sequence

import lldb
from jb_declarative_formatters.parsers.cpp_parser import CppParser
from jb_declarative_formatters.type_viz_generated_method import GeneratedMethod
from renderers.jb_lldb_logging_manager import RENDER_LOG


def prepare_default_lldb_expression_options():
    options = lldb.SBExpressionOptions()
    options.SetSuppressPersistentResult(True)
    options.SetFetchDynamicValue(lldb.eDynamicDontRunTarget)
    return options


def resolve_type_wildcards(expression: str, type_wildcards: Sequence[str]) -> str:
    resolved_expression, all_resolved = CppParser.resolve_wildcards(expression, type_wildcards)
    if not all_resolved:
        RENDER_LOG.warning(f"There are unresolved wildcards left in the expression '%s'", resolved_expression)
    return resolved_expression


class EvaluateError(Exception):
    def __init__(self, error):
        super(Exception, self).__init__(str(error))


class EvaluationContext(object):
    def __init__(self, prolog: str | None, epilog: str | None, jetvis_variables: lldb.SBJetvisExpressionVariables | None):
        self.prolog_code: str = prolog or ""
        self.epilog_code: str = epilog or ""
        self.jetvis_variables: lldb.SBJetvisExpressionVariables | None = jetvis_variables

    def add_context(self, expression: str) -> str:
        if self.prolog_code or self.epilog_code:
            return f"{self.prolog_code}; auto&& __lldb__result__ = ({expression}); " \
                   f"{self.epilog_code}; __lldb__result__;"
        return expression


class EvalSettings:
    _DEFAULT_EXPRESSION_OPTIONS = prepare_default_lldb_expression_options()

    def __init__(self, name: Optional[str] = None, options: lldb.SBExpressionOptions = None,
                 save_expression_in_metadata: bool = False, getter_call: Optional[GeneratedMethod.Call] = None):
        self.name = name
        self.options = options or self._DEFAULT_EXPRESSION_OPTIONS
        self.save_expression_in_metadata = save_expression_in_metadata
        self.getter_call = getter_call

    @staticmethod
    def with_metadata(name: Optional[str] = None, expression_getter: Optional[GeneratedMethod] = None,
                      synthetic_getter_args: Optional[List[str]] = None) -> EvalSettings:
        getter_call = expression_getter.method_call(synthetic_getter_args) if expression_getter is not None else None
        return EvalSettings(name, None, True, getter_call)
