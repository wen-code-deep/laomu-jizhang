from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Optional
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from xml.sax import saxutils

from jb_declarative_formatters import *
from jb_declarative_formatters.parsers.context_operator_parser import replace_context_operators_in_text
from jb_declarative_formatters.parsers.cpp_parser import CppParser
from jb_declarative_formatters.parsers.type_name_parser import parse_type_name_template, TypeNameParsingError
from jb_declarative_formatters.type_viz import TypeVizSmartPointer, TypeVizStringView, TypeVizSyntheticItem
from jb_declarative_formatters.type_viz_intrinsic import TypeVizIntrinsic, TypeVizIntrinsicParameter, \
    IntrinsicsScope, create_intrinsic, mangle_intrinsic_name, apply_intrinsics_to_expression, check_intrinsic_call_args
from jb_declarative_formatters.type_viz_expression import TypeVizCondition
from jb_declarative_formatters.type_viz_item_nodes import *
from jb_declarative_formatters.type_viz_item_providers import TypeVizItemProviderCustomListItems, TypeVizItemProviderSynthetic
from jb_declarative_formatters.type_viz_storage import DirectAcyclicGraph
from six import StringIO

# noinspection HttpUrlsUsage
NATVIS_SCHEMA_NAMESPACE = 'http://schemas.microsoft.com/vstudio/debugger/natvis/2010'


class NatvisIntrinsicXmlDefinition(object):
    def __init__(self, name: str, expression: str, optional: bool,
                 parameters: list[TypeVizIntrinsicParameter], return_type: str | None,
                 dependencies: list[str]):
        self.parameters = parameters
        self.return_type = return_type
        self.base_name: str = name
        self.mangled_name: str = mangle_intrinsic_name(name, len(parameters))
        self.optional = optional
        self.expression: str = expression
        self.dependencies = dependencies


class NatvisParsingError(Exception):
    pass


_NS = {'natvis': NATVIS_SCHEMA_NAMESPACE}


# noinspection PyBroadException
def natvis_parse_file(path: str, root_logger: logging.Logger, is_jetvis_enabled: bool) -> Iterable[TypeViz]:
    logger = root_logger.getChild("natvis parser")
    try:
        tree = ElementTree.parse(path)
        root = tree.getroot()
    except ElementTree.ParseError:
        # xml parsing error
        logger.exception("XmlError on parsing file %s", path)
        return []

    try:
        intrinsics = _parse_global_intrinsics_nodes(logger, root, is_jetvis_enabled)
    except Exception:
        logger.exception("Error on parsing global Intrinsics in file %s", path)
        return []

    for node_type_name in root.findall('natvis:Type', _NS):
        # noinspection PyBroadException
        try:
            yield natvis_parse_type(node_type_name, intrinsics, logger, is_jetvis_enabled)
        except Exception:
            # parsing error happened, skip the node and continue
            logger.exception("Error on parsing node %s in file %s", node_type_name, path)
            continue


def _unescape(value):
    if value is None:
        return value
    return saxutils.unescape(value)


def _make_tag(tag):
    return '{{{}}}{}'.format(NATVIS_SCHEMA_NAMESPACE, tag)


def _parse_type_name_alternatives(node_type_name):
    try:
        name = node_type_name.attrib['Name']
    except KeyError:
        raise NatvisParsingError("Missing required attribute 'Name'")

    name = _unescape(name)

    # support non-documented way to declare alternative type names used from UE4.17
    for alt_name in name.split('|'):
        yield alt_name

    # support non-documented AlternativeType nodes found in stl.natvis
    for alt_name_node in node_type_name.findall('natvis:AlternativeType', _NS):
        yield _unescape(alt_name_node.attrib['Name'])


__local_priorities_parser_values = {
    'Low': 1,
    'MediumLow': 2,
    'Medium': 3,
    'MediumHigh': 4,
    'High': 5,
}


def _parse_type_priority(node_type_name) -> int:
    priority_str = node_type_name.attrib.get('Priority', 'Medium')
    try:
        return __local_priorities_parser_values[priority_str]
    except KeyError:
        raise NatvisParsingError('Unknown priority {}'.format(priority_str))


__local_boolean_parser_values = {
    'true': True,
    '1': True,
    'false': False,
    '0': False,
}


def _parse_boolean(node, attrib_name, default) -> bool:
    value = node.attrib.get(attrib_name, default)
    try:
        return __local_boolean_parser_values[value]
    except KeyError:
        raise NatvisParsingError('Can\'t parse boolean value {}'.format(value))


__local_usage_parser_values = {
    TypeVizSmartPointer.Usage.Minimal.name: TypeVizSmartPointer.Usage.Minimal,
    TypeVizSmartPointer.Usage.Indexable.name: TypeVizSmartPointer.Usage.Indexable,
    "Full": TypeVizSmartPointer.Usage.Indexable
}


