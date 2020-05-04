#!/usr/bin/env python3

import atexit
import collections
import curses
import json
import os
import re


import appdirs
import npyscreen

GLEAN_DIRS = appdirs.AppDirs("glean")
os.makedirs(GLEAN_DIRS.user_state_dir, exist_ok=True)
RESOURCES_DIR = os.path.join(GLEAN_DIRS.user_data_dir, "resources")
os.makedirs(RESOURCES_DIR, exist_ok=True)

RESOURCES_DEFINED = dict()


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


def build_reverse_dependency_tree():

    reverse_dependency_tree = collections.defaultdict(lambda: [])
    for resource in map(get_resource, get_resource_list()):
        for depedency in resource._dependencies.keys():
            reverse_dependency_tree[depedency].append(resource)
    return reverse_dependency_tree


def replace_name(original, new):
    rdep_tree = build_reverse_dependency_tree()
    for parent in rdep_tree[original]:
        quantity = parent._dependencies.pop(original)
        parent._dependencies[new] = quantity


# @App definition


class GleanApp(npyscreen.NPSAppManaged):
    def onStart(self):
        self.active_resource = []
        self.caller_resource = None
        self.changed = True
        self.last_command_text = None
        self.last_info_command = None
        self.last_resource_object = None
        self.original_name = None
        self.save_place = False
        self.to_add_pair = None

        self.addForm("MODIFY", ModifyResource)
        self.addForm("ADD_QUEUE", AddResourceQueue)
        self.addForm("VIEW", ResourceDetails)
        self.addForm("GET_RESOURCE", ChangeResourceName, name="Enter Resource Name")
        self.addForm("MAIN", MainResourceList)
        self.addForm("SELECT", AutocompleResourceQuantity)
        self.addForm("INFO", Infobox)

    def handle_add(self, resource_name=""):
        self.push(resource_name)
        self.original_name = None
        self.last_resource_object = Resource(self.top(), dict())
        self.save_place = False
        self.switchForm("MODIFY")
        self.changed = True

    def handle_modify(self, resource_name):
        self.push(resource_name)
        self.original_name = self.top()
        old = get_resource(self.top())
        self.last_resource_object = Resource(old.resource_name, old._dependencies)
        self.save_place = False
        self.switchForm("MODIFY")
        self.changed = True

    def push(self, resource_name):
        self.active_resource.append(resource_name)

    def pop(self):
        return self.active_resource.pop()

    def top(self):
        return self.active_resource[-1]


# @Utils


class Search(npyscreen.ActionControllerSimple):
    def create(self):
        self.add_action("^/.*", self.set_search, True)

    def set_search(self, command_line, widget_proxy, live):
        self.parent.resource_listing.set_filter(command_line[1:])
        self.parent.update_listing()
        self.parent.wMain.values = self.parent.resource_listing.get()
        self.parent.wMain.display()


