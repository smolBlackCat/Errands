# Copyright 2023-2024 Vlad Krupinskii <mrvladus@yandex.ru>
# SPDX-License-Identifier: MIT


from gi.repository import Adw, GObject, Gtk  # type:ignore

from errands.lib.data import TaskListData, UserData
from errands.lib.gsettings import GSettings
from errands.lib.logging import Log
from errands.lib.sync.sync import Sync
from errands.lib.utils import get_children
from errands.state import State
from errands.widgets.shared.components.boxes import ErrandsBox, ErrandsListBox
from errands.widgets.shared.components.buttons import ErrandsButton
from errands.widgets.shared.components.header_bar import ErrandsHeaderBar
from errands.widgets.shared.components.menus import ErrandsMenuItem, ErrandsSimpleMenu
from errands.widgets.shared.components.toolbar_view import ErrandsToolbarView
from errands.widgets.shared.titled_separator import TitledSeparator
from errands.widgets.tags.tags_sidebar_row import TagsSidebarRow
from errands.widgets.task_list.task_list import TaskList
from errands.widgets.task_list.task_list_sidebar_row import TaskListSidebarRow
from errands.widgets.today.today_sidebar_row import TodaySidebarRow
from errands.widgets.trash.trash_sidebar_row import TrashSidebarRow

# class SidebarPluginsList(Adw.Bin):
#     def __init__(self, sidebar: Sidebar):
#         super().__init__()
#         self.sidebar: Sidebar = sidebar
#         self._build_ui()
#         self.load_plugins()

#     def _build_ui(self) -> None:
#         self.plugins_list: Gtk.ListBox = Gtk.ListBox(css_classes=["navigation-sidebar"])
#         self.plugins_list.connect("row-selected", self._on_row_selected)
#         self.set_child(
#             Box(
#                 children=[SidebarListTitle(_("Plugins")), self.plugins_list],
#                 orientation="vertical",
#             )
#         )

#     def add_plugin(self, plugin_row: SidebarPluginListItem):
#         self.plugins_list.append(plugin_row)

#     def get_plugins(self) -> list[Gtk.ListBoxRow]:
#         return get_children(self.plugins_list)

#     def load_plugins(self):
#         plugin_loader: PluginsLoader = (
#             self.sidebar.window.get_application().plugins_loader
#         )
#         if not plugin_loader or not plugin_loader.plugins:
#             self.set_visible(False)
#             return
#         for plugin in plugin_loader.plugins:
#             self.add_plugin(SidebarPluginListItem(plugin, self.sidebar))

#     def _on_row_selected(self, _, row: Gtk.ListBoxRow):
#         if row:
#             row.activate()


# class SidebarPluginListItem(Gtk.ListBoxRow):
#     def __init__(self, plugin: PluginBase, sidebar: Sidebar):
#         super().__init__()
#         self.name = plugin.name
#         self.icon = plugin.icon
#         self.main_view = plugin.main_view
#         self.description = plugin.description
#         self.sidebar = sidebar
#         self._build_ui()

#     def _build_ui(self) -> None:
#         self.set_child(
#             Box(
#                 children=[
#                     Gtk.Image(icon_name=self.icon),
#                     Gtk.Label(label=self.name, halign=Gtk.Align.START),
#                 ],
#                 css_classes=["toolbar"],
#             )
#         )
#         ctrl: Gtk.GestureClick = Gtk.GestureClick()
#         ctrl.connect("released", self.do_activate)
#         self.add_controller(ctrl)

#         self.sidebar.window.stack.add_titled(self.main_view, self.name, self.name)

#     def do_activate(self, *args) -> None:
#         self.sidebar.window.stack.set_visible_child_name(self.name)
#         self.sidebar.task_lists.lists.unselect_all()


