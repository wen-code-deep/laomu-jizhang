from __future__ import annotations

import logging
import re
from enum import Enum, auto
from typing import List, Tuple, Optional, Callable, NamedTuple
import hashlib

from . import TypeVizItemProviderArrayItems, TypeVizItemProviderIndexListItems, TypeVizItemProviderSingle, \
    TypeVizItemIndexNodeTypeNode, TypeVizItemValuePointerTypeNode, TypeVizItemProviderLinkedListItems, \
    TypeVizItemProviderTreeItems, TypeVizItemProviderExpanded
from .parsers.context_operator_parser import replace_context_operators_in_text
from .type_name_template import TypeNameTemplate
from .type_viz import TypeVizSmartPointer, TypeViz, TypeVizName, TypeVizStringView
from .type_viz_intrinsic import TypeVizIntrinsic, IntrinsicsScope, apply_intrinsics_to_expression
from .type_viz_item_providers import TypeVizItemProviderSynthetic
from .type_viz_mixins import TypeVizItemExpressionGetterNodeMixin, TypeVizItemNamedNodeMixin, TypeVizItemConditionalNodeMixin
from .parsers.cpp_parser import CppParser
from .type_viz_generated_method import GeneratedMethod, GeneratedMethodDefinition, GeneratedJetvisIntrinsicDefinition
from .type_viz_type_traits import TypeVizTypeTraits


