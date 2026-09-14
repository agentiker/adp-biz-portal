from glob import glob
from importlib import import_module
from inspect import getmembers
from pathlib import Path
from types import ModuleType
import pkgutil
import logging
from sanic.blueprints import Blueprint


def _dotted_name(package: ModuleType, path: Path) -> str:
    """Return the canonical dotted module name for a file inside a package."""
    relative = path.relative_to(Path(package.__file__).parent)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join([package.__name__, *parts]) if parts else package.__name__


def autodiscover(app, module_names: list[ModuleType], recursive: bool = False):
    blueprints = set()

    def _find_bps(module):
        nonlocal blueprints

        for _, member in getmembers(module):
            if isinstance(member, Blueprint):
                blueprints.add(member)

    for module in module_names:
        _find_bps(module)

        if recursive:
            base = Path(module.__file__).parent
            for path in sorted(glob(f"{base}/**/*.py", recursive=True)):
                # Import under the canonical dotted name so the module cache
                # keeps one instance. Loading the same file under a synthetic
                # name would execute route registration twice as soon as
                # anything imports it normally, and would leave ``__name__``
                # wrong for module-level loggers.
                _find_bps(import_module(_dotted_name(module, Path(path))))

    for bp in blueprints:
        print(f'[autodiscover] registering blueprint {bp}')
        app.blueprint(bp)


def autodiscover_vendor():
    import vendor
    vendors = {}

    for _, name, _ in pkgutil.iter_modules(vendor.__path__):
        module = import_module(f'vendor.{name}')
        if hasattr(module, 'get_class'):
            logging.info(f'loading vendor class: {name}')
            cls_or_list = module.get_class()

            # Support both single class and list of classes
            if isinstance(cls_or_list, list):
                for cls in cls_or_list:
                    vendor_name = cls.get_vendor()
                    vendors[vendor_name] = cls
                    logging.info(f'  registered vendor: {vendor_name}')
            else:
                vendor_name = cls_or_list.get_vendor()
                vendors[vendor_name] = cls_or_list
                logging.info(f'  registered vendor: {vendor_name}')

    return vendors


def autodiscover_oauth():
    import oauth_provider

    for _, name, _ in pkgutil.iter_modules(oauth_provider.__path__):
        module = import_module(f'oauth_provider.{name}')
        if hasattr(module, 'get_class'):
            logging.info(f'loading oauth_provider class: {name}')
            cls = module.get_class()
            cls()
