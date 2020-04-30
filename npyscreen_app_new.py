from glean_ref import *
import npyscreen
import curses

# @App definition


class GleanApp(npyscreen.NPSAppManaged):
    def onStart(self):
        self.active_resource = None
        self.new_resource_object = None
        self.to_add_pair = None
        self.form_select = None
        self.save_place = False

        self.changed = True
        self.addForm("ADD", ModifyResource)
        self.addForm("MODIFY", ModifyResource)
        self.addForm("VIEW", ResourceDetails)
        self.addForm("GET_RESOURCE", ChangeResourceName, name="Enter Resource Name")
        self.addForm("MAIN", MainResourceList)
        self.addForm("SELECT", AutocompleResourceQuantity)


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


class FormSelectOk(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()
        self.parent.parentApp.switchForm(self.parent.parentApp.form_select)


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


class GoBackOk(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()
        self.parent.parentApp.switchFormPrevious()


class ExitOk(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()
        self.parent.parentApp.switchForm(None)


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
        self.pa.new_resource_object = CompositeResource("", dict())
        self.pa.save_place = False
        self.pa.form_select = "ADD"
        self.pa.switchForm("ADD")
        self.pa.changed = True

    def modify(self, value):
        self.pa.active_resource = self.values[self.cursor_line]
        self.pa.switchForm("MODIFY")

    def quit(self, value):
        self.pa.switchForm(None)


class FilterableResourceListing(npyscreen.BoxTitle):
    _contained_widget = _FilterableResourceListing

    def __init__(self, *args, **kwargs):
        help_text = (
            f"{key} -> {function}"
            for function, key in self._contained_widget.KEYBINDINGS.items()
        )
        super().__init__(*args, footer=" ".join(help_text), **kwargs)

    def __getattribute__(self, attr):
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            return super().__getattribute__("entry_widget").__getattribute__(attr)


class _DependencyListing(_AddDeleteModifyList):
    KEYBINDINGS = _AddDeleteModifyList.KEYBINDINGS.copy()
    del KEYBINDINGS["quit"]

    def display_value(self, value):
        return "{}: {:,}".format(*value)

    def beforeEditing(self):
        if self.pa.to_add_pair is not None:
            key, value = self.pa.to_add_pair
            self.pa.new_resource_object._dependencies[key] = value
            self.pa.to_add_pair = None
        self.update_listing()

    def update_listing(self):
        self.values = sorted(
            map(list, self.pa.new_resource_object._dependencies.items()),
            key=lambda pair: pair[0],
        )

    def add(self):
        self.pa.to_add_pair = None
        self.pa.switchForm("SELECT")

    def modify(self):
        self.pa.to_add_pair = tuple(self.values[self.cursor_line])
        self.pa.switchForm("SELECT")

    def delete(self):
        del self.values[self.cursor_line]
        self.update_listing()

    def on_ok(self):
        self.pa.new_resource_object._dependencies = dict(self.values)
        self.pa.switchFormPrevious()

    def on_cancel(self):
        self.pa.switchFormPrevious()


class DependencyListing(FilterableResourceListing):
    _contained_widget = _DependencyListing


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
            resource, quantity = self.to_add_pair
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
        self.parentApp.to_add_pair = resource, quantity
        self.parentApp.switchFormPrevious()

    def on_cancel(self):
        self.parentApp.switchFormPrevious()


class ChangeResourceName(npyscreen.Popup):
    FRAMED = True
    OKBUTTON_TYPE = FormSelectOk

    def create(self):
        super().create()
        self.resource_input = self.add(AutocompleteResourceText, name="Resource")

    def beforeEditing(self):
        self.resource_input.value = ""

    def on_ok(self):
        self.parentApp.new_resource_object.resource_name = self.resource_input.value


class ResourceDetails(npyscreen.Form):
    pass


class ModifyResource(npyscreen.ActionFormV2):
    def create(self):

        self.change_resource_text = self.add(PressToChange)
        self.dependency_listing = self.add(DependencyListing)

    def beforeEditing(self):
        if not self.parentApp.save_place:
            self.preserve_selected_widget = False
            self.parentApp.save_place = True
        else:
            self.preserve_selected_widget = True

        self.dependency_listing.update_listing()
        self.change_resource_text.value = (
            self.parentApp.new_resource_object.resource_name
        )
        self.change_resource_text.display()

    def on_change_name(self):
        self.name_changed = True

    def on_ok(self):
        new_object = self.parentApp.new_resource_object
        if new_object.resource_name != self.parentApp.active_resource:
            delete_resource(self.parentApp.active_resource)
        new_object.register()
        self.parentApp.switchForm("MAIN")

    def on_cancel(self):
        self.parentApp.switchForm("MAIN")


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
