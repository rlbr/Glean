from argparse import ArgumentParser
import collections
from concurrent.futures import ProcessPoolExecutor
import atexit
import curses

import json
import os
import re
import readline

from cmd2 import Cmd, with_argparser
import appdirs
import npyscreen
import time

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

EXECUTOR = ProcessPoolExecutor()


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


def handle_new_resource(resource_name):
    time.sleep(0.5)
    app_instance = EditApp(resource_name, dict(), defined_resources=get_resource_list())
    future = EXECUTOR.submit(app_instance.return_resource)
    new_resource = future.result(60)
    if new_resource is not None:
        new_resource.register()
        return new_resource


def handle_change_resource(resource_name):
    time.sleep(0.5)
    old_resource = get_resource(resource_name)
    if type(old_resource) == CompositeResource:
        app_instance = EditApp(
            old_resource.resource_name,
            old_resource._dependencies,
            defined_resources=get_resource_list(),
        )
    else:
        app_instance = EditApp(
            old_resource.resource_name, defined_resources=get_resource_list
        )
    future = EXECUTOR.submit(app_instance.return_resource)
    new_resource = future.result(60)
    if new_resource is not None:
        new_resource.register()
        return new_resource


class EditApp(npyscreen.NPSAppManaged):
    def __init__(
        self,
        resource_name="New-resource",
        resource_dependencies={},
        defined_resources=[],
    ):
        super().__init__()
        self.resource_name = resource_name
        self.defined_resources = defined_resources
        self.dependencies_as_list = list(map(list, resource_dependencies.items()))
        self.shared_state = {"resource": None, "quantity": None, "intent": None}

    def onStart(self):
        self.addForm("MAIN", EditForm, name=self.resource_name)
        self.addForm("SELECT", ResourceSelectionForm)

    def return_resource(self):
        self.run()
        if self.shared_state["intent"] == "save":
            if len(self.dependencies_as_list) == 0:
                res = BasicResource(self.resource_name)
            else:
                res = CompositeResource(
                    self.resource_name, dict(self.dependencies_as_list)
                )
            return res
        else:
            return "Failure"


class DependencyList(npyscreen.MultiLineAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_handlers({"^A": self.add, "^D": self.delete})

    @property
    def info(self):
        return self.parent.parentApp.shared_state

    @property
    def values(self):
        return self.parent.parentApp.dependencies_as_list

    @values.setter
    def values(self, _list):
        pass

    def actionHighlighted(self, act_on_this, keypresses):
        resource, quantity = act_on_this
        self.info["resource"] = resource
        self.info["quantity"] = quantity
        self.info["intent"] = "edit"
        self.info["cursor"] = self.cursor_line
        self.parent.parentApp.switchForm("SELECT")

    def display_value(self, value):
        return "{}: {:,}".format(*value)

    def add(self, _input):
        self.info["intent"] = "add"
        self.info["resource"] = None
        self.info["quantity"] = None
        self.parent.parentApp.switchForm("SELECT")

    def delete(self, _input):
        del self.values[self.cursor_line]
        self.display()


class EditForm(npyscreen.ActionFormV2):
    def create(self):
        self.FRAMED = True
        self.dependencies = self.add(DependencyList)

    @property
    def info(self):
        return self.parentApp.shared_state

    def beforeEditing(self):
        self.refresh()

    def afterEditing(self):
        if self.info["intent"] in ("save", "cancel"):
            self.parentApp.setNextForm(None)

    def on_ok(self):
        self.info["intent"] = "save"

    def on_cancel(self):
        self.info["intent"] = "cancel"


class GleanAutocomplete(npyscreen.Autocomplete):
    def auto_complete(self, _input):
        candidates = [
            resource
            for resource in self.parent.parentApp.defined_resources
            if resource.startswith(self.value)
        ]
        if len(candidates) == 0:
            curses.beep()

        elif len(candidates) == 1:
            single = candidates[0]
            if self.value != single:
                self.value = single
            self.h_exit_down

        else:
            cp = os.path.commonprefix(candidates)
            if cp not in candidates:
                candidates.insert(0, cp)
            self.value = candidates[self.get_choice(candidates)]

        self.cursor_position = len(self.value)


class TitleResourceField(npyscreen.TitleText):
    _entry_type = GleanAutocomplete


class ResourceSelectionForm(npyscreen.ActionFormV2):
    DEFAULT_LINES = 12
    DEFAULT_COLUMNS = 60
    SHOW_ATX = 60
    SHOW_ATY = 2

    @property
    def info(self):
        return self.parentApp.shared_state

    @property
    def deps_list(self):
        return self.parentApp.dependencies_as_list

    def create(self):

        self.resource = self.add(TitleResourceField, name="Resource")
        self.quantity = self.add(npyscreen.TitleText, name="Quantity")

    def beforeEditing(self):
        if self.info["resource"] is None:
            self.resource.value = ""
        else:
            self.resource.value = self.info["resource"]

        if self.info["quantity"] is None:
            self.quantity.value = str(1)
        else:
            self.quantity.value = str(self.info["quantity"])

    def on_ok(self):
        self.info["resource"] = self.resource.value
        try:
            self.info["quantity"] = int(self.quantity.value)

        except ValueError:
            npyscreen.notify_confirm(
                "Not a number: {}".format(self.quantity.value), "Error!"
            )
            return
        if self.info["intent"] == "add":
            self.deps_list.append([self.info["resource"], self.info["quantity"]])

        elif self.info["intent"] == "edit":
            self.deps_list[self.info["cursor"]] = [
                self.info["resource"],
                self.info["quantity"],
            ]

        self.parentApp.switchFormPrevious()

    def on_cancel(self):
        self.parentApp.switchFormPrevious()
