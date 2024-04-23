# Copyright 2023-2024 Vlad Krupinskii <mrvladus@yandex.ru>
# SPDX-License-Identifier: MIT

import datetime
import time
from dataclasses import asdict, dataclass, field

import urllib3
from caldav import Calendar, DAVClient, Principal, Todo
from caldav.elements import dav

from errands.lib.data import TaskData, TaskListData, UserData
from errands.lib.gsettings import GSettings
from errands.lib.logging import Log
from errands.lib.utils import idle_add
from errands.state import State


@dataclass
class UpdateUIArgs:
    update_trash: bool = False
    update_tags: bool = False
    tasks_to_add: list[TaskData] = field(default_factory=lambda: [])
    tasks_to_update: list[TaskData] = field(default_factory=lambda: [])
    tasks_to_purge: list[TaskData] = field(default_factory=lambda: [])
    lists_to_add: list[TaskListData] = field(default_factory=lambda: [])
    lists_to_update_name: list[str] = field(default_factory=lambda: [])
    lists_to_purge_uids: list[str] = field(default_factory=lambda: [])


class SyncProviderCalDAV:
    can_sync: bool = False
    calendars: list[Calendar] = None

    def __init__(self, testing: bool, name: str = "CalDAV") -> bool:
        Log.info(f"Sync: Initialize '{name}' sync provider")

        self.name: str = name
        self.testing: bool = testing  # Only for connection test

        if not self._check_credentials():
            return

        self._check_url()
        return self._connect()

    def _check_credentials(self) -> bool:
        Log.debug("Sync: Checking credentials")

        self.url: str = GSettings.get("sync-url")
        self.username: str = GSettings.get("sync-username")
        self.password: str = GSettings.get_secret(self.name)

        if self.url == "" or self.username == "" or self.password == "":
            Log.error(f"Sync: Not all {self.name} credentials provided")
            if not self.testing:
                State.main_window.add_toast(
                    _("Not all sync credentials provided. Please check settings.")
                )
            return False

        return True

    def _check_url(self) -> None:
        Log.debug("Sync: Checking URL")

        self.url = GSettings.get("sync-url")

        Log.debug(f"Sync: URL is set to {self.url}")

    def _connect(self) -> bool:
        Log.debug("Sync: Attempting connection")

        urllib3.disable_warnings()

        with DAVClient(
            url=self.url,
            username=self.username,
            password=self.password,
            ssl_verify_cert=False,
        ) as client:
            try:
                self.principal: Principal = client.principal()
                Log.info(f"Sync: Connected to {self.name} server at '{self.url}'")
                self.can_sync = True
                self.calendars = [
                    cal
                    for cal in self.principal.calendars()
                    if "VTODO" in cal.get_supported_components()
                ]
            except Exception as e:
                time.sleep(2)
                Log.error(
                    f"Sync: Can't connect to {self.name} server at '{self.url}'. {e}"
                )
                if not self.testing:
                    State.main_window.add_toast(
                        _("Can't connect to CalDAV server at:") + " " + self.url
                    )

    def __get_task(self, calendar: Calendar, task_uid: str):
        return [t for t in self.__get_tasks(calendar) if t.uid == task_uid][0]

    def __get_tasks(self, calendar: Calendar) -> list[TaskData]:
        """
        Get todos from calendar and convert them to TaskData list
        """

        # try:
        Log.debug(f"Sync: Getting tasks for list '{calendar.id}'")
        todos: list[Todo] = calendar.todos(include_completed=True)
        tasks: list[TaskData] = []
        for todo in todos:
            task: TaskData = TaskData(
                color=str(todo.icalendar_component.get("x-errands-color", "")),
                completed=str(todo.icalendar_component.get("status", ""))
                == "COMPLETED",
                notes=str(todo.icalendar_component.get("description", "")),
                parent=str(todo.icalendar_component.get("related-to", "")),
                percent_complete=int(
                    todo.icalendar_component.get("percent-complete", 0)
                ),
                priority=int(todo.icalendar_component.get("priority", 0)),
                text=str(todo.icalendar_component.get("summary", "")),
                uid=str(todo.icalendar_component.get("uid", "")),
                list_uid=calendar.id,
            )

            # Set tags
            if (tags := todo.icalendar_component.get("categories", "")) != "":
                task.tags = [
                    i.to_ical().decode("utf-8")
                    for i in (tags if isinstance(tags, list) else tags.cats)
                ]
            else:
                task.tags = []

            # Set dates

            if todo.icalendar_component.get("due", "") != "":
                task.due_date = (
                    todo.icalendar_component.get("due", "")
                    .to_ical()
                    .decode("utf-8")
                    .strip("Z")
                )
                if task.due_date and "T" not in task.due_date:
                    task.due_date += "T000000"
            else:
                task.due_date = ""

            if todo.icalendar_component.get("dtstart", "") != "":
                task.start_date = (
                    todo.icalendar_component.get("dtstart", "")
                    .to_ical()
                    .decode("utf-8")
                    .strip("Z")
                )
                if task.start_date and "T" not in task.start_date:
                    task.start_date += "T000000"
            else:
                task.start_date = ""

            if todo.icalendar_component.get("dtstamp", "") != "":
                task.created_at = (
                    todo.icalendar_component.get("dtstamp", "")
                    .to_ical()
                    .decode("utf-8")
                    .strip("Z")
                )
            else:
                task.created_at = ""

            if todo.icalendar_component.get("last-modified", "") != "":
                task.changed_at = (
                    todo.icalendar_component.get("last-modified", "")
                    .to_ical()
                    .decode("utf-8")
                    .strip("Z")
                )
            else:
                task.changed_at = ""

            tasks.append(task)
        return tasks
        # except Exception as e:
        #     Log.error(f"Sync: Can't get tasks from remote. {e}")
        #     return []

    def __update_calendars(self) -> bool:
        try:
            self.calendars = [
                cal
                for cal in self.principal.calendars()
                if "VTODO" in cal.get_supported_components()
            ]
            return True
        except Exception as e:
            Log.error(f"Sync: Can't get caldendars from remote. {e}")
            return False

    @idle_add
    def __finish_sync(self) -> None:
        """Update UI thread safe"""

        Log.debug("Sync: Update UI")

        # Remove lists
        for lst in State.get_task_lists():
            if lst.list_uid in self.update_ui_args.lists_to_purge_uids:
                Log.debug(f"Sync: Remove Task List '{lst.list_uid}'")
                lst.purge()

        # Add lists
        for lst in self.update_ui_args.lists_to_add:
            State.sidebar.add_task_list(lst)

        # Rename lists
        for uid in self.update_ui_args.lists_to_update_name:
            task_list = State.get_task_list(uid)
            task_list.update_title()
            task_list.sidebar_row.update_ui(False)

        # Remove tasks
        for task in self.update_ui_args.tasks_to_purge:
            State.get_task(task.list_uid, task.uid).purge()
            State.get_task_list(task.list_uid).update_title()

        # Add tasks
        lists_to_add_uids: list[str] = [
            lst.uid for lst in self.update_ui_args.lists_to_add
        ]
        parents_added_uids: list[str] = []
        for task in self.update_ui_args.tasks_to_add:
            if task.list_uid not in lists_to_add_uids:
                if task.parent not in parents_added_uids:
                    State.get_task_list(task.list_uid).add_task(task)
                    parents_added_uids.append(task.uid)

        # Update tasks
        for task in self.update_ui_args.tasks_to_update:
            try:
                State.get_task(task.list_uid, task.uid).update_ui(False)
            except Exception:
                pass

        # Update tags
        if self.update_ui_args.update_tags:
            State.tags_sidebar_row.update_ui()

        # Update trash
        if self.update_ui_args.update_trash:
            State.trash_sidebar_row.update_ui()

    def sync(self) -> None:
        Log.info("Sync: Sync tasks with remote")

        if not self.__update_calendars():
            return

        self.update_ui_args: UpdateUIArgs = UpdateUIArgs()

        self.__add_local_lists()

        remote_lists_uids = [c.id for c in self.calendars]

        for list in UserData.get_lists_as_dicts():
            # Rename list
            for cal in self.calendars:
                # Rename list on remote
                if cal.id == list.uid and cal.name != list.name and not list.synced:
                    self.__rename_remote_list(cal, list)

                # Rename local list
                elif cal.id == list.uid and cal.name != list.name and list.synced:
                    self.__rename_local_list(cal, list)

            # Delete local list deleted on remote
            if list.uid not in remote_lists_uids and list.synced and not list.deleted:
                self.__delete_local_list(cal, list)

            # Delete remote list deleted locally
            elif list.uid in remote_lists_uids and list.deleted and list.synced:
                self.__delete_remote_list(list)

            # Create new remote list
            elif (
                list.uid not in remote_lists_uids
                and not list.synced
                and not list.deleted
            ):
                self.__create_local_list(list)

        if not self.__update_calendars():
            return

        for calendar in self.calendars:
            # Get tasks
            local_tasks = UserData.get_tasks_as_dicts(calendar.id)
            local_ids = [t.uid for t in local_tasks]
            remote_tasks = self.__get_tasks(calendar)
            remote_ids = [task.uid for task in remote_tasks]
            deleted_uids = [t.uid for t in UserData.get_tasks_as_dicts() if t.deleted]

            for task in local_tasks:
                if task.uid in remote_ids and task.synced:
                    self.__update_local_task(calendar, task)

                elif task.uid in remote_ids and not task.synced:
                    self.__update_remote_task(calendar, task)

                elif task.uid not in remote_ids and not task.synced:
                    self.__create_remote_task(calendar, task)

                elif task.uid not in remote_ids and task.synced:
                    self.__delete_local_task(calendar, task)

                elif task.uid in remote_ids and task.deleted:
                    self.__delete_remote_task(calendar, task)

            # Create new local task that was created on remote
            for task in remote_tasks:
                if task.uid not in local_ids and task.uid not in deleted_uids:
                    self.__create_local_task(calendar, task)

        self.__finish_sync()

    # ----- SYNC LISTS FUNCTIONS ----- #

    def __add_local_lists(self) -> None:
        user_lists_uids = [lst.uid for lst in UserData.get_lists_as_dicts()]
        for calendar in self.calendars:
            if calendar.id not in user_lists_uids:
                Log.debug(f"Sync: Copy list from remote '{calendar.id}'")
                new_list: TaskListData = UserData.add_list(
                    name=calendar.name, uuid=calendar.id, synced=True
                )
                self.update_ui_args.lists_to_add.append(new_list)

    def __rename_remote_list(self, cal: Calendar, list: TaskListData) -> None:
        Log.debug(f"Sync: Rename remote list '{list.uid}'")

        cal.set_properties([dav.DisplayName(list.name)])
        UserData.update_list_prop(cal.id, "synced", False)

    def __rename_local_list(self, cal: Calendar, list: TaskListData) -> None:
        Log.debug(f"Sync: Rename local list '{list.uid}'")

        UserData.update_list_props(cal.id, ["name", "synced"], [cal.name, True])
        self.update_ui_args.lists_to_update_name.append(cal.id)
        self.update_ui_args.update_trash = True

    def __delete_local_list(self, cal: Calendar, list: TaskListData) -> None:
        Log.debug(f"Sync: Delete local list deleted on remote '{list.uid}'")

        UserData.delete_list(list.uid)
        self.update_ui_args.lists_to_purge_uids.append(list.uid)
        self.update_ui_args.update_trash = True
        self.update_ui_args.update_tags = True

    def __delete_remote_list(self, list: TaskListData) -> None:
        for cal in self.calendars:
            if cal.id == list.uid:
                Log.debug(f"Sync: Delete list on remote '{cal.id}'")
                cal.delete()
                UserData.delete_list(cal.id)
                return

    def __create_local_list(self, list: TaskListData) -> None:
        Log.debug(f"Sync: Create list on remote {list.uid}")
        try:
            self.principal.make_calendar(
                cal_id=list.uid,
                supported_calendar_component_set=["VTODO"],
                name=list.name,
            )
        except Exception as e:
            Log.error(f"Sync: Can't create local list '{list.uid}'. {e}")
        UserData.update_list_prop(list.uid, "synced", True)

    # ----- SYNC TASKS FUNCTIONS ----- #

    def __update_local_task(self, calendar: Calendar, task: TaskData):
        remote_task: TaskData = self.__get_task(calendar, task.uid)
        remote_task_keys = asdict(remote_task).keys()
        updated_props = []
        updated_values = []
        for key in remote_task_keys:
            if (
                key not in "synced trash expanded toolbar_shown deleted notified"
                and getattr(remote_task, key) != getattr(task, key)
            ):
                updated_props.append(key)
                updated_values.append(getattr(remote_task, key))
        if updated_props:
            Log.debug(f"Sync: Update local task '{task.uid}'. Updated: {updated_props}")
            UserData.update_props(calendar.id, task.uid, updated_props, updated_values)
            self.update_ui_args.tasks_to_update.append(task)
            self.update_ui_args.update_tags = True
            self.update_ui_args.update_trash = True

    def __update_remote_task(self, calendar: Calendar, task: TaskData) -> None:
        try:
            Log.debug(f"Sync: Update remote task '{task.uid}'")
            todo: Todo = calendar.todo_by_uid(task.uid)
            todo.uncomplete()
            todo.icalendar_component["summary"] = task.text

            if task.due_date:
                todo.icalendar_component["due"] = task.due_date
            else:
                todo.icalendar_component.pop("DUE", None)

            if task.start_date:
                todo.icalendar_component["dtstart"] = task.start_date
            else:
                todo.icalendar_component.pop("DTSTART", None)

            if task.created_at:
                todo.icalendar_component["dtstamp"] = task.created_at
            else:
                todo.icalendar_component.pop("DTSTAMP", None)

            if task.changed_at:
                todo.icalendar_component["last-modified"] = task.changed_at
            else:
                todo.icalendar_component.pop("LAST-MODIFIED", None)

            todo.icalendar_component["percent-complete"] = int(task.percent_complete)
            todo.icalendar_component["description"] = task.notes
            todo.icalendar_component["priority"] = task.priority
            todo.icalendar_component["categories"] = task.tags if task.tags else []
            todo.icalendar_component["related-to"] = task.parent
            todo.icalendar_component["x-errands-color"] = task.color
            todo.save()
            if task.completed:
                todo.complete()
            UserData.update_props(calendar.id, task.uid, ["synced"], [True])
        except Exception as e:
            Log.error(f"Sync: Can't update task on remote '{task.uid}'. {e}")

    def __create_remote_task(self, calendar: Calendar, task: TaskData) -> None:
        Log.debug(f"Sync: Create remote task '{task.uid}'")

        try:
            new_todo = calendar.save_todo(
                categories=",".join(task.tags) if task.tags else None,
                description=task.notes,
                dtstart=(
                    datetime.datetime.fromisoformat(task.start_date)
                    if task.start_date
                    else None
                ),
                due=(
                    datetime.datetime.fromisoformat(task.due_date)
                    if task.due_date
                    else None
                ),
                priority=task.priority,
                percent_complete=task.percent_complete,
                related_to=task.parent,
                summary=task.text,
                uid=task.uid,
                x_errands_color=task.color,
            )
            if task.completed:
                new_todo.complete()
            UserData.update_props(calendar.id, task.uid, ["synced"], [True])
        except Exception as e:
            Log.error(f"Sync: Can't create new task on remote: {task.uid}. {e}")

    def __delete_local_task(self, calendar: Calendar, task: TaskData) -> None:
        Log.debug(f"Sync: Delete local task '{task.uid}'")

        UserData.delete_task(calendar.id, task.uid)
        self.update_ui_args.tasks_to_purge.append(task)
        self.update_ui_args.update_trash = True
        self.update_ui_args.update_tags = True

    def __delete_remote_task(self, calendar: Calendar, task: TaskData) -> None:
        Log.debug(f"Sync: Delete remote task '{task.uid}'")

        try:
            if todo := calendar.todo_by_uid(task.uid):
                todo.delete()
        except Exception as e:
            Log.error(f"Sync: Can't delete task from remote: '{task.uid}'. {e}")

    def __create_local_task(self, calendar: Calendar, task: TaskData) -> None:
        Log.debug(
            f"Sync: Copy new task from remote to list '{calendar.id}': {task.uid}"
        )

        new_task: TaskData = UserData.add_task(**asdict(task))
        self.update_ui_args.tasks_to_add.append(new_task)
