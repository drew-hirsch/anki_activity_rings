from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import unquote

from aqt import dialogs, gui_hooks, mw
from aqt.operations import QueryOp
from aqt.qt import QInputDialog, QLineEdit, Qt

from .config import ConfigLoadResult, load_config, load_config_from_object
from .settings import SourcePickerDialog, install_settings_entrypoints, open_settings_dialog
from .stats import DashboardSnapshot, collect_dashboard_stats
from .web import MESSAGE_PREFIX, render_dashboard_html

LOGGER = logging.getLogger(__name__.split(".", 1)[0])
MODULE = __name__.split(".", 1)[0]


def _configure_logging() -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


class DashboardRingController:
    def __init__(self) -> None:
        _configure_logging()
        self._registered = False
        self._config_result: ConfigLoadResult | None = None
        self._logged_warnings: tuple[str, ...] = tuple()
        self._cached_snapshot: DashboardSnapshot | None = None
        self._dirty = True
        self._loading = False
        self._refresh_queued = False
        self._request_serial = 0
        self._last_refresh_at = 0.0

    def register(self) -> None:
        if self._registered:
            return
        self._registered = True

        gui_hooks.main_window_did_init.append(self._on_main_window_did_init)
        gui_hooks.profile_did_open.append(self._on_profile_did_open)
        gui_hooks.state_did_change.append(self._on_state_did_change)
        gui_hooks.deck_browser_will_render_content.append(self._inject_deck_browser)
        gui_hooks.overview_will_render_content.append(self._inject_overview)
        gui_hooks.sync_did_finish.append(self._on_sync_did_finish)
        gui_hooks.theme_did_change.append(self._on_theme_did_change)
        gui_hooks.webview_did_receive_js_message.append(self._on_webview_did_receive_js_message)

    def _on_main_window_did_init(self) -> None:
        install_settings_entrypoints()
        mw.addonManager.setConfigUpdatedAction(MODULE, self._on_config_updated)
        self._ensure_snapshot_if_visible()

    def _on_profile_did_open(self) -> None:
        self._invalidate(schedule=True)

    def _on_state_did_change(self, new_state: str, _old_state: str) -> None:
        if new_state in {"deckBrowser", "overview"}:
            self._ensure_snapshot_if_visible()

    def _on_sync_did_finish(self) -> None:
        self._invalidate(schedule=True)

    def _on_theme_did_change(self) -> None:
        self._refresh_visible_surface()

    def _on_config_updated(self, new_config: dict) -> None:
        self._set_config_result(load_config_from_object(new_config))
        self._invalidate(schedule=True)

    def _on_webview_did_receive_js_message(
        self,
        handled: tuple[bool, Any],
        message: str,
        _context: object,
    ) -> tuple[bool, Any]:
        if handled[0]:
            return handled
        if not isinstance(message, str) or not message.startswith(MESSAGE_PREFIX):
            return handled

        payload = message[len(MESSAGE_PREFIX) :]
        if payload == "settings":
            open_settings_dialog()
            return (True, None)
        if payload.startswith("picktag:"):
            widget_id = payload.split(":", 1)[1].strip()
            if widget_id:
                self._open_source_picker_for_widget(widget_id)
            return (True, None)
        if payload.startswith("search:"):
            query = unquote(payload.split(":", 1)[1]).strip()
            if query:
                self._open_browser(query)
            return (True, None)
        return handled

    def _config(self) -> ConfigLoadResult:
        if self._config_result is None:
            self._set_config_result(load_config())
        assert self._config_result is not None
        return self._config_result

    def _set_config_result(self, result: ConfigLoadResult) -> None:
        self._config_result = result
        if result.warnings != self._logged_warnings:
            for warning in result.warnings:
                LOGGER.warning(warning)
            self._logged_warnings = result.warnings

    def _invalidate(self, *, schedule: bool) -> None:
        self._dirty = True
        if schedule:
            self._ensure_snapshot_if_visible()

    def _snapshot_is_fresh(self) -> bool:
        if not self._cached_snapshot or self._dirty:
            return False
        ttl_seconds = self._config().config.global_config.cache_ttl_seconds
        return (time.time() - self._cached_snapshot.generated_at) <= ttl_seconds

    def _ensure_snapshot_if_visible(self) -> None:
        if mw.state not in {"deckBrowser", "overview"}:
            return
        self._ensure_snapshot(force=False)

    def _ensure_snapshot(self, *, force: bool) -> None:
        config = self._config().config
        if not getattr(mw, "col", None):
            return
        if not config.widgets:
            self._cached_snapshot = None
            self._loading = False
            self._dirty = False
            return
        if self._loading:
            self._refresh_queued = True
            return
        if not force and self._snapshot_is_fresh():
            return

        self._loading = True
        self._refresh_queued = False
        self._request_serial += 1
        request_id = self._request_serial

        op = QueryOp(
            parent=mw,
            op=lambda col, cfg=config: collect_dashboard_stats(col, cfg),
            success=lambda snapshot, rid=request_id: self._on_snapshot_ready(rid, snapshot),
        )
        op.failure(lambda error, rid=request_id: self._on_snapshot_failed(rid, error))
        op.run_in_background()

    def _on_snapshot_ready(self, request_id: int, snapshot: DashboardSnapshot) -> None:
        if request_id != self._request_serial:
            return
        self._cached_snapshot = snapshot
        self._dirty = False
        self._loading = False
        self._refresh_visible_surface()
        if self._refresh_queued:
            self._refresh_queued = False
            self._ensure_snapshot(force=True)

    def _on_snapshot_failed(self, request_id: int, error: Exception) -> None:
        if request_id != self._request_serial:
            return
        self._loading = False
        LOGGER.error(
            "Failed to collect activity ring stats.",
            exc_info=(type(error), error, error.__traceback__),
        )
        if self._refresh_queued:
            self._refresh_queued = False
            self._ensure_snapshot(force=True)

    def _refresh_visible_surface(self) -> None:
        now = time.time()
        if now - self._last_refresh_at < 0.35:
            return
        self._last_refresh_at = now
        if mw.state == "deckBrowser" and getattr(mw, "deckBrowser", None):
            mw.deckBrowser.refresh()
        elif mw.state == "overview" and getattr(mw, "overview", None):
            mw.overview.refresh()

    def _html_for_surface(self, surface: str) -> str:
        config = self._config().config
        if surface not in config.global_config.show_on_screens:
            return ""
        return render_dashboard_html(
            config,
            self._cached_snapshot,
            surface=surface,
            is_loading=self._loading,
        )

    def _inject_deck_browser(self, _deck_browser, content) -> None:
        html = self._html_for_surface("deckBrowser")
        if html:
            content.stats = self._insert_dashboard_html(content.stats or "", html)

    def _inject_overview(self, _overview, content) -> None:
        html = self._html_for_surface("overview")
        if html:
            content.table = self._insert_dashboard_html(content.table or "", html)

    def _insert_dashboard_html(self, existing: str, html: str) -> str:
        position = self._config().config.global_config.dashboard_position
        if position == "bottom":
            return (existing or "") + html
        return html + (existing or "")

    def _open_browser(self, query: str) -> None:
        browser = dialogs.open("Browser", mw)
        browser.search_for(query)
        browser.setWindowState(
            browser.windowState()
            & ~Qt.WindowState.WindowMinimized
            | Qt.WindowState.WindowActive
        )

    def _open_source_picker_for_widget(self, widget_id: str) -> None:
        raw_config = mw.addonManager.getConfig(MODULE) or {}
        widgets = raw_config.get("widgets", [])
        if not isinstance(widgets, list):
            return

        widget_payload = next(
            (
                widget
                for widget in widgets
                if isinstance(widget, dict) and str(widget.get("id", "")).strip() == widget_id
            ),
            None,
        )
        if not isinstance(widget_payload, dict):
            return

        source = widget_payload.get("source", {})
        if not isinstance(source, dict):
            return

        tags: list[str] = []
        decks: list[str] = []
        if getattr(mw, "col", None):
            for tag in mw.col.tags.all():
                name = getattr(tag, "name", tag)
                if isinstance(name, str) and name.strip():
                    tags.append(name.strip())
            for deck_name_id in mw.col.decks.all_names_and_ids():
                name = getattr(deck_name_id, "name", "")
                if isinstance(name, str) and name.strip():
                    decks.append(name.strip())

        current_type = str(source.get("type", "tag")).strip()
        current_kind = "deck" if current_type == "deck" else "tag"
        current_value = str(source.get("deck" if current_kind == "deck" else "tag", "")).strip()
        dialog = SourcePickerDialog(
            sorted(set(tags), key=str.casefold),
            sorted(set(decks), key=str.casefold),
            current_kind=current_kind,
            current_value=current_value,
            allow_kind_switch=True,
            parent=mw,
        )
        if not dialog.exec():
            return

        selected_kind = dialog.selected_kind()
        selected_value = dialog.selected_value().strip()
        if not selected_value:
            return

        source["type"] = selected_kind
        if selected_kind == "deck":
            source["deck"] = selected_value
            source["tag"] = ""
            source["search"] = ""
            source["include_children"] = False
            source["scope"] = "all"
        else:
            source["tag"] = selected_value
            source["deck"] = ""
            source["search"] = ""
            source["include_children"] = bool(source.get("include_children", True))
            source["scope"] = "all"

        current_title = str(widget_payload.get("title", "")).strip()
        default_title = selected_value.split("::")[-1].strip()
        if selected_kind == "tag":
            default_title = default_title.lstrip("#").strip()
        default_title = default_title or ("Deck" if selected_kind == "deck" else "Tag")
        suggested_title = current_title if current_title and current_title not in {"Tag", "Deck"} else default_title
        title, accepted = QInputDialog.getText(
            mw,
            "Widget Title",
            "Choose a title for this widget:",
            QLineEdit.EchoMode.Normal,
            suggested_title,
        )
        if accepted and title.strip():
            widget_payload["title"] = title.strip()
        elif not current_title or current_title in {"Tag", "Deck"}:
            widget_payload["title"] = default_title
        mw.addonManager.writeConfig(MODULE, raw_config)
        self._on_config_updated(raw_config)


_CONTROLLER = DashboardRingController()


def register_addon() -> None:
    _CONTROLLER.register()


def notify_config_saved(new_config: dict) -> None:
    _CONTROLLER._on_config_updated(new_config)
