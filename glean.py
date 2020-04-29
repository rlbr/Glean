from argparse import ArgumentParser
import collections
import atexit
import curses
import json
import os
import re
import readline

from cmd2 import Cmd, with_argparser
from npyscreen import GridColTitles, ActionFormV2, FormMuttActive
import appdirs

GLEAN_DIRS = appdirs.AppDirs("glean")
BASIC = 0
os.makedirs(GLEAN_DIRS.user_state_dir, exist_ok=True)
hist_file = os.path.join(GLEAN_DIRS.user_state_dir, "history")
if not os.path.exists(hist_file):
    with open(hist_file, "w") as fobj:
        fobj.write("")
readline.read_history_file(hist_file)
atexit.register(readline.write_history_file, hist_file)
RESOURCES_DIR = os.path.join(GLEAN_DIRS.user_data_dir, "resources")
os.makedirs(RESOURCES_DIR, exist_ok=True)

RESOURCES_DEFINED = dict()


class BasicResource:
    "Definition: A resource that cannot be divided futher, and has no dependencies."
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

    def __repr__(self):
        return f"{type(self)}: {self}"

    def __hash__(self):
        return hash(self.resource_name)

    def register(self):
        global RESOURCES_DEFINED
        RESOURCES_DEFINED[self.resource_name] = self


def deserialize(resource_name, data: dict):
    "dict -> BasicResource/CompositeResource as appropriate."
    if data is None:
        return BasicResource(resource_name)
    else:
        return CompositeResource(resource_name, data)


def get_resource_list():
    file_resources = (
        re.sub(".json$", "", filename) for filename in os.listdir(RESOURCES_DIR)
    )
    return sorted(set(RESOURCES_DEFINED.keys()) | set(file_resources))


def get_resource(resource_name):
    "By only fetching resources through this method, single instance is ensured."
    try:
        return RESOURCES_DEFINED[resource_name]
    except KeyError:
        try:
            with open(os.path.join(RESOURCES_DIR, f"{resource_name}.json")) as file:
                resource_obj = deserialize(resource_name, json.load(file))
                RESOURCES_DEFINED[resource_name] = resource_obj
                return resource_obj
        except FileNotFoundError:
            new_resource = handle_new_resource(resource_name)
            return new_resource


class BillOfMaterials(collections.defaultdict):
    def __init__(self, *arg, **kwargs):
        super().__init__(None, *arg, **kwargs)

    def __missing__(self, key):
        return 0

    def __hash__(self):
        return hash(tuple(self.items()))

    def __mul__(self, other):
        ret = BillOfMaterials()
        for k, v in self.items():
            ret[k] = v * other
        return ret

    def __add__(self, other):

        merged = BillOfMaterials(self)
        for k, v in other.items():
            merged[k] += v
        return BillOfMaterials(merged)


class CompositeResource(BasicResource):
    "Anything that cannot qualify as a BasicResource"

    def __init__(self, resource_name, _dependencies):
        super().__init__(resource_name)
        self._dependencies = _dependencies
        self._bom = None

    def serialize(self):
        return self._dependencies

    @property
    def dependencies(self):
        for dependency, quantity in self._dependencies.items():
            yield get_resource(dependency), quantity

    def get_BOM(self, q=1, force_update=False):
        if self._bom is not None and not force_update:
            return self._bom * q

        BOM = BillOfMaterials()
        for dependency, quantity in self.dependencies:
            if type(dependency) == BasicResource:
                BOM[dependency] += quantity
            else:
                dependency_BOM = dependency.get_BOM(quantity, force_update)
                BOM += dependency_BOM
        self._bom = BOM
        return BOM * q


def dump_all():
    "Don't waste my time having to re-enter values"
    global RESOURCES_DEFINED
    for resource in RESOURCES_DEFINED.values():
        if not resource.defined:
            resource.save()


atexit.register(dump_all)