class Sidebar(Adw.Bin):
    def __init__(self) -> None:
        super().__init__()
        State.sidebar = self
        self.__build_ui()

    # ------ PRIVATE METHODS ------ #

    def __build_ui(self) -> None:
        # Add List button
        self.add_list_btn = ErrandsButton(
            icon_name="errands-add-symbolic",
            tooltip_text=_("Add List (Ctrl+A)"),
            on_click=self._on_add_list_btn_clicked,
        )
        add_list_ctrl = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        add_list_ctrl.add_shortcut(
            Gtk.Shortcut(
                action=Gtk.ShortcutAction.parse_string("activate"),
                trigger=Gtk.ShortcutTrigger.parse_string("<Control>a"),
            )
        )
        self.add_list_btn.add_controller(add_list_ctrl)

        # Sync indicator
        self.sync_indicator = Gtk.Spinner(
            spinning=True,
            visible=False,
            tooltip_text=_("Syncing..."),
        )

        # Status page
        self.status_page = Adw.StatusPage(
            title=_("Add new List"),
            description=_('Click "+" button'),
            icon_name="errands-lists-symbolic",
            css_classes=["compact"],
            vexpand=True,
        )

        # List box
        self.list_box = ErrandsListBox(
            activate_on_single_click=False,
            on_row_selected=self._on_row_selected,
            selection_mode=Gtk.SelectionMode.SINGLE,
            css_classes=["navigation-sidebar"],
            children=[
                TodaySidebarRow(),
                TagsSidebarRow(),
                TrashSidebarRow(),
            ],
        )
        self.status_page.bind_property(
            "visible",
            self.list_box,
            "visible",
            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.INVERT_BOOLEAN,
        )
        self.list_box.set_header_func(
            lambda row, before: (
                row.set_header(TitledSeparator(_("Task Lists"), (12, 12, 0, 2)))
                if isinstance(row, TaskListSidebarRow)
                and not isinstance(before, TaskListSidebarRow)
                else ...
            )
        )

        self.set_child(
            ErrandsToolbarView(
                top_bars=[
                    ErrandsHeaderBar(
                        title_widget=Gtk.Label(
                            label=_("Errands"),
                            css_classes=["heading"],
                        ),
                        start_children=[self.add_list_btn],
                        end_children=[
                            # Main Menu
                            Gtk.MenuButton(
                                primary=True,
                                tooltip_text=_("Main Menu"),
                                icon_name="open-menu-symbolic",
                                menu_model=ErrandsSimpleMenu(
                                    items=[
                                        ErrandsMenuItem(
                                            _("Sync / Fetch Tasks"), "app.sync"
                                        ),
                                        ErrandsMenuItem(
                                            _("Import Task List"), "app.import"
                                        ),
                                        ErrandsMenuItem(
                                            _("Preferences"), "app.preferences"
                                        ),
                                        ErrandsMenuItem(
                                            _("Keyboard Shortcuts"),
                                            "win.show-help-overlay",
                                        ),
                                        ErrandsMenuItem(
                                            _("About Errands"), "app.about"
                                        ),
                                        ErrandsMenuItem(_("Quit"), "app.quit"),
                                    ]
                                ),
                            ),
                            # Sync indicator
                            self.sync_indicator,
                        ],
                    )
                ],
                content=ErrandsBox(
                    orientation=Gtk.Orientation.VERTICAL,
                    children=[
                        Gtk.ScrolledWindow(
                            propagate_natural_height=True, child=self.list_box
                        ),
                        self.status_page,
                    ],
                ),
            )
        )

    def remove_task_list(self, row: TaskListSidebarRow) -> None:
        Log.debug(f"Sidebar: Delete list {row.uid}")
        self.list_box.select_row(row.get_prev_sibling())
        State.view_stack.remove(row.task_list)
        self.list_box.remove(row)
        State.trash_sidebar_row.update_ui()
        State.today_page.update_ui()
        self.update_status()

    def __select_last_opened_item(self) -> None:
        for row in self.rows:
            if hasattr(row, "name") and row.name == GSettings.get("last-open-list"):
                Log.debug("Sidebar: Select last opened page")
                if not row.get_realized():
                    row.connect("realize", lambda *_: self.list_box.select_row(row))
                else:
                    self.list_box.select_row(row)
                break

    def update_status(self) -> None:
        length: int = len(self.task_lists_rows)
        self.status_page.set_visible(length == 0)
        if length == 0:
            State.view_stack.set_visible_child_name("errands_status_page")

    # ------ PROPERTIES ------ #

    @property
    def rows(self) -> list[Gtk.ListBoxRow]:
        """Get all rows"""
        return get_children(self.list_box)

    @property
    def task_lists_rows(self) -> list[TaskListSidebarRow]:
        """Get only task list rows"""
        return [r for r in self.rows if isinstance(r, TaskListSidebarRow)]

    @property
    def task_lists(self) -> list[TaskList]:
        return [lst.task_list for lst in self.task_lists_rows]

    # ------ PUBLIC METHODS ------ #

    def add_task_list(self, list_dict: TaskListData) -> TaskListSidebarRow:
        Log.debug(f"Sidebar: Add Task List '{list_dict.uid}'")
        row: TaskListSidebarRow = TaskListSidebarRow(list_dict)
        self.list_box.append(row)
        self.status_page.set_visible(False)
        return row

    def load_task_lists(self) -> None:
        Log.debug("Sidebar: Load Task Lists")

        list_added: bool = False

        for list in (
            list for list in UserData.get_lists_as_dicts() if not list.deleted
        ):
            self.add_task_list(list)
            list_added = True

        self.__select_last_opened_item()
        if list_added:
            self.status_page.set_visible(False)

    def update_task_lists(self, update_lists_ui: bool = True):
        lists: list[TaskListData] = UserData.get_lists_as_dicts()

        # Delete lists
        uids: list[str] = [lst.uid for lst in lists]
        for row in self.task_lists_rows:
            if row.uid not in uids:
                self.remove_task_list(row)

        # Add lists
        lists_uids = [lst.uid for lst in self.task_lists_rows]
        for lst in lists:
            if lst.uid not in lists_uids:
                self.add_task_list(lst)

        if update_lists_ui:
            for row in self.rows:
                if hasattr(row, "update_ui"):
                    row.update_ui()

    def update_ui(self) -> None:
        Log.debug("Sidebar: Update UI")

        self.update_task_lists()

        # Update rows
        for row in self.rows:
            if hasattr(row, "update_ui"):
                row.update_ui()

        self.update_status()

    # ------ TEMPLATE HANDLERS ------ #

    def _on_add_list_btn_clicked(self, btn: ErrandsButton) -> None:
        lists_names: list[str] = [i.name for i in UserData.get_lists_as_dicts()]

        def _entry_activated(_, dialog):
            if dialog.get_response_enabled("add"):
                dialog.response("add")
                dialog.close()

        def _entry_changed(entry: Gtk.Entry, _, dialog):
            text = entry.props.text.strip(" \n\t")
            dialog.set_response_enabled("add", text and text not in lists_names)

        def _confirm(_, res, entry: Gtk.Entry):
            if res == "cancel":
                return

            name = entry.props.text.rstrip().lstrip()
            list_dict = UserData.add_list(name)
            row = self.add_task_list(list_dict)
            row.activate()
            Sync.sync()

        entry = Gtk.Entry(placeholder_text=_("New List Name"))
        dialog = Adw.MessageDialog(
            transient_for=State.main_window,
            hide_on_close=True,
            heading=_("Add List"),
            default_response="add",
            close_response="cancel",
            extra_child=entry,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("add", _("Add"))
        dialog.set_response_enabled("add", False)
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", _confirm, entry)
        entry.connect("activate", _entry_activated, dialog)
        entry.connect("notify::text", _entry_changed, dialog)
        dialog.present()

    def _on_row_selected(self, _, row: Gtk.ListBoxRow) -> None:
        if row:
            row.activate()
