from collections import Counter
import atexit
import json
import os
import re
import readline

from cmd2 import Cmd
import appdirs

# Class definition
GLEAN_DIRS = appdirs.AppDirs("glean")
BASIC = 0
hist_file = os.path.join(GLEAN_DIRS.user_state_dir, "history")
if not os.path.exists(hist_file):
    with open(hist_file, "w") as fobj:
        fobj.write("")
readline.read_history_file(hist_file)
atexit.register(readline.write_history_file, hist_file)
RESOURCES_DIR = os.path.join(GLEAN_DIRS.site_data_dir, "resources")
os.makedirs(RESOURCES_DIR, exists_ok=True)

RESOURCES_DEFINED = dict()


class BasicResource:
    __res_type__ = BASIC

    def __init__(self, resource_name):
        self.resource_name = resource_name

    def save(self):
        with open(
            os.path.join(RESOURCES_DIR, f"{self.resource_name}.json"), "w"
        ) as file:
            json.dump(self.serialize(), file)

    def serialize(self):
        return None

    @property
    def defined(self):
        return f"{self.resource_name}.json" in os.listdir(RESOURCES_DIR)

    def __str__(self):
        return self.resource_name


def deserialize(self, resource_name, data):
    if data is None:
        return BasicResource(resource_name)
    else:
        return CompositeResource(resource_name, data)


def get_resource(resource_name):
    try:
        return RESOURCES_DEFINED[resource_name]
    except KeyError:
        with open("f{resource_name}.json") as file:
            resource_obj = deserialize(json.load(file))
            RESOURCES_DEFINED[resource_name] = resource_obj
            return resource_obj
    except FileNotFoundError:
        handle_new_resource(resource_name)


def handle_new_resource(resource_name):
    pass


class CompositeResource(BasicResource):
    def __init__(self, resource_name, _dependencies):
        super().__init__(resource_name)
        self._dependencies = _dependencies

    def serialize(self):
        return self._dependencies

    def dependencies(self):
        return (
            (get_resource(resource_name), self._dependencies[resource_name])
            for resource_name in self._dependencies.keys()
        )

    def __hash__(self):
        return hash(self.resource_name)

    def get_BOM(self, q=1):
        BOM = Counter()
        for dependency, quantity in self.dependencies:
            if type(dependency) == BasicResource:
                BOM[dependency] += q * quantity
            else:
                sub_BOM = dependency.get_BOM(quantity)
                BOM.update(sub_BOM)

        return BOM


def from_file(filename):
    resource_name = re.sub(r"(.*)\.json$").group(1)
    with open(filename) as file:
        _dependencies = json.load(file)
        if _dependencies is None:
            return BasicResource(resource_name)
        else:
            return CompositeResource


def dump_all():
    for resource in RESOURCES_DEFINED.values():
        if not resource.defined:
            resource.save()


atexit.register(dump_all)


def _build_plan(resource, top_quantity, level, hierarchy):
    c = Counter()
    c[resource] += top_quantity
    hierarchy[resource] = max(level, hierarchy[resource])
    if type(resource) == BasicResource:
        return c
    else:
        for dependency, quantity in resource.dependencies:
            sub_count = _build_plan(
                resource, quantity * top_quantity, level + 1, hierarchy
            )
            c.update(sub_count)
        return c


def build_plan(resource, quantity):
    hierarchy = dict()
    b = _build_plan(resource, quantity, 0, hierarchy)
    parts = ((key, value) for key, value in b.items())
    return sorted(parts, key=lambda part: hierarchy[part[0]])


class MainLoop(Cmd):
    def do_list(self, args):
        pass

    def do_build_guide(self, args):
        pass

    def do_bom(self, args):
        pass

    def do_add(self, args):
        handle_new_resource(args.resource_name)

    def do_modify(self, args):
        pass


if __name__ == "__main__":
    app = MainLoop()
    app.cmdloop()
