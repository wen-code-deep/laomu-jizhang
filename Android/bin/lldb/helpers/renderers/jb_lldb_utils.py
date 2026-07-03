from __future__ import annotations

from enum import Flag, auto
from typing import Optional

import lldb
from renderers.jb_lldb_declarative_formatters_options import set_recursion_level
from renderers.jb_lldb_evaluation_utils import EvalSettings, EvaluateError, EvaluationContext
from renderers.jb_lldb_intrinsics_prolog_cache import IntrinsicsPrologCache
from renderers.jb_lldb_item_expression import ItemExpression
from renderers.jb_lldb_jetvis_proxy import JetvisProxy
from renderers.jb_lldb_logging_manager import RENDER_LOG
from six import StringIO


class IgnoreSynthProvider(Exception):
    def __init__(self, msg=None):
        super(Exception, self).__init__(str(msg) if msg else None)


class Stream(object):
    def __init__(self, is64bit: bool, initial_level: int):
        self.stream = StringIO()
        self.pointer_format = "0x{:016x}" if is64bit else "0x{:08x}"
        self.length = 0
        self.level = initial_level

    def create_nested(self):
        val = self.__class__(False, self.level)
        val.pointer_format = self.pointer_format
        val.length = self.length
        return val

    def output(self, text):
        self.length += len(text)
        self.stream.write(text)

    def output_object(self, val_non_synth: lldb.SBValue):
        RENDER_LOG.info("Retrieving summary of value named '%s'...", val_non_synth.GetName())

        provider = get_viz_descriptor_provider()
        vis_descriptor = provider.get_matched_visualizers(val_non_synth, False)

        self.level += 1
        prev_level = set_recursion_level(self.level)
        try:
            if vis_descriptor is not None:
                try:
                    vis_descriptor.output_summary(val_non_synth, self)
                except Exception:
                    RENDER_LOG.exception("Internal error")
            else:
                self._output_object_fallback(provider, val_non_synth)
        finally:
            set_recursion_level(prev_level)
            self.level -= 1

    def _output_object_fallback(self, provider: AbstractVizDescriptorProvider, val_non_synth: lldb.SBValue):
        # force use raw vis descriptor
        vis_descriptor = provider.get_matched_visualizers(val_non_synth, True)
        if vis_descriptor is not None:
            try:
                vis_descriptor.output_summary(val_non_synth, self)
            except Exception as e:
                RENDER_LOG.error('Internal error: %s', e)
        else:
            summary_value = val_non_synth.GetValue() or ''
            self.output(summary_value)

    def output_string(self, text: str):
        self.output(text)

    def output_keyword(self, text: str):
        self.output(text)

    def output_number(self, text: str):
        self.output(text)

    def output_comment(self, text: str):
        self.output(text)

    def output_value(self, text: str):
        self.output(text)

    def output_address(self, address: int):
        self.output_comment(self.pointer_format.format(address))

    def __str__(self):
        return self.stream.getvalue()


INVALID_CHILD_INDEX = 2 ** 32 - 1


class ChildrenProviderUpdateResult(Flag):
    NONE = 0
    SIZE_UPDATED = auto()


class AbstractChildrenProvider(object):
    def num_children(self) -> int:
        return 0

    def get_child_index(self, name: str) -> int:
        return INVALID_CHILD_INDEX

    def get_child_at_index(self, index: int) -> lldb.SBValue:
        raise NotImplementedError

    def try_update_size(self, value_non_synth: lldb.SBValue) -> ChildrenProviderUpdateResult:
        return ChildrenProviderUpdateResult.NONE


g_empty_children_provider = AbstractChildrenProvider()


class AbstractVisDescriptor(object):
    def output_summary(self, value_non_synth: lldb.SBValue, stream: Stream):
        pass

    def prepare_children(self, value_non_synth: lldb.SBValue) -> AbstractChildrenProvider:
        return g_empty_children_provider


class AbstractVizDescriptorProvider(object):
    def get_matched_visualizers(self, val_non_synth: lldb.SBValue, force_raw_format: bool) -> AbstractVisDescriptor:
        pass


