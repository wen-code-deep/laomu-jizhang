from __future__ import annotations

from typing import Sequence

import lldb
from jb_declarative_formatters.type_viz import TypeVizSyntheticItem
from jb_declarative_formatters.type_viz_item_providers import TypeVizItemProviderSynthetic
from jb_declarative_formatters.type_viz_generated_method import GeneratedMethod
from lldb import eBasicTypeVoid
from renderers.jb_lldb_item_expression import ItemExpression


class NatvisSyntheticItemTypeVizCache:
    """
    Natvis Synthetic Items:
    https://learn.microsoft.com/en-us/visualstudio/debugger/create-custom-views-of-native-objects?view=vs-2022#BKMK_Synthetic_Item_expansion

    TLDR.
        This class is designed to handle Synthetic Items in the Natvis framework by caching visualization contexts and managing
    the original object. By creating a Synthetic Child that mimics the original object and storing visualization context in the cache,
    the framework ensures proper visualizers are applied to Synthetic Items, and expressions are evaluated in the correct context.

    Details.
        Normally, the framework matches visualizers using the Item type name, but Synthetic Item does not have a specific type.
    To deal with this, we introduce a persistent cache that stores a context called [_TypeVizSyntheticContext], containing all
    necessary information for visualizing of Synthetic Items.

    Note, that Synthetic Items, Synthetic Children are different things.
        - Synthetic Items - A Natvis Item type.
        - Synthetic Children - a thing from LLDB. Can be created in a specific SBValue, using [SBValue.CreateChildAtOffset] or
        [SBValue.GetChildAtIndex], or got from [SyntheticChildrenProvider].

    To ensure the framework can later retrieve the correct visualizer for a Synthetic Item, we use a key that uniquely identifies
    the synthetic context. This key is stored in the metadata of the Synthetic Item during its creation. When the system searches for
    the appropriate visualizer, this key can be used to retrieve the cached context. After that, we can create a special visualizer for
    the Synthetic Item - [NatVisSyntheticItemDescriptor].

    In addition to visualization information, it's crucial to be able to get the original object which owns the Synthetic Item,
    using only the SBValue of the Synthetic Item. Here's how we achieve this:
        - Using [SBValue.CreateValueFromData], we create a pointer [void *] at the memory address where the original object is located.
        - The resulted SBValue with the pointer [void *] becomes the Synthetic Item itself.
        - Additionally we generate a Synthetic Child (using the method [get_self_reference_in_synthetic_item]) in the resulted SBValue
        with the pointer [void *], ensuring the Synthetic Child's type matches the original object type.
        - Later, to retrieve the original object with the correct type, we use the created before Synthetic Child.

    Once the Synthetic Child is created, it allows us to execute expressions for Synthetic Item within the context of the original object,
    including for all nested items.
    """

    _METADATA_SYNTHETIC_TYPE_VIZ_CONTEXT = "com.jetbrains.synthetic.type.viz.context"
    _SELF_REFERENCE_SPECIAL_NAME = "_self_reference"

    class _TypeVizSyntheticContext:
        def __init__(self, type_viz: TypeVizSyntheticItem, wildcards: Sequence[str]):
            self.type_viz = type_viz
            self.wildcards = tuple(wildcards)

    _type_viz_synthetic_context_cache: dict[str, _TypeVizSyntheticContext] = {}

    @classmethod
    def _store_type_viz_synthetic_context(cls, non_synthetic_value: lldb.SBValue, typ_viz_synth_item: TypeVizSyntheticItem,
                                          wildcards: Sequence[str]):
        synthetic_type_viz_cache_key = "-".join((
            non_synthetic_value.GetTypeName(), typ_viz_synth_item.name, f"{hash(typ_viz_synth_item):x}", "wildcards", *wildcards
        ))
        if synthetic_type_viz_cache_key not in cls._type_viz_synthetic_context_cache:
            cls._type_viz_synthetic_context_cache[synthetic_type_viz_cache_key] = cls._TypeVizSyntheticContext(
                typ_viz_synth_item, wildcards)

        non_synthetic_value.SetMetadata(cls._METADATA_SYNTHETIC_TYPE_VIZ_CONTEXT, synthetic_type_viz_cache_key)

    @classmethod
    def _retrieve_type_viz_synthetic_context(cls, non_synthetic_value: lldb.SBValue) -> _TypeVizSyntheticContext | None:
        synthetic_type_viz_cache_key = non_synthetic_value.GetMetadata(cls._METADATA_SYNTHETIC_TYPE_VIZ_CONTEXT)
        if not synthetic_type_viz_cache_key:
            return None
        return cls._type_viz_synthetic_context_cache.get(synthetic_type_viz_cache_key)

    @classmethod
    def make_synthetic_item_with_context(cls, val_non_synthetic: lldb.SBValue,
                                         synthetic_item_provider: TypeVizItemProviderSynthetic,
                                         wildcards: Sequence[str]) -> lldb.SBValue:
        type_viz_synth_item = synthetic_item_provider.type_viz_synthetic_item

        self_type: lldb.SBType = val_non_synthetic.GetType()
        self_pointer: lldb.SBData = val_non_synthetic.AddressOf().GetData()
        void_ptr_type = self_type.GetBasicType(eBasicTypeVoid).GetPointerType()
        synthetic_item_value = val_non_synthetic.CreateValueFromData(type_viz_synth_item.name, self_pointer, void_ptr_type)

        non_synthetic_value_of_synthetic_item: lldb.SBValue = synthetic_item_value.GetNonSyntheticValue()
        cls._store_type_viz_synthetic_context(non_synthetic_value_of_synthetic_item, type_viz_synth_item, wildcards)

        self_reference_value: lldb.SBValue = cls.get_self_reference_in_synthetic_item(non_synthetic_value_of_synthetic_item, self_type)
        ItemExpression.copy_item_expression(val_non_synthetic, self_reference_value)

        if type_viz_synth_item.add_watch_expr:
            getter_call: GeneratedMethod.Call | None = None
            if synthetic_item_provider.expression_getter:
                getter_call = synthetic_item_provider.expression_getter.method_call()
            ItemExpression.update_item_expression(non_synthetic_value_of_synthetic_item, val_non_synthetic,
                                                  type_viz_synth_item.add_watch_expr,
                                                  getter_call)
        else:
            ItemExpression.invalidate_item_expression(non_synthetic_value_of_synthetic_item)

        return synthetic_item_value

    @classmethod
    def retrieve_type_viz_and_wildcards_from(cls, val_non_synthetic: lldb.SBValue) -> tuple[TypeVizSyntheticItem | None, tuple[str, ...]]:
        context = cls._retrieve_type_viz_synthetic_context(val_non_synthetic)
        if not context:
            return None, ()
        return context.type_viz, context.wildcards

    @classmethod
    def get_self_reference_in_synthetic_item(cls, non_synthetic_synthetic_item: lldb.SBValue,
                                             self_reference_type: lldb.SBType | None = None) -> lldb.SBValue:
        value_type = self_reference_type or non_synthetic_synthetic_item.GetType()
        return non_synthetic_synthetic_item.CreateChildAtOffset(cls._SELF_REFERENCE_SPECIAL_NAME, 0, value_type)

    @classmethod
    def clear_cache(cls):
        cls._type_viz_synthetic_context_cache = {}