class TypeVizTopLevelMethods:
    # An easy way to disable everything if something goes wrong
    DISABLE_TOP_LEVEL_DECLARATIONS = False
    ENABLE_ASSERTIONS = False

    _INVALID_CHAR_REGEX = re.compile(r'[^\w$]')

    _INTERNAL_INTRINSIC_PREFIX = "_jb$intrinsic$internal$"

    _TYPE_MARKER = "${DECLARATION_CONTEXT}"

    @staticmethod
    def _make_type_arg_marker(index: int) -> str:
        # Replace $T1 (i = 0) -> ${DECLARATION_CONTEXT_WILDCARD_0}, $T2 (i = 1) -> ${DECLARATION_CONTEXT_WILDCARD__1}, ...
        #
        # A space in the end is needed because our hacked Clang parser cannot correctly parse type expressions with '>>'.
        # It only may handle '> >', e.g., '(A<B<C> > *) ptr'.
        # We assume that all type names in the debugger are valid, meaning that they already contain a space between consecutive
        # closing angle brackets ('> >').
        # However, after substitution (e.g., '(A<${DECLARATION_CONTEXT_WILDCARD_0}> *) ptr'), we might accidentally make '>>'.
        # To prevent this, we add an extra space at the end of the type name before substitution.
        return f"${{DECLARATION_CONTEXT_WILDCARD_{index}}} "

    _IndexableTypeItemProvider = TypeVizItemProviderArrayItems | TypeVizItemProviderIndexListItems
    _SingleTypeItemProvider = TypeVizItemProviderSingle | TypeVizItemProviderExpanded
    _IndexableItemNode = TypeVizItemValuePointerTypeNode | TypeVizItemIndexNodeTypeNode

    class _SubscriptStatus(Enum):
        REQUIRED = auto()
        ALREADY_EXISTS = auto()
        FORBIDDEN = auto()

    # dict[MethodName, dict[tuple[MethodExpression, TypePriority], Count]]
    _TypeMethods = dict[str, dict[tuple[str, int], int]]

    class _MethodParameter(NamedTuple):
        param_type: str
        param_name: str

    class _IntrinsicUniqueIdentifier(NamedTuple):
        owning_type_name: str | None
        intrinsic_name: str
        parameters: tuple[TypeVizTopLevelMethods._MethodParameter, ...]
        expression: str

    def __init__(self, logger: logging.Logger, is_jetvis_enabled: bool):
        self._known_method_names: dict[str, TypeVizTopLevelMethods._TypeMethods] = {}
        self._known_intrinsics: set[TypeVizTopLevelMethods._IntrinsicUniqueIdentifier] = set()
        self._private_getters: dict[str, str] = {}
        self._subscript_operators_in_types: dict[str, str] = {}
        self._method_definitions: list[GeneratedMethodDefinition] = []
        self._jetvis_intrinsics: list[GeneratedJetvisIntrinsicDefinition] = []
        self._use_jetvis = is_jetvis_enabled
        self._logger = logger
        self._type_intrinsics: IntrinsicsScope | None = None
        self._global_intrinsics: IntrinsicsScope | None = None

    @property
    def methods_definitions(self) -> list[GeneratedMethodDefinition]:
        return self._method_definitions

    @property
    def jetvis_intrinsics(self) -> list[GeneratedJetvisIntrinsicDefinition]:
        return self._jetvis_intrinsics

    def collect_top_level_methods_from(self,  type_viz: TypeViz, type_name: TypeVizName):
        if self.DISABLE_TOP_LEVEL_DECLARATIONS:
            return

        if self._use_jetvis:
            self._type_intrinsics = type_viz.type_all_intrinsics
            self._global_intrinsics = type_viz.global_all_intrinsics
        else:
            self._add_global_intrinsics_for_internal_usage(type_viz.global_lazy_intrinsics)
            self._add_type_intrinsics_for_internal_usage(type_name, type_viz.type_lazy_intrinsics)
            self._add_type_intrinsics_for_public_usage(type_name, type_viz.type_all_intrinsics)

        item_providers = type_viz.item_providers or []

        has_new_string_methods, has_new_string_methods_for_jetvis = self._add_getters_for_all_providers(type_name, item_providers,
                                                                                                        True, type_viz.priority)

        if type_viz.smart_pointer is not None:
            self._method_definitions += self._smart_pointer_methods(type_name, type_viz.smart_pointer)
            self._jetvis_intrinsics += self._smart_pointer_methods_for_jetvis(type_name, type_viz.smart_pointer, type_viz.priority)
        if not has_new_string_methods:
            self._method_definitions += self._string_methods_from_string_view(type_name, type_viz.string_views)
        if not has_new_string_methods_for_jetvis:
            self._jetvis_intrinsics += self._string_methods_from_string_views_for_jetvis(type_name, type_viz.string_views,
                                                                                         type_viz.priority)

        if self._use_jetvis:
            self._add_type_intrinsics_for_public_usage(type_name, self._type_intrinsics)
            self._add_type_intrinsics_for_internal_usage(type_name, self._type_intrinsics.retain_only_lazy())
            self._add_global_intrinsics_for_internal_usage(self._global_intrinsics.retain_only_lazy())

        self._type_intrinsics = None
        self._global_intrinsics = None

    def _add_getters_for_all_providers(self, type_name: TypeVizName, item_providers: list, add_string_methods: bool, priority: int) \
      -> tuple[bool, bool]:
        has_new_string_methods = False
        has_new_string_methods_for_jetvis = False
        for item_provider in item_providers:
            match item_provider:
                case TypeVizItemProviderSingle():
                    self._add_single_item_getter(type_name, item_provider, priority)
                case TypeVizItemProviderExpanded():
                    self._add_single_item_getter(type_name, item_provider, priority)
                case TypeVizItemProviderSynthetic():
                    self._add_synthetic_item_getter(type_name, item_provider, priority)
                case TypeVizItemProviderArrayItems():
                    self._add_array_methods(type_name, item_provider, priority)
                    if add_string_methods and not has_new_string_methods:
                        string_methods = self._string_methods_from_array_items(type_name, item_provider)
                        self._method_definitions += string_methods
                        has_new_string_methods = bool(string_methods)
                    if add_string_methods and not has_new_string_methods_for_jetvis:
                        string_methods_for_jetvis = self._string_methods_from_array_items_for_jetvis(type_name, item_provider, priority)
                        self._jetvis_intrinsics += string_methods_for_jetvis
                        has_new_string_methods_for_jetvis = bool(string_methods_for_jetvis)
                case TypeVizItemProviderIndexListItems():
                    self._add_index_list_methods(type_name, item_provider, priority)
                case TypeVizItemProviderLinkedListItems():
                    self._add_linked_list_method(type_name, item_provider, priority)
                case TypeVizItemProviderTreeItems():
                    self._add_tree_method(type_name, item_provider, priority)
        return has_new_string_methods, has_new_string_methods_for_jetvis

    @staticmethod
    def _make_internal_name(name: str) -> str:
        return f"jb$internal$name$${name}$$"

    @classmethod
    def _mangle_name(cls, name: str) -> str:
        return cls._INVALID_CHAR_REGEX.sub('$', name)

    @staticmethod
    def _get_condition(conditional_mixin: TypeVizItemConditionalNodeMixin | TypeVizStringView | None) -> str | None:
        if conditional_mixin and conditional_mixin.condition and conditional_mixin.condition.condition:
            return conditional_mixin.condition.condition
        return None

    def _prepare_expr(self, expr: str) -> str:
        if self._use_jetvis:
            # Do not combine '[self._type_intrinsics, self._global_intrinsics]' this will work differently.
            # For example, when a global intrinsic calls another global intrinsic that has the same name as another type intrinsic.
            if self._type_intrinsics is not None:
                expr = apply_intrinsics_to_expression(expr, [self._type_intrinsics], self._logger)
            if self._global_intrinsics is not None:
                expr = apply_intrinsics_to_expression(expr, [self._global_intrinsics], self._logger)

            expr = replace_context_operators_in_text(expr)

        expr = expr.replace(TypeVizIntrinsic.INTRINSIC_NAME_PREFIX, self._INTERNAL_INTRINSIC_PREFIX)
        substituted_expr, all_substituted = CppParser.substitute_wildcards(expr, self._make_type_arg_marker)
        if self.ENABLE_ASSERTIONS:
            assert all_substituted, f"There are unsubstituted wildcards left in the expression '{substituted_expr}'"
        return substituted_expr

    def _add_getter_with_unique_name(self, type_name: TypeVizName, item_node: TypeVizItemExpressionGetterNodeMixin,
                                     method_name: str, method_expr: str, priority: int) -> bool:
        method_expressions = self._known_method_names.setdefault(type_name.type_name, {}).setdefault(method_name, {})
        new_method_name_id = len(method_expressions)
        method_name_id = method_expressions.setdefault((method_expr, priority), new_method_name_id)
        if method_name_id:
            method_name += str(method_name_id)
        if item_node.expression_getter is None:
            item_node.expression_getter = GeneratedMethod.named_method(method_name, method_expr)
        elif self.ENABLE_ASSERTIONS:
            assert item_node.expression_getter.name == method_name, \
                f"getter name: {item_node.expression_getter.name}, generated name: {method_name}"
        return new_method_name_id == method_name_id

    def _try_declare_subscript_operator(self, type_name: TypeVizName, method_expr: str) -> _SubscriptStatus:
        declared = self._subscript_operators_in_types.get(type_name.type_name, None)
        if declared is None:
            self._subscript_operators_in_types[type_name.type_name] = method_expr
            return self._SubscriptStatus.REQUIRED
        return self._SubscriptStatus.ALREADY_EXISTS if declared == method_expr else self._SubscriptStatus.FORBIDDEN

    def _smart_pointer_methods_for_jetvis(self, type_name: TypeVizName, smart_pointer: TypeVizSmartPointer, priority: int) -> \
      list[GeneratedJetvisIntrinsicDefinition]:
        expr = smart_pointer.expression.text
        if not expr:
            return []

        other_param = self._make_internal_name("other")
        methods = [
            GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator->", f"{expr}"),
            GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator*", f"*({expr})"),
            GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator bool", f"static_cast<bool>({expr})"),
            GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator==",
                                               f"(static_cast<const void *>({expr}) == {other_param})", [other_param], ["const void *"]),
            GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator!=",
                                               f"(static_cast<const void *>({expr}) != {other_param})", [other_param], ["const void *"])
        ]

        if smart_pointer.usage == TypeVizSmartPointer.Usage.Indexable:
            index_param = self._make_internal_name("index")
            subscript_operator = GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator[]", f"({expr})[{index_param}]",
                                                                    [index_param], ["long long"])
            methods.append(subscript_operator)
            # TODO: We cannot support operator +, - now because we cannot modify and create non trivial objects in Jetvis expression

        return methods

    def _smart_pointer_methods(self, type_name: TypeVizName, smart_pointer: TypeVizSmartPointer) -> \
            List[GeneratedMethodDefinition]:
        expr = self._prepare_expr(smart_pointer.expression.text)
        operators = self._get_minimal_operators(expr)
        # Declare 'Indexable' separately because LLDB may be unable to compile methods like 'operator+', 'operator-'
        # since it requires an available copy constructor for a smart pointer type (usually, 'Indexable' is an iterator)
        if smart_pointer.usage == TypeVizSmartPointer.Usage.Indexable:
            operators += self._get_indexable_operators(type_name, expr)

        return [GeneratedMethodDefinition(type_name.type_name_template, f"operator{operator}", body) for operator, body in operators]

    @classmethod
    def _get_minimal_operators(cls, expr: str) -> List[Tuple[str, str]]:
        other_param = cls._make_internal_name("other")
        return [
            ("->", f"auto {cls._TYPE_MARKER}::operator->() const -> decltype({expr}) {{ return {expr}; }}"),
            ("*", f"auto {cls._TYPE_MARKER}::operator*() const -> decltype((*({expr}))) {{ return (*({expr})); }}"),
            ("!", f"bool {cls._TYPE_MARKER}::operator!() const {{ return !({expr}); }}"),
            ("==", f"bool {cls._TYPE_MARKER}::operator==(const void *{other_param}) const {{ "
                   f"return static_cast<const void *>({expr}) == {other_param}; "
                   f"}}"),
            ("!=", f"bool {cls._TYPE_MARKER}::operator!=(const void *{other_param}) const {{ "
                   f"return static_cast<const void *>({expr}) != {other_param}; "
                   f"}}")
        ]

    def _get_indexable_operators(self, type_name: TypeVizName, expr: str) -> List[Tuple[str, str]]:
        index_param = self._make_internal_name("index")
        operators = []
        subscript_body = f"return (({expr})[{index_param}]);"
        # Add an operator even if the status is FORBIDDEN.
        # This declaration is not used as a synthetic getter, therefore it is safe to add one more declaration here.
        # In the worst case, it will simply be ignored as a redeclaration.
        if self._try_declare_subscript_operator(type_name, subscript_body) != self._SubscriptStatus.ALREADY_EXISTS:
            operators.append(
                ("[]", f"decltype(auto) {self._TYPE_MARKER}::operator[](long long {index_param}) const {{ {subscript_body} }}")
            )
        # Support only trivial expressions with the property accessing, such as '_Ptr'.
        # Do not support complex expressions, like:
        #   '_Ptr + _Idx' or
        #   '_Ptr->_Isnil ? nullptr : &_Ptr->_Myval' (Usually, such expressions are used for 'Minimal' smart pointers)
        if CppParser.is_trivial_expression(expr):
            offset_param = self._make_internal_name("offset")
            result = self._make_internal_name("result")
            operators += [
                ("+", f"::{self._TYPE_MARKER} {self._TYPE_MARKER}::operator+(long long {offset_param}) const {{ "
                      f"{self._TYPE_MARKER} {result} = *this; {result}.{expr} += {offset_param}; return {result}; "
                      f"}}"),
                ("-", f"::{self._TYPE_MARKER} {self._TYPE_MARKER}::operator-(long long {offset_param}) const {{ "
                      f"{self._TYPE_MARKER} {result} = *this; {result}.{expr} -= {offset_param}; return {result}; "
                      f"}}")
            ]
        return operators

    def _indexable_node_expression(self, item_node: _IndexableItemNode, index_param: str, prepare_expression: bool) -> str:
        expr = self._prepare_expr(item_node.expr.text) if prepare_expression else item_node.expr.text
        if isinstance(item_node, TypeVizItemIndexNodeTypeNode):
            return expr.replace("$i", index_param)
        return f"({expr})[{index_param}]"

    def _subscript_operator_body(self, item_nodes: List[_IndexableItemNode], index_param: str, for_jetvis: bool) -> str:
        lines = []
        for (index, item_node) in enumerate(item_nodes):
            expr = self._indexable_node_expression(item_node, index_param, not for_jetvis)
            if condition_expr := self._get_condition(item_node):
                if not for_jetvis:
                    condition_expr = self._prepare_expr(condition_expr)
                if isinstance(item_node, TypeVizItemIndexNodeTypeNode):
                    condition_expr = condition_expr.replace("$i", index_param)
                lines.append(f'({condition_expr}) ? ({expr}) :')
                if index + 1 == len(item_nodes):
                    if for_jetvis:
                        lines.append('__jetvis_evaluation_error("unable to evaluate \'operator[]\' because all conditions are false")')
                    else:
                        lines.append(f'({expr})')
            else:
                lines.append(f'({expr})')
                break

        if for_jetvis:
            return "\n".join(lines)
        return "return " + '\n'.join(lines) + ";\n"

    @classmethod
    def _make_mutable_const_method(cls, type_name_template: TypeNameTemplate, method_name: str, body: str,
                                   params: tuple[_MethodParameter, ...] | None = None,
                                   mutable_method_prefix: str | None = None) -> GeneratedMethodDefinition:
        params = params or ()
        param_list = ', '.join(map(lambda p: f"{p.param_type} {p.param_name}", params))
        arg_list = ', '.join(map(lambda p: f"{p.param_name}", params))
        mutable_method = cls._make_internal_name(f"{mutable_method_prefix or method_name}$mutable")
        return GeneratedMethodDefinition(
            declaration_context=type_name_template,
            declaration_name=method_name,
            definition_template=f"decltype(auto) {cls._TYPE_MARKER}::{mutable_method}({param_list}) {{ {body} }}\n"
                                f"decltype(auto) {cls._TYPE_MARKER}::{method_name}({param_list}) const {{ "
                                f"return const_cast<::{cls._TYPE_MARKER} *>(this)->{mutable_method}({arg_list}); "
                                f"}}"
        )

    @classmethod
    def _container_method_definition(cls, type_name: TypeVizName, item_node: TypeVizItemExpressionGetterNodeMixin,
                                     body: str, index_param: str, mutable_method_prefix: Optional[str] = None) -> \
            GeneratedMethodDefinition:
        method_name = item_node.expression_getter.name
        params = (cls._MethodParameter("long long", index_param), )
        return cls._make_mutable_const_method(type_name.type_name_template, method_name, body, params, mutable_method_prefix)

    def _add_subscript_operator_for_jetvis(self, type_name: TypeVizName, item_nodes: List[_IndexableItemNode], index_param: str,
                                           priority: int):
        jetvis_subscript_body = self._subscript_operator_body(item_nodes, index_param, True)
        if jetvis_subscript_body:
            jetvis_intrinsic = GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, "operator[]",
                                                                  jetvis_subscript_body, [index_param], ["long long"])
            self._jetvis_intrinsics.append(jetvis_intrinsic)

    def _add_indexed_methods(self, type_name: TypeVizName, indexable_provider: _IndexableTypeItemProvider,
                             get_nodes: Callable[[_IndexableTypeItemProvider], List[_IndexableItemNode]], priority: int):
        index_param = self._make_internal_name("index")
        item_nodes = get_nodes(indexable_provider)
        item_nodes_count = len(item_nodes)
        if item_nodes_count == 1 or TypeVizTypeTraits.is_subscript_operator_required(type_name.type_name):
            body = self._subscript_operator_body(item_nodes, index_param, False)
            subscript_status = self._try_declare_subscript_operator(type_name, body)
            if subscript_status != self._SubscriptStatus.FORBIDDEN:
                if indexable_provider.expression_getter is None:
                    indexable_provider.expression_getter = GeneratedMethod.subscript_operator(body)
                elif self.ENABLE_ASSERTIONS:
                    assert isinstance(indexable_provider.expression_getter.identifier,
                                      GeneratedMethod.SubscriptOperator)
                if subscript_status == self._SubscriptStatus.REQUIRED:
                    method_definition = self._container_method_definition(type_name, indexable_provider, body,
                                                                          index_param, "op$subscript")
                    self._method_definitions.append(method_definition)
                    self._add_subscript_operator_for_jetvis(type_name, item_nodes, index_param, priority)
                return
        else:
            self._add_subscript_operator_for_jetvis(type_name, item_nodes, index_param, priority)

        for item_node in item_nodes:
            prepared_expr = self._indexable_node_expression(item_node, index_param, True)
            if self._add_getter_with_unique_name(type_name, item_node, f"_get$", prepared_expr, priority):
                body = f"return ({prepared_expr});"

                method_definition = self._container_method_definition(type_name, item_node, body, index_param)
                self._method_definitions.append(method_definition)

                jetvis_intrinsic = GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, item_node.expression_getter.name,
                                                                      self._indexable_node_expression(item_node, index_param, False),
                                                                      [index_param], ["long long"])
                self._jetvis_intrinsics.append(jetvis_intrinsic)

    def _add_array_methods(self, type_name: TypeVizName, array_items: TypeVizItemProviderArrayItems, priority: int):
        self._add_indexed_methods(type_name, array_items, lambda items: items.value_pointer_nodes, priority)

    def _add_index_list_methods(self, type_name: TypeVizName, index_list_items: TypeVizItemProviderIndexListItems, priority: int):
        self._add_indexed_methods(type_name, index_list_items, lambda items: items.value_node_nodes, priority)

    def _try_as_internal_getter(self, name: str, expr: str) -> str:
        expr = CppParser.simplify_cpp_expression(expr)
        if CppParser.is_trivial_expression(expr):
            return expr
        expr = self._prepare_expr(expr)
        getter = f"private$get${name}${hashlib.sha256(expr.encode()).hexdigest()}"
        getter = self._make_internal_name(getter)
        if getter not in self._private_getters:
            self._method_definitions.append(self._make_mutable_const_method(TypeNameTemplate("*"), getter, f"return ({expr});"))
            self._private_getters[getter] = expr
        elif self.ENABLE_ASSERTIONS:
            assert self._private_getters[getter] == expr

        return f"{getter}()"

    def _add_linked_list_method(self, type_name: TypeVizName, list_items: TypeVizItemProviderLinkedListItems, priority: int):
        index_param = self._make_internal_name("index")
        next_ptr = self._try_as_internal_getter("list$next", list_items.next_pointer_node.text)
        get_value = self._try_as_internal_getter("list$value", list_items.value_node_node.expr.text)
        body = (f"auto it = {self._prepare_expr(list_items.head_pointer_node.text)};\n"
                f"while ({index_param}-- > 0) it = it->{next_ptr};\n"
                f"return (it->{get_value});\n")
        if self._add_getter_with_unique_name(type_name, list_items, f"_get$", body, priority):
            method_definition = self._container_method_definition(type_name, list_items, body, index_param)
            self._method_definitions.append(method_definition)

    def _add_tree_method(self, type_name: TypeVizName, tree_items: TypeVizItemProviderTreeItems, priority: int):
        index_param = self._make_internal_name("index")
        counter = self._make_internal_name("element_counter")
        node = self._make_internal_name("node")
        found = self._make_internal_name("found")
        inorder_method = self._make_internal_name("get_inorder_element")
        node_ptr_type = self._make_internal_name("NodePtr")
        inorder_helper_type = self._make_internal_name("InorderHelper")

        head_ptr = self._prepare_expr(tree_items.head_pointer_node.text)
        left_ptr = self._try_as_internal_getter("tree$left", tree_items.left_pointer_node.text)
        right_ptr = self._try_as_internal_getter("tree$right", tree_items.right_pointer_node.text)
        get_value = self._try_as_internal_getter("tree$value", tree_items.value_node_node.expr.text)
        stop_condition = f"(!{node})"
        if condition := self._get_condition(tree_items.value_node_node):
            condition_expr = self._try_as_internal_getter("tree$condition", condition)
            stop_condition += f" || !({node}->{condition_expr})"

        body = (f"using {node_ptr_type} = decltype({head_ptr});\n"
                f"struct {inorder_helper_type} {{\n"
                f"static {node_ptr_type} {inorder_method}({node_ptr_type} {node}, long long &{counter}) {{\n"
                f"if ({stop_condition}) return nullptr;\n"
                f"if (auto {found} = {inorder_method}({node}->{left_ptr}, {counter})) return {found};\n"
                f"if ({counter}-- <= 0) return {node};\n"
                f"return {inorder_method}({node}->{right_ptr}, {counter});"
                f"}}\n"
                f"}};\n"
                f"return ({inorder_helper_type}::{inorder_method}({head_ptr}, {index_param})->{get_value});\n")

        if self._add_getter_with_unique_name(type_name, tree_items, f"_get$", body, priority):
            method_definition = self._container_method_definition(type_name, tree_items, body, index_param)
            self._method_definitions.append(method_definition)

    def _add_primitive_getter_for_expr(self, type_name: TypeVizName, user_expr: str | None, method_name: str,
                                       primitive_item: TypeVizItemExpressionGetterNodeMixin, priority: int):
        if not user_expr:
            return
        original_expr = CppParser.simplify_cpp_expression(user_expr)
        if CppParser.is_trivial_expression(original_expr):
            return
        specifier, sub_expression = CppParser.cut_deref_or_address_of_from_trivial_expression(original_expr)
        if specifier and sub_expression:
            return
        prepared_expr = self._prepare_expr(original_expr)
        if self._add_getter_with_unique_name(type_name, primitive_item, method_name, prepared_expr, priority):
            unique_method_name = primitive_item.expression_getter.name
            method_definition = self._make_mutable_const_method(type_name.type_name_template, unique_method_name,
                                                                f"return ({prepared_expr});")
            self._method_definitions.append(method_definition)

            jetvis_intrinsic = GeneratedJetvisIntrinsicDefinition(type_name.type_name, priority, unique_method_name, original_expr)
            self._jetvis_intrinsics.append(jetvis_intrinsic)

    def _add_single_item_getter(self, type_name: TypeVizName, single_item: _SingleTypeItemProvider, priority: int):
        item_name = single_item.name if isinstance(single_item, TypeVizItemNamedNodeMixin) else None
        method_name = "_expanded$" if item_name is None else f"_item${self._mangle_name(item_name)}$"
        self._add_primitive_getter_for_expr(type_name, single_item.expr.text, method_name, single_item, priority)

    def _add_synthetic_item_getter(self, type_name: TypeVizName, synthetic_item: TypeVizItemProviderSynthetic, priority: int):
        method_name = f"_synthetic_item{self._mangle_name(synthetic_item.type_viz_synthetic_item.name)}$"
        self._add_primitive_getter_for_expr(type_name, synthetic_item.type_viz_synthetic_item.add_watch_expr,
                                            method_name, synthetic_item, priority)
        self._add_getters_for_all_providers(type_name, synthetic_item.type_viz_synthetic_item.item_providers or [], False, priority)

    def _try_add_new_intrinsic(self, owning_type: str | None, name: str, intrinsic: TypeVizIntrinsic) -> \
      tuple[str | None, tuple[_MethodParameter, ...] | None]:
        # Function overloading is not supported for top-level lazily declared methods.
        # However, we may support a kind of SFINAE, allowing different intrinsics with the same name
        # to be defined more than once, with the expectation that LLDB will select the first correct one.
        expr = self._prepare_expr(intrinsic.expression)
        params = tuple(
            self._MethodParameter(param.parameter_type, param.parameter_name or self._make_internal_name(f"{name}$param${i}"))
            for i, param in enumerate(intrinsic.parameters)
        )
        key = self._IntrinsicUniqueIdentifier(owning_type, name, params, expr)
        if key in self._known_intrinsics:
            return None, None
        self._known_intrinsics.add(key)
        return expr, params

    def _add_global_intrinsics_for_internal_usage(self, global_intrinsics: IntrinsicsScope):
        """
        Add global intrinsics for internal use only. These intrinsics have specially mangled names and are intended
        to be called only from other synthetically generated methods, such as item getters and operators.
        """
        for intrinsic in reversed(global_intrinsics.sorted_list):
            if not intrinsic.is_used or not intrinsic.is_lazy:
                continue
            name = f"{self._INTERNAL_INTRINSIC_PREFIX}{intrinsic.name}"
            expr, params = self._try_add_new_intrinsic(None, name, intrinsic)
            if expr is not None:
                params_line = ', '.join(map(lambda p: f"{p.param_type} {p.param_name}", params))
                method = GeneratedMethodDefinition(None, name, f"decltype(auto) {name}({params_line}) {{ return {expr}; }}")
                self._method_definitions.append(method)

    def _add_type_intrinsics_for_internal_usage(self, type_name: TypeVizName, type_intrinsics: IntrinsicsScope):
        """
        Add type intrinsics for internal use only. These intrinsics have specially mangled names and are intended
        to be called only from other synthetically generated methods, such as item getters and operators.
        """
        for intrinsic in reversed(type_intrinsics.sorted_list):
            if not intrinsic.is_used or not intrinsic.is_lazy:
                continue
            name = f"{self._INTERNAL_INTRINSIC_PREFIX}{intrinsic.name}"
            expr, params = self._try_add_new_intrinsic(type_name.type_name, name, intrinsic)
            if expr is not None:
                self._method_definitions.append(
                    self._make_mutable_const_method(type_name.type_name_template, name, f"return {expr};", params))


    def _add_type_intrinsics_for_public_usage(self, type_name: TypeVizName, type_intrinsics: IntrinsicsScope):
        """
        Add type intrinsics for public use. These intrinsics have original names and are intended
        to be called by users or other Natvis type visualizer by the original name.
        """
        for intrinsic in reversed(type_intrinsics.sorted_list):
            name = intrinsic.base_name
            expr, params = self._try_add_new_intrinsic(type_name.type_name, name, intrinsic)
            if expr is not None:
                self._method_definitions.append(
                    self._make_mutable_const_method(type_name.type_name_template, name, f"return {expr};", params))

    def _string_methods(self, type_name: TypeVizName,
                        init_block_builder: Callable[[TypeVizTypeTraits.StringTraits, str, str], str]) -> \
            List[GeneratedMethodDefinition]:
        string_type_traits = TypeVizTypeTraits.get_string_type_traits(type_name.type_name_template)
        if not string_type_traits:
            return []

        methods = []

        self_size = self._make_internal_name("self$size")
        self_data = self._make_internal_name("self$data")
        other_data = self._make_internal_name("other$data")
        other_size = self._make_internal_name("other$size")

        for type_specialization, type_traits in string_type_traits:
            init_part = init_block_builder(type_traits, self_data, self_size)

            def make_compare_part(is_equal: bool) -> str:
                op = "==" if is_equal else "!="
                # In Unreal natvis, empty strings are interpreted as a string "\0" with a size equal to 1
                unreal_empty_string_hack = f"if ({self_size} == 1 && {self_data} && !*{self_data}) {self_size} = 0;"
                return apply_intrinsics_to_expression(
                    expression=f"{unreal_empty_string_hack}\n"
                               f"if (!{other_data}) return {self_size} {op} 0;\n"
                               f"const unsigned long long {other_size} = {type_traits.strlen}({other_data});\n"
                               f"if (!{self_data}) return {other_size} {op} 0;\n"
                               f"if ({other_size} != {self_size}) return {'false' if is_equal else 'true'};\n"
                               f"return {type_traits.strncmp}({self_data}, {other_data}, {self_size}) {op} 0;",
                    user_intrinsics_scopes=[],  # apply only builtin intrinsics
                    logger=self._logger
                )

            # Add operators separately so that compilation and evaluation are faster for each of them
            methods.append(GeneratedMethodDefinition(
                declaration_context=type_specialization,
                declaration_name="operator==",
                definition_template=(f"bool {self._TYPE_MARKER}::operator==(const {type_traits.char_type} *{other_data}) const {{\n"
                         f"{init_part}\n"
                         f"{make_compare_part(True)}\n"
                      f"}}")))
            methods.append(GeneratedMethodDefinition(
                declaration_context=type_specialization,
                declaration_name="operator!=",
                definition_template=(f"bool {self._TYPE_MARKER}::operator!=(const {type_traits.char_type} *{other_data}) const {{\n"
                         f"{init_part}\n"
                         f"{make_compare_part(False)}\n"
                      f"}}")))

        return methods

    def _prepare_expr_for_string(self, type_traits: TypeVizTypeTraits.StringTraits, expr: str) -> str:
        prepared_expr = self._prepare_expr(expr)
        expr_with_fixed_type = prepared_expr.replace(self._make_type_arg_marker(0), type_traits.char_type)
        return expr_with_fixed_type

    def _string_methods_from_array_items(self, type_name: TypeVizName, array_items: TypeVizItemProviderArrayItems) -> \
            List[GeneratedMethodDefinition]:
        def array_items_init_block(type_traits: TypeVizTypeTraits.StringTraits, self_data: str, self_size: str) -> str:
            lines = [
                f"unsigned long long {self_size} = 0;\n"
                f"const {type_traits.char_type} *{self_data} = nullptr;\n"
            ]
            for size_node in array_items.size_nodes:
                if condition := self._get_condition(size_node):
                    lines.append(f"if ({self._prepare_expr_for_string(type_traits, condition)}) ")
                lines.append(f"{self_size} = (unsigned long long)({self._prepare_expr_for_string(type_traits, size_node.text)});\n")

            for pointer_node in array_items.value_pointer_nodes:
                if condition := self._get_condition(pointer_node):
                    lines.append(f"if ({self._prepare_expr_for_string(type_traits, condition)}) ")
                data_pointer_expr = self._prepare_expr_for_string(type_traits, pointer_node.expr.text)
                lines.append(f"{self_data} = (const {type_traits.char_type} *)({data_pointer_expr});\n")

            return "".join(lines)

        return self._string_methods(type_name, array_items_init_block)

    def _string_methods_from_string_view(self, type_name: TypeVizName, string_views: List[TypeVizStringView]) -> \
            List[GeneratedMethodDefinition]:
        if not string_views:
            return []

        def string_view_init_block(type_traits: TypeVizTypeTraits.StringTraits, self_data: str, self_size: str) -> str:
            lines = [
                f"unsigned long long {self_size} = (unsigned long long)(-1);\n"
                f"const {type_traits.char_type} *{self_data} = nullptr;\n"
            ]
            for string_view in string_views:
                if condition := self._get_condition(string_view):
                    lines.append(f"if ({self._prepare_expr_for_string(type_traits, condition)})\n")
                lines.append("{\n")
                data_pointer_expr = self._prepare_expr_for_string(type_traits, string_view.expression.text)
                lines.append(f"{self_data} = (const {type_traits.char_type} *)({data_pointer_expr});\n")
                string_len_expr = string_view.expression.view_options.array_size
                if string_len_expr:
                    lines.append(f"{self_size} = (unsigned long long)({self._prepare_expr_for_string(type_traits, string_len_expr)});\n")
                lines.append("}\n")
            lines.append(f"if ({self_size} == (unsigned long long)(-1)) "
                         f"{self_size} = {self_data} ? {type_traits.strlen}({self_data}) : 0;\n")
            return "".join(lines)

        return self._string_methods(type_name, string_view_init_block)

    @staticmethod
    def _replate_char_type_marker(type_traits: TypeVizTypeTraits.StringTraits, expr: str) -> str:
        # TODO: I hope there are no string types with $T10 or more
        return expr.replace("$T1", type_traits.char_type)

    def _string_helpers_from_array_items_for_jetvis(self, type_name_template: TypeNameTemplate,
                                                    type_traits: TypeVizTypeTraits.StringTraits,
                                                    array_items: TypeVizItemProviderArrayItems,
                                                    priority: int, get_raw_str_name: str, get_len_name: str) -> \
      List[GeneratedJetvisIntrinsicDefinition]:
        get_raw_str_lines = []
        for index, pointer_node in enumerate(array_items.value_pointer_nodes):
            raw_str_expr = self._replate_char_type_marker(type_traits, pointer_node.expr.text)
            if condition := self._get_condition(pointer_node):
                get_raw_str_lines.append(f"({self._replate_char_type_marker(type_traits, condition)}) ? "
                                         f"static_cast<const {type_traits.char_type} *>({raw_str_expr}) : ")
                if index + 1 == len(array_items.value_pointer_nodes):
                    get_raw_str_lines.append('__jetvis_evaluation_error("unable to get a string pointer because all conditions are false")')
            else:
                get_raw_str_lines.append(f"static_cast<const {type_traits.char_type} *>({raw_str_expr})")
                break

        get_len_lines = []
        for index, size_node in enumerate(array_items.size_nodes):
            len_expr = self._replate_char_type_marker(type_traits, size_node.text)
            if condition := self._get_condition(size_node):
                get_len_lines.append(f"({self._replate_char_type_marker(type_traits, condition)}) ? ({len_expr}) : ")
                if index + 1 == len(array_items.size_nodes):
                    get_len_lines.append('__jetvis_evaluation_error("unable to get a string length because all conditions are false")')
            else:
                get_len_lines.append(f"({len_expr})")
                break

        full_type_name = type_name_template.get_full_name_with_wildcards()
        return [
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, get_raw_str_name, "\n".join(get_raw_str_lines)),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, get_len_name, "\n".join(get_len_lines))
        ]

    def _string_helpers_from_string_view_for_jetvis(self, type_name_template: TypeNameTemplate,
                                                    type_traits: TypeVizTypeTraits.StringTraits,
                                                    string_views: list[TypeVizStringView],
                                                    priority: int, get_raw_str_name: str, get_len_name: str) -> \
      List[GeneratedJetvisIntrinsicDefinition]:
        get_raw_str_lines = []
        get_len_helper_lines = []

        get_len_helper_name = self._make_internal_name("private$get$len$helper")
        raw_str_param = self._make_internal_name("self$raw$str")
        for index, string_view in enumerate(string_views):
            raw_str_expr = self._replate_char_type_marker(type_traits, string_view.expression.text)
            len_expr = self._replate_char_type_marker(type_traits, string_view.expression.view_options.array_size or "")
            if not len_expr:
                len_expr = f"{raw_str_param} ? {type_traits.strlen}({raw_str_param}) : 0"

            if condition := self._get_condition(string_view):
                condition = self._replate_char_type_marker(type_traits, condition)
                get_raw_str_lines.append(f"({condition}) ? static_cast<const {type_traits.char_type} *>({raw_str_expr}) : ")
                get_len_helper_lines.append(f"({condition}) ? ({len_expr}) : ")
                if index + 1 == len(string_views):
                    get_raw_str_lines.append('__jetvis_evaluation_error("unable to get a string pointer because all conditions are false")')
                    get_len_helper_lines.append(
                        '__jetvis_evaluation_error("unable to get a string length because all conditions are false")')
            else:
                get_raw_str_lines.append(f"static_cast<const {type_traits.char_type} *>({raw_str_expr})")
                get_len_helper_lines.append(f"({len_expr})")
                break

        get_len_expr = f"{get_len_helper_name}({get_raw_str_name}())"
        full_type_name = type_name_template.get_full_name_with_wildcards()
        return [
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, get_raw_str_name, "\n".join(get_raw_str_lines)),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, get_len_helper_name, "\n".join(get_len_helper_lines),
                                               [raw_str_param], [f"const {type_traits.char_type} *"]),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, get_len_name, get_len_expr),
        ]

    def _string_methods_for_jetvis(self, type_name_template: TypeNameTemplate,
                                   type_traits: TypeVizTypeTraits.StringTraits,
                                   priority: int, get_raw_str_name: str, get_len_name: str):
        is_str_equal_name = self._make_internal_name("private$is$str$equal")
        is_str_equal_with_ue_hack_name = self._make_internal_name("private$is$str$equal$with$ue$hack")

        self_raw_str = self._make_internal_name("self$raw$str")
        self_size = self._make_internal_name("self$size")
        other_raw_str = self._make_internal_name("other$raw$data")
        other_size = self._make_internal_name("other$size")

        is_str_equal_param_names = [self_raw_str, self_size, other_raw_str, other_size]
        is_str_equal_param_types = [f"const {type_traits.char_type} *", "unsigned long long",
                                    f"const {type_traits.char_type} *", "unsigned long long"]

        is_str_equal_expr = (f"({self_size} == {other_size}) && "
                             f"(({self_size} == 0) || {type_traits.strncmp}({self_raw_str}, {other_raw_str}, {self_size}) == 0)")
        is_str_equal_with_ue_hack_expr = (f"{is_str_equal_name}("
                                          f"{self_raw_str}, "
                                          f"({self_size} == 1 && {self_raw_str} && !*{self_raw_str}) ? 0 : {self_size}, "
                                          f"{other_raw_str}, "
                                          f"{other_size})")

        operator_cmp_param_names = [other_raw_str]
        operator_cmp_param_types = [f"const {type_traits.char_type} *"]
        operator_eq_expr = (f"{is_str_equal_with_ue_hack_name}("
                            f"{get_raw_str_name}(), "
                            f"{get_len_name}(), "
                            f"{other_raw_str}, "
                            f"{other_raw_str} ? {type_traits.strlen}({other_raw_str}) : 0)")
        operator_neq_expr = f"!({operator_eq_expr})"

        full_type_name = type_name_template.get_full_name_with_wildcards()
        return [
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, is_str_equal_name, is_str_equal_expr,
                                               is_str_equal_param_names, is_str_equal_param_types),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, is_str_equal_with_ue_hack_name, is_str_equal_with_ue_hack_expr,
                                               is_str_equal_param_names, is_str_equal_param_types),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, "operator==", operator_eq_expr,
                                               operator_cmp_param_names, operator_cmp_param_types),
            GeneratedJetvisIntrinsicDefinition(full_type_name, priority, "operator!=", operator_neq_expr,
                                               operator_cmp_param_names, operator_cmp_param_types),
        ]

    def _string_methods_from_array_items_for_jetvis(self, type_name: TypeVizName, array_items: TypeVizItemProviderArrayItems,
                                                    priority: int) -> List[GeneratedJetvisIntrinsicDefinition]:
        string_type_traits = TypeVizTypeTraits.get_string_type_traits(type_name.type_name_template)
        get_raw_str_name = self._make_internal_name("private$get$raw$str")
        get_len_name = self._make_internal_name("private$get$len")

        methods = []
        for type_specialization, type_traits in string_type_traits:
            methods += self._string_helpers_from_array_items_for_jetvis(type_specialization, type_traits, array_items,
                                                                        priority, get_raw_str_name, get_len_name)
            methods += self._string_methods_for_jetvis(type_specialization, type_traits, priority, get_raw_str_name, get_len_name)
        return methods

    def _string_methods_from_string_views_for_jetvis(self, type_name: TypeVizName, string_views: list[TypeVizStringView],
                                                     priority: int) -> List[GeneratedJetvisIntrinsicDefinition]:
        methods = []
        if string_views:
            get_raw_str_name = self._make_internal_name("private$get$raw$str")
            get_len_name = self._make_internal_name("private$get$len")

            string_type_traits = TypeVizTypeTraits.get_string_type_traits(type_name.type_name_template)
            for type_specialization, type_traits in string_type_traits:
                methods += self._string_helpers_from_string_view_for_jetvis(type_specialization, type_traits, string_views,
                                                                            priority, get_raw_str_name, get_len_name)
                methods += self._string_methods_for_jetvis(type_specialization, type_traits, priority, get_raw_str_name, get_len_name)
        return methods