def _natvis_node_parse_smart_pointer_usage(node: Element) -> TypeVizSmartPointer.Usage:
    value = node.attrib.get('Usage', '')
    try:
        return __local_usage_parser_values[value]
    except KeyError:
        expected = ', '.join(__local_usage_parser_values.keys())
        raise NatvisParsingError(f"Can't parse 'Usage' value '{value}', expected: {expected}")


def _parse_display_strings(node: Element, all_intrinsics_list: list[IntrinsicsScope],
                           logger: logging.Logger, is_jetvis_enabled: bool) -> list[TypeVizSummary]:
    summaries = []

    for display_string_node in node.findall('natvis:DisplayString', _NS):
        display_string_raw_text = display_string_node.text or ''
        trimmed_text_lines = map(lambda s: s.strip(), display_string_raw_text.splitlines())
        non_empty_text_lines = filter(lambda s: bool(s), trimmed_text_lines)
        display_string_text = " ".join(non_empty_text_lines)
        condition = _natvis_node_parse_condition(display_string_node, all_intrinsics_list, logger, is_jetvis_enabled)
        optional = _natvis_node_parse_optional(display_string_node)
        display_string_expression = _natvis_node_parse_interpolated_string(display_string_text, all_intrinsics_list, logger,
                                                                           is_jetvis_enabled)
        summaries.append(TypeVizSummary(display_string_expression, condition, optional))

    return summaries


def _parse_item_providers(node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                          logger: logging.Logger, is_jetvis_enabled: bool) -> tuple[list | None, bool]:
    _ITEM_NODE_PARSERS = {
        _make_tag('Item'): _natvis_node_parse_item,
        _make_tag('ExpandedItem'): _natvis_node_parse_expanded_item,
        _make_tag('Synthetic'): _natvis_node_parse_synthetic_item,
        _make_tag('ArrayItems'): _natvis_node_parse_array_items,
        _make_tag('IndexListItems'): _natvis_node_parse_index_list_items,
        _make_tag('LinkedListItems'): _natvis_node_parse_linked_list_items,
        _make_tag('TreeItems'): _natvis_node_parse_tree_items,
        _make_tag('CustomListItems'): _natvis_node_parse_custom_list_items,
    }

    expand_node = node.find('natvis:Expand', _NS)
    if expand_node is None:
        return None, False

    hide_raw_view = _parse_boolean(expand_node, 'HideRawView', 'false')
    item_providers = []

    for node in expand_node:
        parse_fn = _ITEM_NODE_PARSERS.get(node.tag)
        if parse_fn:
            item_provider = parse_fn(node, type_intrinsics, global_intrinsics, logger, is_jetvis_enabled)
            if item_provider:
                item_providers.append(item_provider)
    return item_providers, hide_raw_view


def natvis_parse_type(node_type_name: Element, global_scope_intrinsics: IntrinsicsScope,
                      logger: logging.Logger, is_jetvis_enabled: bool) -> TypeViz:
    type_viz_names = list[TypeVizName]()
    alt_names = _parse_type_name_alternatives(node_type_name)
    for alt_name in alt_names:
        try:
            logger.info("Parsing type name '%s'", alt_name)
            name_ast = parse_type_name_template(alt_name)
        except TypeNameParsingError as e:
            raise NatvisParsingError(e)
        type_viz_names.append(TypeVizName(alt_name, name_ast))

    inheritable = _parse_boolean(node_type_name, 'Inheritable', 'true')
    include_view = _natvis_node_parse_include_view(node_type_name)
    exclude_view = _natvis_node_parse_exclude_view(node_type_name)
    priority = _parse_type_priority(node_type_name)

    type_scope_intrinsics = _parse_type_intrinsics_nodes(logger, node_type_name, global_scope_intrinsics, is_jetvis_enabled)

    type_viz_obj = TypeViz(type_viz_names, inheritable, include_view, exclude_view, priority,
                           global_scope_intrinsics, type_scope_intrinsics, logger)

    all_intrinsics_list = [type_scope_intrinsics, global_scope_intrinsics]
    type_viz_obj.summaries = _parse_display_strings(node_type_name, all_intrinsics_list, logger, is_jetvis_enabled)
    item_providers, hide_raw_view = _parse_item_providers(node_type_name, type_scope_intrinsics, global_scope_intrinsics,
                                                          logger, is_jetvis_enabled)
    type_viz_obj.item_providers, type_viz_obj.hide_raw_view = item_providers, hide_raw_view
    type_viz_obj.smart_pointer = _parse_smart_pointer(logger, node_type_name, all_intrinsics_list, is_jetvis_enabled)
    type_viz_obj.string_views = _parse_string_views(logger, node_type_name, all_intrinsics_list, is_jetvis_enabled)
    return type_viz_obj


