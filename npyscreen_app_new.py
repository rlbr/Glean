from glean_ref import *
import npyscreen

# @App definition


class GleanApp(npyscreen.NPSAppManaged):
    def onStart(self):
        self.active_resource = None
        self.new_resource = None
        self.last_resource_name_prompt = ""

        self.changed = True
        self.addForm("ADD", AddResource)
        self.addForm("MODIFY", ModifyResource)
        self.addForm("VIEW", ResourceDetails)
        self.addForm("GET_RESOURCE", ResourceNameQuery, name="Enter Resource Name")
        self.addForm("MAIN", ResourceList)

    def register_new_resource(self):
        if self.new_resource is not None:
            self.new_resource.register()


# @Widgets and buttons


class GoBackOk(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()
        self.parent.parentApp.switchFormPrevious()


class ExitOk(npyscreen.ButtonPress):
    def whenPressed(self):
        self.parent.on_ok()
        self.parent.parentApp.switchForm(None)


class _AddDeleteModifyList(npyscreen.MultiLineAction):
    KEYBINDINGS = {"^A": "add", "^D": "delete", "^E": "modify", "^Q": "quit"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        modifiers = {}
        for k, v in self.KEYBINDINGS.items():
            modifiers[k] = getattr(self, v)

        self.add_handlers(modifiers)


class _ResourceListing(_AddDeleteModifyList):
    def update_listing(self):
        self.values = list(get_resource_list())
        self.display()

    def delete(self, value):
        value = self.values[self.cursor_line]
        if npyscreen.notify_ok_cancel("No way to restore!", "Alert"):
            delete_resource(value)
            self.parent.parentApp.changed = True
            self.parent.update_listing()

    def add(self, value):
        self.parent.parentApp.switchForm("GET_RESOURCE")
        self.parent.parentApp.setNextForm("ADD")
        self.parent.parentApp.changed = True

    def modify(self, value):
        self.parent.parentApp.active_resource = self.values[self.cursor_line]
        self.parent.parentApp.switchForm("MODIFY")

    def quit(self, value):
        self.parent.parentApp.switchForm(None)


class ResourceListing(npyscreen.BoxTitle):
    _contained_widget = _ResourceListing

    def __init__(self, *args, **kwargs):
        help_text = (
            f"{key} -> {function}"
            for key, function in _AddDeleteModifyList.KEYBINDINGS.items()
        )
        super().__init__(*args, footer=" ".join(help_text), **kwargs)


# @Forms


class ResourceNameQuery(npyscreen.Popup):
    FRAMED = True
    OKBUTTON_TYPE = GoBackOk

    def create(self):
        super().create()
        self.resource_input = self.add(npyscreen.TitleText, name="Resource")

    def beforeEditing(self):
        self.resource_input.value = ""

    def on_ok(self):
        self.parentApp.last_resource_name_prompt = self.resource_input.value


class ResourceDetails(npyscreen.Form):
    pass


class ModResourceBase(npyscreen.ActionFormV2):
    pass


class AddResource(ModResourceBase):
    pass


class ModifyResource(ModResourceBase):
    npyscreen.FormMutt


class ActionControllerSearch(npyscreen.ActionControllerSimple):
    def create(self):
        self.add_action("^/.*", self.set_search, True)

    def set_search(self, command_line, widget_proxy, live):
        self.parent.resource_listing.set_filter(command_line[1:])
        self.parent.update_listing()
        self.parent.wMain.values = self.parent.resource_listing.get()
        self.parent.wMain.display()


# @Main form


class ResourceList(npyscreen.FormMuttActive):
    MAIN_WIDGET_CLASS = ResourceListing
    ACTION_CONTROLLER = ActionControllerSearch

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
