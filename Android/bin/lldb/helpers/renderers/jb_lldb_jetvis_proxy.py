from __future__ import annotations

import os
from typing import Iterable

import lldb
from jb_declarative_formatters import TypeViz, TypeVizName
from jb_declarative_formatters.type_viz_generated_method import GeneratedJetvisIntrinsicDefinition
from jb_declarative_formatters.type_viz_intrinsic import TypeVizIntrinsic, TypeVizIntrinsicParameter
from renderers.jb_lldb_item_expression import ItemExpression
from renderers.jb_lldb_logging_manager import RENDER_LOG


class JetvisProxy:
    _ENABLED = os.environ.get("LLDB_USE_JETVIS_EXPRESSION_EVALUATOR", "true").lower() in {"yes", "true", "on", "1"}

    _LOG = RENDER_LOG.getChild("jetvis engine")

    @classmethod
    def _report_warnings(cls, evaluation_warnings: lldb.SBJetvisWarnings):
        for i in range(evaluation_warnings.GetWarningCount()):
            warning_msg = evaluation_warnings.GetWarningAtIndex(i)
            if warning_msg:
                cls._LOG.warning(warning_msg)

    @classmethod
    def evaluate_expression_on_object(cls, this_object: lldb.SBValue, expression: str, name: str,
                                      variables: lldb.SBJetvisExpressionVariables | None) -> lldb.SBValue:
        evaluation_warnings = lldb.SBJetvisWarnings()
        if variables is not None:
            evaluation_result: lldb.SBValue = lldb.SBJetvisEvaluator.EvaluateExpressionOnObject(this_object, expression, name,
                                                                                                evaluation_warnings, variables)
        else:
            evaluation_result: lldb.SBValue = lldb.SBJetvisEvaluator.EvaluateExpressionOnObject(this_object, expression, name,
                                                                                                evaluation_warnings)
        cls._report_warnings(evaluation_warnings)
        return evaluation_result

    @classmethod
    def evaluate_expression_on_stack_frame(cls, frame: lldb.SBFrame, expression: str) -> lldb.SBValue:
        evaluation_warnings = lldb.SBJetvisWarnings()
        evaluation_result: lldb.SBValue = lldb.SBJetvisEvaluator.EvaluateExpressionOnStackFrame(frame, expression, expression,
                                                                                                evaluation_warnings)
        cls._report_warnings(evaluation_warnings)
        if evaluation_result.IsValid() and evaluation_result.GetError().Success():
            static_value: lldb.SBValue = evaluation_result.GetStaticValue()
            static_value.SetPreferDynamicValue(lldb.eDynamicDontRunTarget)
            ItemExpression.set_item_expression(static_value, expression)
            return static_value
        return evaluation_result

    @classmethod
    def initialize_expr_variables_by_names(cls, this_object: lldb.SBValue,
                                           names: list[str], initializers: list[str]) -> lldb.SBJetvisExpressionVariables | None:
        if not cls.is_enabled():
            return None
        cls._LOG.debug("Initializing local variables %s, initializers: %s", names, initializers)
        error = lldb.SBError()
        evaluation_warnings = lldb.SBJetvisWarnings()
        variables: lldb.SBJetvisExpressionVariables = lldb.SBJetvisEvaluator.InitializeExpressionVariables(error, this_object, names,
                                                                                                           initializers,
                                                                                                           evaluation_warnings)
        cls._report_warnings(evaluation_warnings)
        if error.Fail():
            cls._LOG.error("Error on initializing local variables: %s", error.description)
            return None
        return variables

    @classmethod
    def clear(cls, debugger: lldb.SBDebugger):
        if cls.is_enabled():
            jetvis_registry: lldb.SBJetvisRegistry = debugger.GetJetvisRegistry()
            jetvis_registry.Clear()

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._ENABLED

    @classmethod
    def register_type_visualizers(cls, debugger: lldb.SBDebugger, storages: Iterable):
        if not cls.is_enabled():
            return

        jetvis_registry: lldb.SBJetvisRegistry = debugger.GetJetvisRegistry()
        all_global_intrinsics: list[TypeVizIntrinsic] = []
        for storage in storages:
            for item in storage.iterate_type_viz_unsorted():
                type_viz: TypeViz = item[1]
                type_viz_name: TypeVizName = item[2]

                global_intrinsics = cls._register_type_visualizer(jetvis_registry, type_viz, type_viz_name)
                for global_intrinsic in global_intrinsics:
                    if global_intrinsic not in all_global_intrinsics:
                        all_global_intrinsics.append(global_intrinsic)

            generated_intrinsics: list[GeneratedJetvisIntrinsicDefinition] = storage.get_jetvis_generated_intrinsics()
            for intrinsic in generated_intrinsics:
                cls._register_type_intrinsic(jetvis_registry, intrinsic.name, intrinsic.type_name, intrinsic.expression,
                                             intrinsic.param_names, intrinsic.param_types, intrinsic.return_type, intrinsic.priority, True)

        for global_intrinsic in all_global_intrinsics:
            param_names, param_types = cls._split_param_name_type(global_intrinsic.parameters)
            cls._LOG.debug("Registering global intrinsic '%s'; expr: '%s', param_names: %s, param_types: %s, return type: '%s'",
                           global_intrinsic.base_name, global_intrinsic.original_expression, param_names, param_types,
                           global_intrinsic.return_type)
            error: lldb.SBError = jetvis_registry.RegisterGlobalIntrinsic(global_intrinsic.base_name, global_intrinsic.original_expression,
                                                                          global_intrinsic.return_type, param_names, param_types)
            if error.Fail():
                cls._LOG.error("Error on registering global intrinsic '%s': %s", global_intrinsic.base_name, error.description)

    @staticmethod
    def _split_param_name_type(parameters: list[TypeVizIntrinsicParameter]) -> tuple[list[str], list[str]]:
        param_names = []
        param_types = []
        for param in parameters:
            param_names.append(param.parameter_name or "")
            param_types.append(param.parameter_type or "")
        return param_names, param_types

    @classmethod
    def _register_type_intrinsic(cls, jetvis_registry: lldb.SBJetvisRegistry, intrinsic_name: str, type_name: str, body: str,
                                 param_names: list[str] | None, param_types: list[str] | None, return_type: str | None,
                                 priority: int, optional: bool):
        cls._LOG.debug(
            "Registering type intrinsic '%s'; type: '%s', expr: '%s', "
            "param_names: %s, param_types: %s, return type: '%s', priority: %s, optional: %s",
            intrinsic_name, type_name, body, param_names,
            param_types, return_type, priority, optional)
        error: lldb.SBError = jetvis_registry.RegisterTypeIntrinsic(intrinsic_name, body, return_type, param_names, param_types,
                                                                    type_name, priority, optional)
        if error.Fail():
            cls._LOG.error("Error on registering type intrinsic '%s': %s", intrinsic_name, error.description)

    @classmethod
    def _register_type_visualizer(cls, jetvis_registry: lldb.SBJetvisRegistry, type_viz: TypeViz, type_viz_name: TypeVizName) \
      -> list[TypeVizIntrinsic]:
        cls._LOG.debug("Registering type visualizer '%s' in JetvisRegistry", type_viz_name.type_name)

        for type_intrinsic in type_viz.type_all_intrinsics.declaration_order_list:
            param_names, param_types = cls._split_param_name_type(type_intrinsic.parameters)
            cls._register_type_intrinsic(jetvis_registry, type_intrinsic.base_name, type_viz_name.type_name,
                                         type_intrinsic.original_expression, param_names, param_types, type_intrinsic.return_type,
                                         type_viz.priority, type_intrinsic.optional)

        return type_viz.global_all_intrinsics.declaration_order_list
