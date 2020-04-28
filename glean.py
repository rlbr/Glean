from argparse import ArgumentParser
from collections import Counter
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
            new_resource.register()
            return new_resource


class CompositeResource(BasicResource):
    "Anything that cannot qualify as a BasicResource"

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

    def get_BOM(self, q=1):
        BOM = Counter()
        for dependency, quantity in self.dependencies:
            if type(dependency) == BasicResource:
                BOM[dependency] += q * quantity
            else:
                sub_BOM = dependency.get_BOM(quantity)
                BOM.update(sub_BOM)

        return BOM


def dump_all():
    "Don't waste my time having to re-enter values"
    global RESOURCES_DEFINED
    for resource in RESOURCES_DEFINED.values():
        if not resource.defined:
            resource.save()


atexit.register(dump_all)


def _build_plan(resource, top_quantity, level, hierarchy):
    "Helper"
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
    "Order in which to build resources and in what quantity to achieve the end goal"
    hierarchy = dict()
    b = _build_plan(resource, quantity, 0, hierarchy)
    parts = ((key, value) for key, value in b.items())
    return sorted(parts, key=lambda part: hierarchy[part[0]])


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

bom_parser = ArgumentParser()
bom_parser.add_argument("resource_name", help="The resource, no spaces please.")

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
    complete_add = resource_completer
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
        pass

    @with_argparser(bom_parser)
    def do_bom(self, args):
        pass

    @with_argparser(add_parser)
    def do_add(self, args):
        handle_new_resource(args.resource_name)

    @with_argparser(modify_parser)
    def do_modify(self, args):
        handle_change_resource(args.resource_name)


if __name__ == "__main__":
    app = MainLoop()
    app.cmdloop()