def _build_plan(resource, top_quantity, level, hierarchy):
    "Helper"
    plan = BillOfMaterials()
    plan[resource] += top_quantity
    hierarchy[resource] = max(level, hierarchy.get(resource, level))
    if type(resource) == BasicResource:
        return plan
    else:
        for dependency, quantity in resource.dependencies:
            sub_count = _build_plan(
                dependency, quantity * top_quantity, level + 1, hierarchy
            )
            plan += sub_count
        return plan


def build_plan(resource, quantity):
    "Order in which to build resources and in what quantity to achieve the end goal"
    hierarchy = dict()
    b = _build_plan(resource, quantity, 0, hierarchy)
    parts = ((key, value) for key, value in b.items())
    return sorted(parts, key=lambda part: hierarchy[part[0]], reverse=True)


class MyGrid(GridColTitles):
    X = 1
    Y = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, col_titles=["Resource", "Quantity"], **kwargs)
        self.add_handlers({curses.KEY_ENTER, self.change_cell})
        super().set_up_handlers

    def change_cell(self):
        if self.edit_cell[MyGrid.X] == 0:
            pass
        else:
            pass

    def to_dict(self):
        rows = ((str(r), int(q)) for r, q in self.values)
        return dict(rows)


class ModifyResourceForm(ActionFormV2):
    pass


class SelectionPopup(FormMuttActive):
    DEFAULT_LINES = 12
    DEFAULT_COLUMNS = 60
    SHOW_ATX = 10
    SHOW_ATY = 2


def handle_new_resource(resource_name):
    pass


def handle_change_resource(resource_name):
    pass


list_parser = ArgumentParser()
list_parser.add_argument(
    "-f",
    "--filter",
    action="store_true",
    help="input a lambda function to filter resource types (re is imported)",
)

build_guide_parser = ArgumentParser()
build_guide_parser.add_argument("resource_name", help="The resource, no spaces please.")
build_guide_parser.add_argument(
    "-q", "--quantity", action="store", type=int, default=1, help="How many to make"
)

bom_parser = ArgumentParser()
bom_parser.add_argument("resource_name", help="The resource, no spaces please.")
bom_parser.add_argument(
    "-q", "--quantity", action="store", type=int, default=1, help="How many to make"
)
bom_parser.add_argument(
    "-f", "--force-update", action="store_true", help="Force fresh calculation of bom"
)

add_parser = ArgumentParser()
add_parser.add_argument("resource_name", help="The resource, no spaces please.")

modify_parser = ArgumentParser()
modify_parser.add_argument("resource_name", help="The resource, no spaces please.")


class MainLoop(Cmd):
    def resource_completer(self, text, line, start_index, end_index):

        resources = get_resource_list()
        if text:
            return [resource for resource in resources if resource.startswith(text)]
        else:
            return list(resources)

    complete_list = resource_completer
    complete_build_guide = resource_completer
    complete_bom = resource_completer
    complete_modify = resource_completer

    @with_argparser(list_parser)
    def do_list(self, args):
        all_resources = (
            get_resource(resource_name) for resource_name in get_resource_list()
        )
        if args.filter:
            key = eval(input("Lambda expr: "))
            all_resources = filter(key, all_resources)
        print("\n".join(resource.resource_name for resource in all_resources))

    @with_argparser(build_guide_parser)
    def do_build_guide(self, args):
        items = build_plan(get_resource(args.resource_name), args.quantity)
        print("\n".join(f"{item}: {quantity:,}" for item, quantity in items))

    @with_argparser(bom_parser)
    def do_bom(self, args):
        bom = get_resource(args.resource_name).get_BOM(args.quantity, args.force_update)
        prelim_items = ((k.resource_name, v) for k, v in bom.items())
        items = sorted(prelim_items, key=lambda pair: pair[0])
        print("\n".join(f"{item}: {quantity:,}" for item, quantity in items))

    @with_argparser(add_parser)
    def do_add(self, args):
        handle_new_resource(args.resource_name)

    @with_argparser(modify_parser)
    def do_modify(self, args):
        handle_change_resource(args.resource_name)


if __name__ == "__main__":
    app = MainLoop()
    app.cmdloop()