def _sort_intrinsics_by_their_dependencies(intrinsics: list[TypeVizIntrinsic]) -> list[TypeVizIntrinsic]:
    # we can't use graphlib.TopologicalSorter because we have next case:
    # A = B()
    # A = 10
    # B = A()
    # and this case works in VS

    if not len(intrinsics):
        return []

    def get_children(intrinsic: TypeVizIntrinsic) -> list[TypeVizIntrinsic]:
        res = []
        for dep in intrinsic.unique_dependencies:
            for tmp in intrinsics:
                if dep == tmp.name:
                    res.append(tmp)
        return res

    graph = DirectAcyclicGraph(intrinsics, get_children)
    sorted_list = graph.sort()

    return sorted_list


def _parse_global_intrinsics_nodes(logger: logging.Logger, root: Element, is_jetvis_enabled: bool) -> IntrinsicsScope:
    intrinsics = _parse_intrinsics_nodes(logger, root, None, IntrinsicsScope.Kind.GLOBAL, is_jetvis_enabled)
    return intrinsics


def _parse_type_intrinsics_nodes(logger: logging.Logger, node_type_name: Element,
                                 global_intrinsics: IntrinsicsScope, is_jetvis_enabled: bool) -> IntrinsicsScope:
    intrinsics = _parse_intrinsics_nodes(logger, node_type_name, global_intrinsics, IntrinsicsScope.Kind.TYPE, is_jetvis_enabled)
    return intrinsics


def _parse_smart_pointer(logger: logging.Logger, node_type_name: Element,
                         intrinsics: List[IntrinsicsScope], is_jetvis_enabled: bool) -> Optional[TypeVizSmartPointer]:
    smart_ptr_node = node_type_name.find('natvis:SmartPointer', _NS)
    if smart_ptr_node is None:
        return None

    smart_ptr_expr = _natvis_node_parse_formatted_expression(smart_ptr_node.text or '', intrinsics, logger, is_jetvis_enabled)
    smart_ptr_usage = _natvis_node_parse_smart_pointer_usage(smart_ptr_node)
    return TypeVizSmartPointer(smart_ptr_expr, smart_ptr_usage)


def _parse_string_views(logger: logging.Logger, node_type_name: Element,
                        intrinsics: List[IntrinsicsScope], is_jetvis_enabled: bool) -> List[TypeVizStringView]:
    string_views = []
    for string_view_node in node_type_name.findall('natvis:StringView', _NS):
        string_expression = _natvis_node_parse_formatted_expression(string_view_node.text or '', intrinsics, logger, is_jetvis_enabled)
        condition = _natvis_node_parse_condition(string_view_node, intrinsics, logger, is_jetvis_enabled)
        string_views.append(TypeVizStringView(string_expression, condition))
    return string_views


def _apply_context_and_intrinsics(raw_expr: str, intrinsics_scopes: list[IntrinsicsScope], logger: logging.Logger) -> str:
    context_replaced_expr = replace_context_operators_in_text(raw_expr)
    intrinsics_applied_expr = apply_intrinsics_to_expression(context_replaced_expr, intrinsics_scopes, logger)
    return intrinsics_applied_expr


def _parse_intrinsics_nodes(logger: logging.Logger, node_type_name: Element,
                            global_intrinsics: IntrinsicsScope | None,
                            intrinsic_scope_kind: IntrinsicsScope.Kind, is_jetvis_enabled: bool) -> IntrinsicsScope:
    intrinsics_from_xml = list[NatvisIntrinsicXmlDefinition]()

    intrinsic_overloads = dict[str, int]()

    for intrinsic_node in node_type_name.findall('natvis:Intrinsic', _NS):
        intrinsic = _natvis_node_parse_intrinsic(intrinsic_node, logger, is_jetvis_enabled)
        current_count = intrinsic_overloads.get(intrinsic.mangled_name, 0)
        intrinsic_overloads[intrinsic.mangled_name] = current_count + 1
        intrinsics_from_xml.append(intrinsic)

    intrinsics_list = list[TypeVizIntrinsic]()
    global_intrinsics_count = len(global_intrinsics.sorted_list) if global_intrinsics else 0
    for intrinsic in intrinsics_from_xml:
        unique_id = global_intrinsics_count + len(intrinsics_list)
        intrinsics_list.append(
            create_intrinsic(
                intrinsic_overloads, intrinsic.mangled_name, intrinsic.base_name, intrinsic.expression,
                intrinsic.optional, intrinsic.parameters, intrinsic.return_type, intrinsic.dependencies, unique_id))

    sorted_list = _sort_intrinsics_by_their_dependencies(intrinsics_list)

    intrinsics = IntrinsicsScope(intrinsics_list, sorted_list, intrinsic_scope_kind)

    all_intrinsics_list = [intrinsics]
    if global_intrinsics is not None:
        all_intrinsics_list.append(global_intrinsics)

    if not is_jetvis_enabled:
        for intrinsic in intrinsics.sorted_list:
            updated_expression = _apply_context_and_intrinsics(intrinsic.expression, all_intrinsics_list, logger)
            intrinsic.change_expression(updated_expression)
    return intrinsics


