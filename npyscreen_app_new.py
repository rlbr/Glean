from glean_ref import *
import npyscreen
import curses


def build_reverse_dependency_tree():

    reverse_dependency_tree = collections.defaultdict(lambda: [])
    for resource in map(get_resource, get_resource_list()):
        for depedency in resource._dependencies.keys():
            reverse_dependency_tree[depedency].append(resource)
    return reverse_dependency_tree


def replace_name(original, new):
    rdep_tree = build_reverse_dependency_tree()
    npyscreen.notify_confirm(pprint.pformat(rdep_tree[original]))
    for parent in rdep_tree[original]:
        quantity = parent._dependencies.pop(original)
        parent._dependencies[new] = quantity


# @App definition


class GleanApp(npyscreen.NPSAppManaged):
    def onStart(self):
        self.active_resource = []
        self.to_add_pair = None
        self.save_place = False
        self.caller_resource = None
        self.last_command_text = None
        self.last_info_command = None
        self.last_resource_object = None
        self.original_name = None

        self.changed = True
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
    KEYBINDINGS = {"add": "^A", "delete": "^D", "modify": "^E", "quit": "^Q"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        modifiers = {}
        for f, k in self.KEYBINDINGS.items():
            modifiers[k] = getattr(self, f)
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
            f"{key} -> {function}"
            for function, key in self._contained_widget.KEYBINDINGS.items()
        )
        super().__init__(*args, footer=" ".join(help_text), **kwargs)


class _DependencyListing(_AddDeleteModifyList):
    KEYBINDINGS = _AddDeleteModifyList.KEYBINDINGS.copy()
    del KEYBINDINGS["quit"]
    del KEYBINDINGS["modify"]

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

    def actionHighlighted(self, *args):
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
        npyscreen.notify_confirm(str(self.parentApp.active_resource))

        if self.parentApp.last_resource_object is None:
            self.parentApp.last_resource_object = Resource(self.parentApp.top(), dict())

        super().beforeEditing()

    def on_cancel(self):
        npyscreen.notify_confirm("You must save this resource", "Alert")

    def on_ok(self):

        self.parentApp.last_resource_object.register()
        self.parentApp.pop()
        npyscreen.notify_confirm(str(self.parentApp.last_resource_object._dependencies))
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

    def create(self):
        self.resource_looked_at = None
        self.resource_name = self.add(npyscreen.FixedText, editable=False)

        self.BOM = self.add(
            ActionTextbox,
            action_function=self.handle_bom,
            name="Input quantity and press enter for BOM",
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
        npyscreen.notify_confirm(str(resource_name))
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
    ga = GleanApp()
    ga.run()
