from renderers.jb_lldb_logging_manager import RENDER_LOG

g_type_viz_loaders = {}


class TypeVizLoaderException(Exception):
    pass


def type_viz_loader_add(tag, loader):
    RENDER_LOG.info("Registering loader for type viz of type '%s'", tag)
    if tag in g_type_viz_loaders:
        RENDER_LOG.warning("Loader for type viz of type '%s' already exists", tag)
    g_type_viz_loaders[tag] = loader


def type_viz_loader_remove(tag):
    RENDER_LOG.info("Removing loader for type viz of type '%s'", tag)
    del g_type_viz_loaders[tag]


def type_viz_loader_get_list():
    return g_type_viz_loaders


def type_viz_loader_get(tag):
    return g_type_viz_loaders[tag]