g_viz_descriptor_provider: AbstractVizDescriptorProvider


def get_viz_descriptor_provider() -> AbstractVizDescriptorProvider:
    return g_viz_descriptor_provider


def set_viz_descriptor_provider(provider: AbstractVizDescriptorProvider):
    global g_viz_descriptor_provider
    g_viz_descriptor_provider = provider


class FormattedStream(Stream):
    def output_string(self, text):
        self.stream.write("\xfeS")
        self.output(self.escape_rich_value_mark(text))
        self.stream.write("\xfeE")

    def output_keyword(self, text):
        self.stream.write("\xfeK")
        self.output(self.escape_rich_value_mark(text))
        self.stream.write("\xfeE")

    def output_number(self, text):
        self.stream.write("\xfeN")
        self.output(self.escape_rich_value_mark(text))
        self.stream.write("\xfeE")

    def output_comment(self, text):
        self.stream.write("\xfeC")
        self.output(self.escape_rich_value_mark(text))
        self.stream.write("\xfeE")

    def output_value(self, text):
        self.stream.write("\xfeV")
        self.output(self.escape_rich_value_mark(text))
        self.stream.write("\xfeE")

    def escape_rich_value_mark(self, text):
        return text.replace("\xfe", "\xfe\xfe")


def _execute_lldb_eval(val: lldb.SBValue, code: str, user_eval_settings: Optional[EvalSettings],
                       jetvis_variables: lldb.SBJetvisExpressionVariables | None) -> lldb.SBValue:
    eval_settings = user_eval_settings or EvalSettings()
    if JetvisProxy.is_enabled():
        result = JetvisProxy.evaluate_expression_on_object(val, code, eval_settings.name, jetvis_variables)
    else:
        result = val.EvaluateExpression(code, eval_settings.options, eval_settings.name)
    if result is None:
        err = lldb.SBError()
        err.SetErrorString("evaluation setup failed")
        RENDER_LOG.error("Evaluate failed: %s", err)
        raise EvaluateError(err)
    if eval_settings.save_expression_in_metadata:
        ItemExpression.update_item_expression(result, val, code, eval_settings.getter_call, jetvis_variables is not None)
    elif eval_settings.name is not None:
        ItemExpression.invalidate_item_expression(result)
    return result


def eval_expression(val: lldb.SBValue, expr: str, settings: Optional[EvalSettings] = None,
                    context: Optional[EvaluationContext] = None) -> lldb.SBValue:
    RENDER_LOG.info("Evaluate '%s' in context of '%s' of type '%s'", expr, val.GetName(), val.GetTypeName())

    expression_with_context = context.add_context(expr) if context else expr
    jetvis_variables = context.jetvis_variables if context else None
    expression_with_intrinsics = IntrinsicsPrologCache.add_intrinsics_prolog(val, expression_with_context)
    eval_result = _execute_lldb_eval(val, expression_with_intrinsics, settings, jetvis_variables)

    result_non_synth = eval_result.GetNonSyntheticValue()
    err: lldb.SBError = result_non_synth.GetError()
    if err.Fail():
        err_type = err.GetType()
        err_code = err.GetError()
        if err_type == lldb.eErrorTypeExpression and err_code == lldb.eExpressionParseError:
            RENDER_LOG.error("Evaluate failed (can't parse expression): %s", err)
            raise EvaluateError(err)

        # error is runtime error which is handled later
        RENDER_LOG.warning("Returning value with error: %s", err)
        return eval_result

    RENDER_LOG.info("Evaluate succeed: result type - %s", result_non_synth.GetTypeName())
    return eval_result


def get_root_value(val: lldb.SBValue) -> lldb.SBValue:
    val_non_synth: lldb.SBValue = val.GetNonSyntheticValue()
    val_non_synth.SetPreferDynamicValue(lldb.eNoDynamicValues)
    return val_non_synth


def get_value_format(val: lldb.SBValue) -> int:
    return get_root_value(val).GetFormat()


def set_value_format(val: lldb.SBValue, fmt: int):
    # noinspection PyArgumentList
    get_root_value(val).SetFormat(fmt)
