import collections
from concurrent.futures import ProcessPoolExecutor
import atexit

import json
import os
import re
import readline

import appdirs


GLEAN_DIRS = appdirs.AppDirs("glean_dev")
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


def filepath(resource_name):
    return os.path.join(RESOURCES_DIR, f"{resource_name}.json")


def delete_resource(resource_name):
    try:
        del RESOURCES_DEFINED[resource_name]
    except KeyError:
        pass
    try:
        os.remove(filepath(resource_name))
    except FileNotFoundError:
        pass


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
                resource_obj = Resource(resource_name, json.load(file))
                RESOURCES_DEFINED[resource_name] = resource_obj
                return resource_obj
        except FileNotFoundError:
            return None


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


class Resource:
    def __init__(self, resource_name, _dependencies):
        self.resource_name = resource_name
        self._dependencies = _dependencies
        self._bom = None

    def save(self):
        with open(
            os.path.join(RESOURCES_DIR, f"{self.resource_name}.json"), "w"
        ) as file:
            json.dump(self.serialize(), file)

    @property
    def defined(self):
        return f"{self.resource_name}.json" in os.listdir(RESOURCES_DIR)

    def __str__(self):
        return self.resource_name

    def __repr__(self):
        return f"{self.__class__.__name__}: {self}"

    def __hash__(self):
        return hash(self.resource_name)

    def register(self):
        global RESOURCES_DEFINED
        RESOURCES_DEFINED[self.resource_name] = self

    def serialize(self):
        return self._dependencies

    @property
    def dependencies(self):
        for dependency, quantity in self._dependencies.items():
            yield get_resource(dependency), quantity

    def get_BOM(self, q=1, force_update=False):
        BOM = BillOfMaterials()
        if len(self._dependencies) == 0:
            BOM[self] += q
            return BOM
        if self._bom is not None and not force_update:
            return self._bom * q

        for dependency, quantity in self.dependencies:
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


def BOM(resource, quantity, update):
    return get_resource(resource).get_BOM(quantity)
