import importlib
import pkgutil

_discovered = {}


def discover_plugins(package):
    global _discovered
    _discovered.clear()
    prefix = package.__name__ + "."
    for _, name, ispkg in pkgutil.iter_modules(package.__path__, prefix):
        if ispkg:
            continue
        mod = importlib.import_module(name)
        for attr in dir(mod):
            obj = getattr(mod, attr, None)
            if (
                isinstance(obj, type)
                and hasattr(obj, "tool_name")
                and obj.tool_name
                and obj is not type(obj)
            ):
                try:
                    _discovered[obj.tool_name] = obj()
                except Exception:
                    pass


def get_plugin(name):
    return _discovered.get(name)


def list_plugins():
    return list(_discovered.values())


def all_plugins():
    return list(_discovered.values())