# noinspection SpellCheckingInspection
NATVIS_FORMAT_SPECIFIERS_MAPPING = {
    'd': TypeVizFormatSpec.DECIMAL,
    'o': TypeVizFormatSpec.OCTAL,
    'x': TypeVizFormatSpec.HEX,
    'h': TypeVizFormatSpec.HEX,
    'X': TypeVizFormatSpec.HEX_UPPERCASE,
    'H': TypeVizFormatSpec.HEX_UPPERCASE,
    'xb': TypeVizFormatSpec.HEX_NO_PREFIX,
    'hb': TypeVizFormatSpec.HEX_NO_PREFIX,
    'Xb': TypeVizFormatSpec.HEX_UPPERCASE_NO_PREFIX,
    'Hb': TypeVizFormatSpec.HEX_UPPERCASE_NO_PREFIX,
    'b': TypeVizFormatSpec.BINARY,
    'bb': TypeVizFormatSpec.BINARY_NO_PREFIX,
    'e': TypeVizFormatSpec.SCIENTIFIC,
    'g': TypeVizFormatSpec.SCIENTIFIC_MIN,
    'c': TypeVizFormatSpec.CHARACTER,
    's': TypeVizFormatSpec.STRING,
    'sb': TypeVizFormatSpec.STRING_NO_QUOTES,
    's8': TypeVizFormatSpec.UTF8_STRING,
    's8b': TypeVizFormatSpec.UTF8_STRING_NO_QUOTES,
    'su': TypeVizFormatSpec.WIDE_STRING,
    'sub': TypeVizFormatSpec.WIDE_STRING_NO_QUOTES,
    'bstr': TypeVizFormatSpec.WIDE_STRING,
    's32': TypeVizFormatSpec.UTF32_STRING,
    's32b': TypeVizFormatSpec.UTF32_STRING_NO_QUOTES,
    'en': TypeVizFormatSpec.ENUM,
    'hv': TypeVizFormatSpec.HEAP_ARRAY,
    'hr': TypeVizFormatSpec.IGNORED,
    'wc': TypeVizFormatSpec.IGNORED,
    'wm': TypeVizFormatSpec.IGNORED,
}

NATVIS_FORMAT_FLAGS_MAPPING = {
    'na': TypeVizFormatFlags.NO_ADDRESS,
    'nd': TypeVizFormatFlags.NO_DERIVED,
    'nr': TypeVizFormatFlags.NO_RAW_VIEW,
    'nvo': TypeVizFormatFlags.NUMERIC_VALUE_ONLY,
    '!': TypeVizFormatFlags.RAW_FORMAT,
}
NATVIS_FORMAT_FLAGS = NATVIS_FORMAT_FLAGS_MAPPING.keys()

_NATVIS_LITERAL_ARRAY_REGEX = re.compile(r"^\d+$")
_NATVIS_SPECS_REGEX = re.compile(r"^(?:\[(.*)])?(.*)$")
_NATVIS_VIEW_SPECS_REGEX = re.compile(r"^(?:view\s*\((.*)\))?(.*)$")


def _natvis_parse_expression_specs(specs):
    simple_match = _NATVIS_LITERAL_ARRAY_REGEX.match(specs)
    if simple_match:
        array_len = simple_match.group(0)
        if array_len:
            array_len = array_len.strip()
            return array_len, None, None, None

    match = _NATVIS_SPECS_REGEX.match(specs)
    if not match:
        return None, None, None, None

    array_len = match.group(1)
    if array_len:
        array_len = array_len.strip()
    spec = match.group(2)
    if spec:
        spec = spec.strip()

    view_spec = None
    view_match = _NATVIS_VIEW_SPECS_REGEX.match(spec)
    if view_match:
        view_spec = view_match.group(1)
        if view_spec:
            view_spec = view_spec.strip()

    spec = view_match.group(2)
    spec_value, spec_flags = _natvis_parse_format_specs(spec)

    return array_len, spec_value, spec_flags, view_spec


def _natvis_parse_format_specs(spec: str):
    spec_flags: TypeVizFormatFlags | None = TypeVizFormatFlags(0)
    idx = 0
    while True:
        for flag_name, flag in NATVIS_FORMAT_FLAGS_MAPPING.items():
            if spec.startswith(flag_name, idx):
                spec_flags |= flag
                idx += len(flag_name)
                break
        else:
            break
    spec = spec[idx:]
    if spec_flags == 0:
        spec_flags = None

    return NATVIS_FORMAT_SPECIFIERS_MAPPING.get(spec, None), spec_flags


def _natvis_node_parse_expression(expression_text: str | None,
                                  intrinsics_scopes: list[IntrinsicsScope] | None,
                                  logger: logging.Logger, is_jetvis_enabled: bool) -> Optional[str]:
    if expression_text is None:
        return None
    expression_text = _unescape(expression_text)
    expression_text = expression_text.replace('\n', '')

    if is_jetvis_enabled:
        return expression_text

    expression_text = replace_context_operators_in_text(expression_text)

    if not intrinsics_scopes:
        return expression_text

    return apply_intrinsics_to_expression(expression_text, intrinsics_scopes, logger)


