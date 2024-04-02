from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw  # type:ignore

from __main__ import PROFILE


if TYPE_CHECKING:
    from errands.application import ErrandsApplication
    from errands.widgets.sidebar.sidebar import Sidebar
    from errands.widgets.tags.tags import Tags
    from errands.widgets.tags.tags_sidebar_row import TagsSidebarRow
    from errands.widgets.task.task import Task
    from errands.widgets.task_list.task_list import TaskList
    from errands.widgets.today.today import Today
    from errands.widgets.today.today_sidebar_row import TodaySidebarRow
    from errands.widgets.trash.trash_sidebar_row import TrashSidebarRow
    from errands.widgets.window import Window
    from errands.widgets.trash.trash import Trash


class State:
    """Application state class for accessing core widgets globally
    and some utils for quick access to deeper widgets"""

    profile: str = PROFILE
    # Application
    application: ErrandsApplication = None
    # Main window
    main_window: Window = None
    toast_overlay: Adw.ToastOverlay = None
    split_view: Adw.NavigationSplitView = None
    # View Stack
    view_stack: Adw.ViewStack = None
    today_page: Today = None
    tags_page: Tags = None
    trash_page: Trash = None
    # Sidebar
    sidebar: Sidebar = None
    today_sidebar_row: TodaySidebarRow = None
    tags_sidebar_row: TagsSidebarRow = None
    trash_sidebar_row: TrashSidebarRow = None

    @property
    def task_lists(cls) -> list[TaskList]:
        """All Task Lists"""

        return cls.sidebar.task_lists

    @property
    def tasks(cls) -> list[Task]:
        """All Tasks in all Task Lists"""

        all_tasks: list[Task] = []
        for list in cls.task_lists:
            all_tasks.extend(list.all_tasks)
        return all_tasks