class GleanAutocomplete(npyscreen.Autocomplete):
    def auto_complete(self, _input):
        candidates = [
            resource
            for resource in get_resource_list()
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


# @Widgets and buttons


class AutocompleteResourceText(npyscreen.TitleText):
    _entry_type = GleanAutocomplete


class _PressToChange(npyscreen.FixedText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_handlers(
            {curses.ascii.NL: self.handlePress, curses.ascii.CR: self.handlePress}
        )

    def handlePress(self, _input):
        self.parent.on_change_name()
        self.parent.parentApp.switchForm("GET_RESOURCE")


class PressToChange(npyscreen.BoxTitle):
    _contained_widget = _PressToChange

    def __init__(self, *args, **kwargs):
        kwargs["max_height"] = 3
        kwargs["name"] = "Resource name"
        super().__init__(*args, **kwargs)


class ActionTextbox(npyscreen.TitleText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.action_function = kwargs.pop("action_function")
        self.add_handlers(
            {
                curses.ascii.NL: self.handle_action_function,
                curses.ascii.CR: self.handle_action_function,
            }
        )

    def handle_action_function(self, _input):
        self.action_function(self.value)


class ButtonPressCallback(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()


class _AddDeleteModifyList(npyscreen.MultiLineAction):
    KEYBINDINGS = {
        "add": "a",
        "delete": "d",
        "modify": "e",
        "quit": "q",
        "search": "s",
        "reset search": "^R",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        modifiers = {}
        for f, k in self.KEYBINDINGS.items():
            modifiers[k] = getattr(self, f.replace(" ", "_"))
        self.add_handlers(modifiers)

        self.pa: GleanApp = self.parent.parentApp


class _FilterableResourceListing(_AddDeleteModifyList):
    def update_listing(self):
        self.values = list(get_resource_list())
        self.display()

    def delete(self, value):
        value = self.values[self.cursor_line]
        if npyscreen.notify_ok_cancel("All deletes are final!", "Alert"):
            delete_resource(value)
            self.pa.changed = True
            self.parent.update_listing()

    def add(self, value):
        self.pa.handle_add()

    def modify(self, value):
        self.pa.handle_modify(self.values[self.cursor_line])

    def actionHighlighted(self, value, ch):
        self.pa.push(value)
        self.pa.switchForm("VIEW")

    def quit(self, value):
        self.pa.switchForm(None)

    def search(self, _input):
        self.parent.wCommand.edit()

    def reset_search(self, _input):
        self.parent.resource_listing.set_filter("")
        self.parent.update_listing()
        self.parent.wMain.values = self.parent.resource_listing.get()
        self.parent.wMain.display()
        self.parent.wCommand.value = ""
        self.parent.wCommand.display()


class PassthroughBoxTitle(npyscreen.BoxTitle):
    def __getattribute__(self, attr):
        try:
            return super(PassthroughBoxTitle, self).__getattribute__(attr)
        except AttributeError as e:
            try:
                if attr in ("parent_widget",):
                    raise e
                return (
                    super(PassthroughBoxTitle, self)
                    .__getattribute__("entry_widget")
                    .__getattribute__(attr)
                )
            except Exception as e:
                raise e


class FilterableResourceListing(PassthroughBoxTitle):
    _contained_widget = _FilterableResourceListing

    def __init__(self, *args, **kwargs):
        help_text = (
            f"{key} -> {function.title()}"
            for function, key in self._contained_widget.KEYBINDINGS.items()
        )
        super().__init__(*args, footer=" ".join(help_text), **kwargs)


class _DependencyListing(_AddDeleteModifyList):
    KEYBINDINGS = {}
    for key in ("add", "modify", "delete"):
        KEYBINDINGS[key] = _AddDeleteModifyList.KEYBINDINGS[key]

    def display_value(self, value):
        return "{}: {:,}".format(*value)

    def update_listing(self):
        self.values = sorted(
            map(list, self.pa.last_resource_object._dependencies.items()),
            key=lambda pair: pair[0],
        )
        self.display()

    def add(self, _input):
        self.pa.to_add_pair = None
        self.pa.switchForm("SELECT")

    def actionHighlighted(self, _input):
        self.modify()

    def modify(self):
        self.pa.to_add_pair = self.values[self.cursor_line]
        self.pa.switchForm("SELECT")

    def delete(self, _input):
        dependency_name = self.values[self.cursor_line][0]
        del self.pa.last_resource_object._dependencies[dependency_name]
        self.update_listing()


class DependencyListing(FilterableResourceListing):
    _contained_widget = _DependencyListing


class _DependencyListingFixed(npyscreen.MultiLineAction):
    def update_listing(self):
        self.values = list(
            map(list, self.parent.resource_looked_at._dependencies.items())
        )
        self.display()

    def actionHighlighted(self, value, ch):
        resource_name = value[0]
        if resource_name in get_resource_list():
            self.parent.parentApp.push(resource_name)
            self.parent.beforeEditing()
        else:
            self.parent.handle_maybe_missing_resources()

    def display_value(self, value):
        resource_name, quantity = value
        return f"{resource_name}: {quantity}"


class DependencyListingFixed(PassthroughBoxTitle):
    _contained_widget = _DependencyListingFixed

    def __init__(self, *args, **kwargs):
        kwargs["name"] = "Dependencies"
        super().__init__(*args, **kwargs)


class CommandText(npyscreen.MultiLineEditableBoxed):
    def __init__(self, *args, **kwargs):
        kwargs["editable"] = False
        super().__init__(*args, **kwargs)


# @Forms


class AutocompleResourceQuantity(npyscreen.ActionFormV2):
    DEFAULT_LINES = 12
    DEFAULT_COLUMNS = 60
    SHOW_ATX = 60
    SHOW_ATY = 2
    resource_default_quantity = 1

    def create(self):

        self.resource = self.add(AutocompleteResourceText, name="Resource")
        self.quantity = self.add(npyscreen.TitleText, name="Quantity")

    def beforeEditing(self):
        if self.parentApp.to_add_pair is None:
            self.resource.value = ""
            self.quantity.value = str(self.resource_default_quantity)

        else:
            resource, quantity = self.parentApp.to_add_pair
            self.resource.value = resource
            self.quantity.value = str(quantity)

    def on_ok(self):

        resource = self.resource.value
        try:
            quantity = int(self.quantity.value)

        except ValueError:
            npyscreen.notify_confirm(
                "Not a number: {}".format(self.quantity.value), "Error!"
            )
            return
        self.parentApp.to_add_pair = None
        self.parentApp.last_resource_object._dependencies[resource] = quantity
        self.parentApp.switchFormPrevious()

    def on_cancel(self):
        self.parentApp.switchFormPrevious()


class ChangeResourceName(npyscreen.Popup):
    FRAMED = True
    OKBUTTON_TYPE = ButtonPressCallback

    def create(self):
        super().create()
        self.resource_input = self.add(AutocompleteResourceText, name="Resource")

    def beforeEditing(self):
        self.resource_input.value = ""

    def on_ok(self):
        self.parentApp.last_resource_object.resource_name = self.resource_input.value
        self.parentApp.push(self.resource_input.value)
        self.parentApp.switchFormPrevious()


class ModifyResource(npyscreen.ActionFormV2):
    def create(self):

        self.resource_name = self.add(PressToChange)
        self.dependency_listing = self.add(DependencyListing)

    def beforeEditing(self):
        if not self.parentApp.save_place:
            self.preserve_selected_widget = False
            self.parentApp.save_place = True
        else:
            self.preserve_selected_widget = True

        self.dependency_listing.update_listing()
        self.resource_name.value = self.parentApp.last_resource_object.resource_name
        self.resource_name.display()

    def on_change_name(self):
        self.name_changed = True
        self.parentApp.pop()

    def on_ok(self):

        if self.parentApp.last_resource_object.resource_name == "":
            npyscreen.notify_confirm("Please input a name", "Alert")
            return

        self.parentApp.pop()
        if self.parentApp.original_name is not None:

            if (  # noqa
                self.parentApp.last_resource_object.resource_name  # noqa
                != self.parentApp.original_name  # noqa
            ):  # noqa
                replace_name(
                    self.parentApp.original_name,
                    self.parentApp.last_resource_object.resource_name,
                )
                delete_resource(self.parentApp.original_name)

        self.parentApp.last_resource_object.register()
        self.parentApp.switchFormPrevious()

    def on_cancel(self):
        self.parentApp.pop()
        self.parentApp.switchFormPrevious()


class AddResourceQueue(ModifyResource):
    def create(self):

        self.resource_name = self.add(
            npyscreen.TitleText, editable=False, name="Resource"
        )
        self.dependency_listing = self.add(DependencyListing)

    def beforeEditing(self):

        if self.parentApp.last_resource_object is None:
            self.parentApp.last_resource_object = Resource(self.parentApp.top(), dict())

        super().beforeEditing()

    def on_cancel(self):
        npyscreen.notify_confirm("You must save this resource", "Alert")

    def on_ok(self):

        self.parentApp.last_resource_object.register()
        self.parentApp.pop()
        for dependency in self.parentApp.last_resource_object._dependencies.keys():
            if dependency not in get_resource_list():
                self.parentApp.push(dependency)
        self.parentApp.last_resource_object = Resource(self.parentApp.top(), dict())
        self.parentApp.save_place = False
        self.parentApp.changed = True
        if self.parentApp.top() == self.parentApp.caller_resource:
            self.parentApp.switchFormPrevious()
        else:
            self.beforeEditing()


class ResourceDetails(npyscreen.Form):

    OKBUTTON_TYPE = ButtonPressCallback

    def __init__(self, *args, **kwargs):
        kwargs["name"] = "Details"
        kwargs["help"] = "^Q -> Back"

        super().__init__(*args, **kwargs)
        self.handlers.update({"^Q": self.on_ok})

    def create(self):
        self.resource_looked_at = None
        self.resource_name = self.add(npyscreen.FixedText, editable=False)

        self.BOM = self.add(
            ActionTextbox,
            action_function=self.handle_bom,
            name="Input quantity and press enter for Bill Of Materials",
        )
        self.build_plan = self.add(
            ActionTextbox,
            action_function=self.handle_build_plan,
            name="Input quantity and press enter for Build Plan",
        )
        self.dependency_listing = self.add(DependencyListingFixed)

    def beforeEditing(self):
        if self.parentApp.last_command_text is not None:
            self.parentApp.switchForm("INFO")
            return
        self.resource_looked_at = get_resource(self.parentApp.top())
        self.resource_name.value = self.resource_looked_at.resource_name
        self.resource_name.display()
        self.BOM.value = ""
        self.build_plan.value = ""
        self.dependency_listing.update_listing()

    def on_ok(self):
        self.parentApp.pop()
        if len(self.parentApp.active_resource) != 0:
            self.beforeEditing()
        else:
            self.parentApp.switchFormPrevious()

    def mark_missing_dependencies(self, resource_name):
        resource = get_resource(resource_name)
        if resource is None:
            self.parentApp.push(resource_name)
            return

        for dependency in resource._dependencies.keys():
            self.mark_missing_dependencies(dependency)

    def handle_bom(self, quantity):
        self.parentApp.last_info_command = self.bom_set_command_text
        self.handle_info(quantity)

    def bom_set_command_text(self):
        resource_name = self.parentApp.top()
        quantity = self.parentApp.last_requested_quanitity
        bom = get_resource(resource_name).get_BOM(quantity, self.parentApp.changed)
        prelim_items = ((k.resource_name, v) for k, v in bom.items())
        items = sorted(prelim_items, key=lambda pair: pair[0])
        self.parentApp.last_command_text = "\n".join(
            f"{item}: {quantity:,}" for item, quantity in items
        )

    def build_plan_set_command_text(self):
        resource_name = self.parentApp.top()
        quantity = self.parentApp.last_requested_quanitity
        items = build_plan(get_resource(resource_name), quantity)

        self.parentApp.last_command_text = "\n".join(
            f"{item}: {quantity:,}" for item, quantity in items
        )

    def handle_maybe_missing_resources(self):
        self.parentApp.caller_resource = self.parentApp.top()
        self.mark_missing_dependencies(self.parentApp.caller_resource)
        if self.parentApp.top() != self.parentApp.caller_resource:
            self.parentApp.last_resource_object = None
            self.parentApp.switchForm("ADD_QUEUE")
            return True
        return False

    def handle_info(self, quantity):
        try:
            self.parentApp.last_requested_quanitity = int(quantity)
        except ValueError:
            npyscreen.notify_confirm(f"{quantity} is not a valid integer")
            return
        if not self.handle_maybe_missing_resources():

            self.parentApp.last_info_command()
            self.beforeEditing()

    def handle_build_plan(self, quantity):
        self.parentApp.last_info_command = self.build_plan_set_command_text
        self.handle_info(quantity)


class Infobox(npyscreen.Form):
    FRAMED = True
    OKBUTTON_TYPE = ButtonPressCallback

    def __init__(self, *args, **kwargs):
        kwargs["name"] = "Info"

        super().__init__(*args, **kwargs)

    def create(self):
        self.command_box = self.add(npyscreen.MultiLineEdit, editable=False)

    def beforeEditing(self):
        self.command_box.value = self.parentApp.last_command_text
        self.command_box.update()

    def on_ok(self):
        self.parentApp.last_command_text = None
        self.parentApp.switchFormPrevious()


# @Main form


class MainResourceList(npyscreen.FormMuttActive):
    MAIN_WIDGET_CLASS = FilterableResourceListing
    ACTION_CONTROLLER = Search

    def create(self):
        super().create()
        self.wStatus1.value = "Resources"
        self.wStatus2.value = "Search"
        self.resource_listing = npyscreen.NPSFilteredDataList()
        self.update_listing()

    def update_listing(self):
        if self.parentApp.changed:
            self.resource_listing.set_values(get_resource_list())
            self.wMain.values = self.resource_listing.get()
            self.wMain.display()
            self.parentApp.changed = False

    def beforeEditing(self):
        self.update_listing()

    def on_ok(self):
        print("values", self.resource_list.values)


if __name__ == "__main__":
    GleanApp().run()