def _natvis_node_parse_formatted_expression(expression_text: str,
                                            intrinsics_scopes: list[IntrinsicsScope],
                                            logger: logging.Logger, is_jetvis_enabled: bool) -> Optional[TypeVizExpression]:
    if expression_text is None:
        return None
    expression_text = _unescape(expression_text)
    expression_text = expression_text.replace('\n', '')

    parts = expression_text.rsplit(',', 1)
    array_size = None
    format_spec = None
    format_flags = None
    view_spec = None
    if len(parts) == 2:
        specs = parts[1].strip()
        array_size, format_spec, format_flags, view_spec = _natvis_parse_expression_specs(specs)

    if array_size or format_spec or format_flags or view_spec:
        expression = parts[0].strip()
    else:
        expression = expression_text.strip()

    if not is_jetvis_enabled:
        expression = _apply_context_and_intrinsics(expression, intrinsics_scopes, logger)
    return TypeVizExpression(expression, array_size, format_spec, format_flags, view_spec)


def _natvis_node_parse_interpolated_string(text: str, intrinsics_scopes: list[IntrinsicsScope],
                                           logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizInterpolatedString:
    text_len = len(text)
    i = 0
    parts_list = []
    cur_part = StringIO()
    while i < text_len:
        if text[i] == '{':
            i += 1
            if i < text_len and text[i] == '{':
                # '{{' is escaped '{'
                cur_part.write('{')
                i += 1
                continue

            idx_start = i
            # get expression slice to evaluate
            while i < text_len:
                if text[i] == '}':
                    break
                i += 1
            else:
                raise NatvisParsingError("missing '}'")

            expr = _natvis_node_parse_formatted_expression(text[idx_start:i], intrinsics_scopes, logger, is_jetvis_enabled)
            parts_list.append((cur_part.getvalue(), expr))
            i += 1  # skip closing }
            cur_part = StringIO()  # start new non-evaluated part
            continue

        if text[i] == '}':
            cur_part.write('}')
            i += 1
            if i < text_len and text[i] == '}':
                # '}}' is escaped '}'
                i += 1
            continue

        cur_part.write(text[i])
        i += 1

    last_part = cur_part.getvalue()
    if last_part:
        parts_list.append((last_part, None))
    return TypeVizInterpolatedString(parts_list)


def _natvis_node_parse_optional_name(item_node: Element) -> str | None:
    return _natvis_node_parse_optional_attribute(item_node, 'Name')


def _natvis_node_parse_required_name(item_node: Element) -> str:
    return _natvis_node_parse_required_attribute(item_node, 'Name')


def _natvis_node_parse_required_type(item_node: Element) -> str:
    return _natvis_node_parse_required_attribute(item_node, 'Type')


def _natvis_node_parse_optional_attribute(node: Element, attr_name: str) -> str | None:
    return _unescape(node.get(attr_name, None))


def _natvis_node_parse_required_attribute(node: Element, attr_name: str) -> str:
    value = node.get(attr_name, None)
    if value is None:
        raise NatvisParsingError(f"Missing required attribute '{attr_name}'")

    return _unescape(value)


def _natvis_node_parse_item(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                            logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderSingle:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_name = _natvis_node_parse_required_name(item_node)
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)
    item_expression = _natvis_node_parse_formatted_expression(item_node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)
    return TypeVizItemProviderSingle(item_name, item_expression, item_condition, item_optional)


def _natvis_node_parse_expanded_item(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                     logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderExpanded:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)
    item_expression = _natvis_node_parse_formatted_expression(item_node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)
    return TypeVizItemProviderExpanded(item_expression, item_condition, item_optional)


def _natvis_node_parse_synthetic_item(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                      logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderSynthetic:
    item_name = _natvis_node_parse_required_name(item_node)
    item_optional = _natvis_node_parse_optional(item_node)
    # VS never shows "Raw View" for Synthetic items and completely ignores "HideRawView" attribute, therefore ignore it too
    item_providers, ignore_hide_raw_view = _parse_item_providers(item_node, type_intrinsics, global_intrinsics, logger, is_jetvis_enabled)

    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    add_watch_expr = _natvis_node_parse_expression(item_node.attrib.get('Expression'), intrinsics_scopes, logger, is_jetvis_enabled)
    summaries = _parse_display_strings(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    string_views = _parse_string_views(logger, item_node, intrinsics_scopes, is_jetvis_enabled)

    type_viz_synthetic_item = TypeVizSyntheticItem(item_name, add_watch_expr, summaries, item_providers, string_views,
                                                   global_intrinsics, type_intrinsics)

    return TypeVizItemProviderSynthetic(item_name, item_condition, item_optional, type_viz_synthetic_item)


def _natvis_node_parse_size_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                 logger: logging.Logger, is_jetvis_enabled: bool) -> list[TypeVizItemSizeTypeNode] | None:
    nodes = item_node.findall('natvis:Size', _NS)
    if nodes is None:
        return None

    values = []
    for node in nodes:
        condition = _natvis_node_parse_condition(node, intrinsics_scopes, logger, is_jetvis_enabled)
        optional = _natvis_node_parse_optional(node)
        value = _natvis_node_parse_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

        values.append(TypeVizItemSizeTypeNode(value, condition, optional))

    return values


def _natvis_node_parse_value_pointer_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                          logger: logging.Logger, is_jetvis_enabled: bool) -> list[TypeVizItemValuePointerTypeNode] | None:
    nodes = item_node.findall('natvis:ValuePointer', _NS)
    if nodes is None:
        return None

    values = []
    for node in nodes:
        condition = _natvis_node_parse_condition(node, intrinsics_scopes, logger, is_jetvis_enabled)
        value = _natvis_node_parse_formatted_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

        values.append(TypeVizItemValuePointerTypeNode(value, condition))

    return values


def _natvis_node_parse_array_items(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                   logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderArrayItems | None:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)

    items_size = _natvis_node_parse_size_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_size is None:
        return None

    items_value_pointer = _natvis_node_parse_value_pointer_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_value_pointer is None:
        return None

    return TypeVizItemProviderArrayItems(items_size,
                                         items_value_pointer,
                                         item_condition, item_optional)


def _natvis_node_parse_index_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                  logger: logging.Logger, is_jetvis_enabled: bool) -> list[TypeVizItemIndexNodeTypeNode] | None:
    nodes = item_node.findall('natvis:ValueNode', _NS)
    if nodes is None:
        return None

    values = []
    for node in nodes:
        condition = _natvis_node_parse_condition(node, intrinsics_scopes, logger, is_jetvis_enabled)
        value = _natvis_node_parse_formatted_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

        values.append(TypeVizItemIndexNodeTypeNode(value, condition))

    return values


def _natvis_node_parse_index_list_items(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                        logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderIndexListItems | None:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)

    items_size = _natvis_node_parse_size_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_size is None:
        return None

    items_value_node = _natvis_node_parse_index_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_value_node is None:
        return None

    return TypeVizItemProviderIndexListItems(items_size, items_value_node,
                                             item_condition, item_optional)


def _natvis_node_parse_linked_list_head_pointer(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                                logger: logging.Logger,
                                                is_jetvis_enabled: bool) -> TypeVizItemListItemsHeadPointerTypeNode | None:
    nodes = item_node.findall('natvis:HeadPointer', _NS)
    if nodes is None:
        return None

    if len(nodes) != 1:
        raise NatvisParsingError('Only one HeadPointer node allowed')
    node = nodes[0]

    node_expression = _natvis_node_parse_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

    return TypeVizItemListItemsHeadPointerTypeNode(node_expression)


def _natvis_node_parse_linked_list_next_pointer(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                                logger: logging.Logger,
                                                is_jetvis_enabled: bool) -> TypeVizItemListItemsNextPointerTypeNode | None:
    nodes = item_node.findall('natvis:NextPointer', _NS)
    if nodes is None:
        return None

    if len(nodes) != 1:
        raise NatvisParsingError('Only one NextPointer node allowed')
    node = nodes[0]

    node_expression = _natvis_node_parse_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

    return TypeVizItemListItemsNextPointerTypeNode(node_expression)


ElementToTypeViz = tuple[Element, Optional[TypeVizExpression], Optional[TypeVizInterpolatedString]]


def _internal_parse_value_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                               logger: logging.Logger, is_jetvis_enabled: bool) -> ElementToTypeViz | None:
    nodes = item_node.findall('natvis:ValueNode', _NS)
    if nodes is None:
        return None

    if len(nodes) != 1:
        raise NatvisParsingError('Only one ValueNode node allowed')
    node = nodes[0]

    node_name_str = _natvis_node_parse_optional_name(node)
    node_name = _natvis_node_parse_interpolated_string(
        node_name_str, intrinsics_scopes, logger, is_jetvis_enabled) if node_name_str is not None else None
    node_expression = _natvis_node_parse_formatted_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)

    return node, node_expression, node_name


def _natvis_node_parse_linked_list_value_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                              logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemListItemsIndexNodeTypeNode:
    node, node_expression, node_name = _internal_parse_value_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    return TypeVizItemListItemsIndexNodeTypeNode(node_expression, node_name)


def _natvis_node_parse_linked_list_items(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                         logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderLinkedListItems | None:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)

    items_size = _natvis_node_parse_size_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    # size can be omitted

    item_head_pointer = _natvis_node_parse_linked_list_head_pointer(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if item_head_pointer is None:
        return None

    item_next_pointer = _natvis_node_parse_linked_list_next_pointer(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if item_next_pointer is None:
        return None

    items_value_node = _natvis_node_parse_linked_list_value_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_value_node is None:
        return None

    return TypeVizItemProviderLinkedListItems(items_size, item_head_pointer, item_next_pointer, items_value_node,
                                              item_condition, item_optional)


def _natvis_node_parse_tree_pointer_helper(item_node: Element, node_name: str, intrinsics_scopes: list[IntrinsicsScope],
                                           logger: logging.Logger, is_jetvis_enabled: bool) -> str | None:
    nodes = item_node.findall('natvis:{}'.format(node_name), _NS)
    if nodes is None:
        return None

    if len(nodes) != 1:
        raise NatvisParsingError('Only one {} node allowed'.format(node_name))
    node = nodes[0]

    node_expression = _natvis_node_parse_expression(node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)
    return node_expression


def _natvis_node_parse_tree_head_pointer(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                         logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemTreeHeadPointerTypeNode | None:
    node_expression = _natvis_node_parse_tree_pointer_helper(item_node, 'HeadPointer', intrinsics_scopes, logger, is_jetvis_enabled)
    if node_expression is None:
        return None
    return TypeVizItemTreeHeadPointerTypeNode(node_expression)


def _natvis_node_parse_tree_child_pointer(item_node: Element, node_name: str, intrinsics_scopes: list[IntrinsicsScope],
                                          logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemTreeChildPointerTypeNode | None:
    node_expression = _natvis_node_parse_tree_pointer_helper(item_node, node_name, intrinsics_scopes, logger, is_jetvis_enabled)
    if node_expression is None:
        return None
    return TypeVizItemTreeChildPointerTypeNode(node_expression)


def _natvis_node_parse_tree_value_node(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                       logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemTreeNodeTypeNode | None:
    node, node_expression, node_name = _internal_parse_value_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    node_condition = _natvis_node_parse_condition(node, intrinsics_scopes, logger, is_jetvis_enabled)

    return TypeVizItemTreeNodeTypeNode(node_expression, node_name, node_condition)


def _natvis_node_parse_tree_items(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                  logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderTreeItems | None:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)

    items_size = _natvis_node_parse_size_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    # size can be omitted

    item_head_pointer = _natvis_node_parse_tree_head_pointer(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if item_head_pointer is None:
        return None

    item_left_pointer = _natvis_node_parse_tree_child_pointer(item_node, 'LeftPointer', intrinsics_scopes, logger, is_jetvis_enabled)
    if item_left_pointer is None:
        return None

    item_right_pointer = _natvis_node_parse_tree_child_pointer(item_node, 'RightPointer', intrinsics_scopes, logger, is_jetvis_enabled)
    if item_right_pointer is None:
        return None

    items_value_node = _natvis_node_parse_tree_value_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_value_node is None:
        return None

    return TypeVizItemProviderTreeItems(items_size, item_head_pointer,
                                        item_left_pointer, item_right_pointer,
                                        items_value_node,
                                        item_condition, item_optional)


def _natvis_node_parse_variable_nodes(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                      logger: logging.Logger, is_jetvis_enabled: bool) -> list[TypeVizItemVariableTypeNode] | None:
    nodes = item_node.findall('natvis:Variable', _NS)
    if nodes is None:
        return None

    variables = []
    for node in nodes:
        name = _natvis_node_parse_required_name(node)

        initial_value_text = node.attrib.get('InitialValue', '')
        initial_value = _natvis_node_parse_expression(initial_value_text, intrinsics_scopes, logger, is_jetvis_enabled)
        variables.append(TypeVizItemVariableTypeNode(name, initial_value))

    return variables


def _natvis_node_parse_code_block_nodes(item_node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                        logger: logging.Logger, is_jetvis_enabled: bool) -> list:
    def _parse_condition(code_block_node):
        return _natvis_node_parse_expression(code_block_node.attrib.get('Condition'), intrinsics_scopes, logger, is_jetvis_enabled)

    def _parse_exec(code_block_node):
        condition = _parse_condition(code_block_node)
        expression = _natvis_node_parse_expression(code_block_node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)
        return TypeVizItemExecCodeBlockTypeNode(condition, expression)

    def _parse_loop(code_block_node):
        condition = _parse_condition(code_block_node)
        code_blocks = _natvis_node_parse_code_block_nodes(code_block_node, intrinsics_scopes, logger, is_jetvis_enabled)
        return TypeVizItemLoopCodeBlockTypeNode(condition, code_blocks)

    def _parse_if(code_block_node):
        condition = _parse_condition(code_block_node)
        code_blocks = _natvis_node_parse_code_block_nodes(code_block_node, intrinsics_scopes, logger, is_jetvis_enabled)
        return TypeVizItemIfCodeBlockTypeNode(condition, code_blocks)

    def _parse_else_if(code_block_node):
        condition = _parse_condition(code_block_node)
        code_blocks = _natvis_node_parse_code_block_nodes(code_block_node, intrinsics_scopes, logger, is_jetvis_enabled)
        return TypeVizItemElseIfCodeBlockTypeNode(condition, code_blocks)

    def _parse_else(code_block_node):
        code_blocks = _natvis_node_parse_code_block_nodes(code_block_node, intrinsics_scopes, logger, is_jetvis_enabled)
        return TypeVizItemElseCodeBlockTypeNode(code_blocks)

    def _parse_break(code_block_node):
        condition = _parse_condition(code_block_node)
        return TypeVizItemBreakCodeBlockTypeNode(condition)

    def _parse_item(code_block_node):
        condition = _parse_condition(code_block_node)
        expression = _natvis_node_parse_formatted_expression(code_block_node.text or '', intrinsics_scopes, logger, is_jetvis_enabled)
        raw_name = _natvis_node_parse_optional_name(code_block_node)
        name = _natvis_node_parse_interpolated_string(raw_name, intrinsics_scopes, logger, is_jetvis_enabled) if raw_name else None
        return TypeVizItemItemCodeBlockTypeNode(condition, name, expression)

    _code_block_node_parsers = {
        _make_tag('Exec'): _parse_exec,
        _make_tag('Loop'): _parse_loop,
        _make_tag('If'): _parse_if,
        _make_tag('Elseif'): _parse_else_if,
        _make_tag('Else'): _parse_else,
        _make_tag('Break'): _parse_break,
        _make_tag('Item'): _parse_item,
    }

    result = []

    for node in item_node:
        parse_fn = _code_block_node_parsers.get(node.tag)
        if parse_fn:
            code_block = parse_fn(node)
            if code_block:
                result.append(code_block)

    return result


def _natvis_node_parse_custom_list_items(item_node: Element, type_intrinsics: IntrinsicsScope, global_intrinsics: IntrinsicsScope,
                                         logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizItemProviderCustomListItems | None:
    intrinsics_scopes = [type_intrinsics, global_intrinsics]
    item_condition = _natvis_node_parse_condition(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    item_optional = _natvis_node_parse_optional(item_node)

    variables = _natvis_node_parse_variable_nodes(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    # variables can be omitted

    items_size = _natvis_node_parse_size_node(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if items_size is None:
        return None

    code_blocks = _natvis_node_parse_code_block_nodes(item_node, intrinsics_scopes, logger, is_jetvis_enabled)
    if code_blocks is None:
        return None

    return TypeVizItemProviderCustomListItems(variables,
                                              items_size, code_blocks,
                                              item_condition, item_optional)


def _natvis_node_parse_condition(node: Element, intrinsics_scopes: list[IntrinsicsScope],
                                 logger: logging.Logger, is_jetvis_enabled: bool) -> TypeVizCondition:
    condition = _natvis_node_parse_expression(node.attrib.get('Condition'), intrinsics_scopes, logger, is_jetvis_enabled)
    include_view = _natvis_node_parse_include_view(node)
    exclude_view = _natvis_node_parse_exclude_view(node)
    return TypeVizCondition(condition, include_view, exclude_view)


def _natvis_node_parse_optional(node: Element) -> bool:
    return _parse_boolean(node, 'Optional', 'false')


def _natvis_node_parse_exclude_view(node: Element) -> str:
    return node.attrib.get('ExcludeView', '')


def _natvis_node_parse_include_view(node: Element) -> str:
    return node.attrib.get('IncludeView', '')


def _natvis_node_parse_intrinsic_parameter(node: ElementTree.Element) -> TypeVizIntrinsicParameter:
    param_name = _natvis_node_parse_optional_name(node)
    param_type = _natvis_node_parse_required_type(node)

    return TypeVizIntrinsicParameter(param_name, param_type)


def _natvis_node_parse_intrinsic(node: ElementTree.Element, logger: logging.Logger,
                                 is_jetvis_enabled: bool) -> NatvisIntrinsicXmlDefinition:
    name = _natvis_node_parse_optional_name(node)
    # TODO: Expression may not exist, see example:
    #       https://learn.microsoft.com/en-us/visualstudio/debugger/implementing-natvis-intrinsic-function?view=vs-2022#guidelines-to-implement-an-intrinsic-function
    expr = _natvis_node_parse_expression(node.attrib['Expression'], None, logger, is_jetvis_enabled)
    optional = _natvis_node_parse_optional(node)

    dependencies = list[str]()
    current_pos = 0
    while len(expr) > current_pos:
        intrinsic_call = CppParser.search_unqualified_function_call(expr, current_pos)
        if not intrinsic_call:
            break
        current_pos = intrinsic_call.args_begin_pos
        if not check_intrinsic_call_args(expr, intrinsic_call, logger):
            continue
        dependencies.append(mangle_intrinsic_name(intrinsic_call.base_name, len(intrinsic_call.args)))

    params = list[TypeVizIntrinsicParameter]()
    for paramNode in node.findall('natvis:Parameter', _NS):
        parsed_param = _natvis_node_parse_intrinsic_parameter(paramNode)
        params.append(parsed_param)

    return_type = node.attrib.get("ReturnType", None)
    return NatvisIntrinsicXmlDefinition(name, expr, optional, params, return_type, dependencies)
