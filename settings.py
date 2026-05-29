from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QAbstractItemView,
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    QTimer,
)
from aqt.utils import qconnect, restoreGeom, saveGeom, tooltip
from aqt.webview import AnkiWebView

from .config import (
    MODULE,
    addon_config_to_dict,
    default_config_dict,
    default_query_payload,
    default_ring_payload,
    default_source_payload,
    default_today_widget_payload,
    default_widget_payload,
    load_config,
    load_config_from_json_string,
    load_config_from_object,
)
from .metrics import (
    BUILTIN_TODAY_ALL_COMPLETED,
    BUILTIN_TODAY_ALL_TOTAL,
    builtin_metric_definitions,
    builtin_metric_description,
    builtin_metric_label,
)
from .stats import DashboardSnapshot, WidgetSnapshot, collect_dashboard_stats
from .web import render_dashboard_html

ADDON_NAME = "Activity Rings"
GEOMETRY_KEY = "activity_rings_dashboard_settings"
_MENU_ACTION: QAction | None = None


def _slugify(text: str, fallback: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or fallback


def _source_summary(widget_payload: dict[str, Any]) -> str:
    source = widget_payload.get("source", {})
    if not isinstance(source, dict):
        return "No source"
    source_type = str(source.get("type", "tag")).strip()
    if source_type == "today":
        scope = str(source.get("scope", "all")).strip()
        if scope == "deck":
            return str(source.get("deck", "")).strip() or "Today's Progress · Choose a deck"
        return "Today's Progress · All Decks"
    if source_type == "search":
        return str(source.get("search", "")).strip() or "Search source"
    if source_type == "deck":
        return str(source.get("deck", "")).strip() or "No deck selected"
    return str(source.get("tag", "")).strip() or "No tag selected"


def _deepcopy_widget(widget_payload: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(widget_payload)


def _default_ring_payload_for_widget(widget_payload: dict[str, Any], ring_index: int) -> dict[str, Any]:
    source = widget_payload.get("source", {})
    if isinstance(source, dict) and str(source.get("type", "tag")) == "today":
        templates = list(default_today_widget_payload()["rings"])
        templates.append(
            {
                "id": "today_all_completed",
                "enabled": True,
                "label": "All Done",
                "metric": default_query_payload(builtin_name=BUILTIN_TODAY_ALL_COMPLETED),
                "denominator": default_query_payload(builtin_name=BUILTIN_TODAY_ALL_TOTAL),
                "color": "auto",
                "track_color": "auto",
            }
        )
        return deepcopy(templates[ring_index % len(templates)])
    return default_ring_payload(ring_index)


class ColorField(QWidget):
    def __init__(self, *, allow_auto: bool, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allow_auto = allow_auto
        self._callbacks: list[Callable[[], None]] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.swatch = QLabel(self)
        self.swatch.setFixedSize(18, 18)
        layout.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignVCenter)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.edit, 1)

        self.pick_button = QPushButton("Pick", self)
        self.pick_button.setAutoDefault(False)
        self.pick_button.setMaximumWidth(56)
        layout.addWidget(self.pick_button)

        if allow_auto:
            self.auto_button = QPushButton("Auto", self)
            self.auto_button.setAutoDefault(False)
            self.auto_button.setMaximumWidth(56)
            layout.addWidget(self.auto_button)
            qconnect(self.auto_button.clicked, self._set_auto)
        else:
            self.auto_button = None

        qconnect(self.pick_button.clicked, self._pick_color)
        self.edit.textChanged.connect(self._notify)
        self.edit.textChanged.connect(self._update_swatch)
        self._update_swatch()

    def connect_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str | None) -> None:
        self.edit.setText((value or "").strip())
        self._update_swatch()

    def _set_auto(self) -> None:
        self.edit.clear()
        self._notify()

    def _pick_color(self) -> None:
        color = QColor(self.text()) if self.text() else QColor()
        chosen = QColorDialog.getColor(color, self, "Choose Color")
        if chosen.isValid():
            self.edit.setText(chosen.name())
            self._notify()

    def _update_swatch(self) -> None:
        value = self.text()
        color = QColor(value)
        if color.isValid():
            self.swatch.setStyleSheet(
                f"background: {color.name()}; border-radius: 9px; border: 1px solid rgba(0,0,0,0.18);"
            )
        elif self._allow_auto and not value:
            self.swatch.setStyleSheet(
                "background: rgba(127,127,127,0.15); border-radius: 9px; border: 1px dashed rgba(127,127,127,0.45);"
            )
        else:
            self.swatch.setStyleSheet(
                "background: rgba(220,53,69,0.12); border-radius: 9px; border: 1px solid rgba(220,53,69,0.35);"
            )

    def _notify(self, *_args) -> None:
        self._update_swatch()
        for callback in self._callbacks:
            callback()


class QueryFieldEditor(QWidget):
    CUSTOM_VALUE = "__custom_search__"

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._callbacks: list[Callable[[], None]] = []
        self._definitions = builtin_metric_definitions()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = QComboBox(self)
        layout.addWidget(self.combo)

        for metric_name, definition in self._definitions.items():
            self.combo.addItem(definition.label, metric_name)
        self.combo.addItem("Custom Search", self.CUSTOM_VALUE)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Anki search query")
        layout.addWidget(self.search_edit)

        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.search_edit.textChanged.connect(self._notify)
        self._on_combo_changed()

    def connect_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def set_query_payload(self, payload: dict[str, Any]) -> None:
        query_type = str(payload.get("type", "builtin")).strip()
        if query_type == "search":
            index = self.combo.findData(self.CUSTOM_VALUE)
            self.combo.setCurrentIndex(max(index, 0))
            self.search_edit.setText(str(payload.get("search", "")).strip())
        else:
            name = str(payload.get("name", "")).strip()
            index = self.combo.findData(name)
            if index < 0:
                index = 0
            self.combo.setCurrentIndex(index)
            self.search_edit.clear()
        self._sync_tooltip()
        self._on_combo_changed()

    def payload(self) -> dict[str, Any]:
        current = self.combo.currentData()
        if current == self.CUSTOM_VALUE:
            return {"type": "search", "search": self.search_edit.text().strip()}
        return {"type": "builtin", "name": str(current)}

    def _on_combo_changed(self) -> None:
        is_custom = self.combo.currentData() == self.CUSTOM_VALUE
        self.search_edit.setVisible(is_custom)
        self._sync_tooltip()
        self._notify()

    def _sync_tooltip(self) -> None:
        current = self.combo.currentData()
        if current == self.CUSTOM_VALUE:
            tooltip_text = "Use any Anki search as this metric or denominator."
        else:
            tooltip_text = builtin_metric_description(str(current))
        self.combo.setToolTip(tooltip_text)
        self.search_edit.setToolTip(tooltip_text)

    def _notify(self, *_args) -> None:
        for callback in self._callbacks:
            callback()


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, *, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = content

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.toggle = QToolButton(self)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._content)

        qconnect(self.toggle.clicked, self._apply_state)
        self._apply_state()

    def _apply_state(self) -> None:
        expanded = self.toggle.isChecked()
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._content.setVisible(expanded)


class SourcePickerDialog(QDialog):
    def __init__(
        self,
        tags: list[str],
        decks: list[str],
        *,
        current_kind: str = "tag",
        current_value: str = "",
        allow_kind_switch: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent or mw)
        self._tags = sorted(tags, key=str.casefold)
        self._decks = sorted(decks, key=str.casefold)
        self._allow_kind_switch = allow_kind_switch
        self._selected_kind = current_kind if current_kind in {"tag", "deck"} else "tag"
        self._selected_values: dict[str, str] = {
            "tag": current_value.strip() if self._selected_kind == "tag" else "",
            "deck": current_value.strip() if self._selected_kind == "deck" else "",
        }
        self._items_by_value: dict[str, QTreeWidgetItem] = {}

        self.setWindowTitle("Choose Source")
        self.resize(560, 660)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        if self._allow_kind_switch:
            kind_row = QWidget(self)
            kind_layout = QHBoxLayout(kind_row)
            kind_layout.setContentsMargins(0, 0, 0, 0)
            kind_layout.setSpacing(8)
            kind_layout.addWidget(QLabel("Choose from", kind_row))
            self.kind_combo = QComboBox(kind_row)
            self.kind_combo.addItem("Tags", "tag")
            self.kind_combo.addItem("Decks", "deck")
            self.kind_combo.setCurrentIndex(max(self.kind_combo.findData(self._selected_kind), 0))
            kind_layout.addWidget(self.kind_combo)
            kind_layout.addStretch(1)
            root.addWidget(kind_row)
        else:
            self.kind_combo = None

        self.intro = QLabel("", self)
        self.intro.setWordWrap(True)
        root.addWidget(self.intro)

        self.search_edit = QLineEdit(self)
        root.addWidget(self.search_edit)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        root.addLayout(buttons)
        buttons.addStretch(1)
        self.use_button = QPushButton("", self)
        self.cancel_button = QPushButton("Cancel", self)
        buttons.addWidget(self.use_button)
        buttons.addWidget(self.cancel_button)

        self._build_tree()
        self._restore_selection(self._selected_values[self._selected_kind])
        self._sync_labels()

        self.search_edit.textChanged.connect(self._apply_filter)
        self.tree.itemSelectionChanged.connect(self._sync_selected_tag)
        self.tree.itemDoubleClicked.connect(self._accept_item)
        if self.kind_combo is not None:
            self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        qconnect(self.use_button.clicked, self.accept)
        qconnect(self.cancel_button.clicked, self.reject)

    def selected_kind(self) -> str:
        return self._selected_kind

    def selected_value(self) -> str:
        return self._selected_values.get(self._selected_kind, "")

    def selected_tag(self) -> str:
        return self._selected_values.get("tag", "")

    def selected_deck(self) -> str:
        return self._selected_values.get("deck", "")

    def accept(self) -> None:  # type: ignore[override]
        self._sync_selected_tag()
        selected = self.selected_value()
        if not selected:
            source_name = "tag" if self._selected_kind == "tag" else "deck"
            QMessageBox.information(self, f"Choose a {source_name.title()}", f"Select a {source_name} before continuing.")
            return
        super().accept()

    def _build_tree(self) -> None:
        nodes: dict[str, QTreeWidgetItem] = {}
        self.tree.clear()
        self._items_by_value.clear()

        values = self._tags if self._selected_kind == "tag" else self._decks
        for full_value in values:
            parent: QTreeWidgetItem | None = None
            parts: list[str] = []
            for segment in full_value.split("::"):
                parts.append(segment)
                path = "::".join(parts)
                if path not in nodes:
                    item = QTreeWidgetItem([segment])
                    item.setData(0, Qt.ItemDataRole.UserRole, None)
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    nodes[path] = item
                item = nodes[path]
                parent = item
                if path == full_value:
                    item.setData(0, Qt.ItemDataRole.UserRole, full_value)
                    item.setToolTip(0, full_value)
                    self._items_by_value[full_value] = item

        self.tree.collapseAll()

    def _restore_selection(self, full_value: str) -> None:
        item = self._items_by_value.get(full_value.strip())
        if not item:
            return
        self.tree.setCurrentItem(item)
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.scrollToItem(item)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(index), needle)
        if not needle:
            self.tree.collapseAll()
            self._restore_selection(self._selected_values[self._selected_kind])

    def _filter_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        tag_value = str(item.data(0, Qt.ItemDataRole.UserRole) or "").lower()
        self_match = not needle or needle in item.text(0).lower() or (tag_value and needle in tag_value)
        child_match = False
        for child_index in range(item.childCount()):
            child = item.child(child_index)
            child_match = self._filter_item(child, needle) or child_match
        visible = self_match or child_match
        item.setHidden(not visible)
        if visible and child_match and needle:
            item.setExpanded(True)
        return visible

    def _sync_selected_tag(self) -> None:
        item = self.tree.currentItem()
        if item:
            value = item.data(0, Qt.ItemDataRole.UserRole)
            self._selected_values[self._selected_kind] = str(value or "").strip()

    def _accept_item(self, item: QTreeWidgetItem) -> None:
        value = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if value:
            self._selected_values[self._selected_kind] = value
            self.accept()

    def _on_kind_changed(self, _index: int) -> None:
        self._sync_selected_tag()
        if self.kind_combo is not None:
            self._selected_kind = str(self.kind_combo.currentData() or "tag")
        self.search_edit.clear()
        self._build_tree()
        self._restore_selection(self._selected_values[self._selected_kind])
        self._sync_labels()

    def _sync_labels(self) -> None:
        label = "tag" if self._selected_kind == "tag" else "deck"
        self.setWindowTitle("Choose Source" if self._allow_kind_switch else f"Choose {label.title()}")
        self.intro.setText(
            f"Search or browse nested {label}s. Double-click a {label} to use its full path."
        )
        self.search_edit.setPlaceholderText(f"Search {label}s...")
        self.use_button.setText(f"Use Selected {label.title()}")


class TagPickerDialog(SourcePickerDialog):
    def __init__(self, tags: list[str], current_tag: str = "", parent: QWidget | None = None) -> None:
        super().__init__(
            tags,
            [],
            current_kind="tag",
            current_value=current_tag,
            allow_kind_switch=False,
            parent=parent,
        )


class DeckPickerDialog(SourcePickerDialog):
    def __init__(self, decks: list[str], current_deck: str = "", parent: QWidget | None = None) -> None:
        super().__init__(
            [],
            decks,
            current_kind="deck",
            current_value=current_deck,
            allow_kind_switch=False,
            parent=parent,
        )


class JsonEditorDialog(QDialog):
    def __init__(self, current_config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent or mw)
        self.result_payload: dict[str, Any] | None = None
        self.result_warnings: tuple[str, ...] = tuple()

        self.setWindowTitle("Edit Activity Rings JSON")
        self.resize(940, 720)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Advanced mode. Invalid or missing fields will be repaired where possible before saving.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(json.dumps(current_config, indent=2, sort_keys=True))
        layout.addWidget(self.editor, 1)

        self.warning_label = QLabel("", self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b45309;")
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)
        button_row.addStretch(1)
        self.validate_button = QPushButton("Validate", self)
        self.load_button = QPushButton("Load Into Visual Editor", self)
        self.cancel_button = QPushButton("Cancel", self)
        button_row.addWidget(self.validate_button)
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.cancel_button)

        qconnect(self.validate_button.clicked, self._validate)
        qconnect(self.load_button.clicked, self._load)
        qconnect(self.cancel_button.clicked, self.reject)

    def _validate(self) -> None:
        result = load_config_from_json_string(self.editor.toPlainText())
        warnings = list(result.warnings)
        if warnings:
            self.warning_label.setText("\n".join(warnings))
            self.warning_label.show()
        else:
            self.warning_label.setText("No validation warnings.")
            self.warning_label.setStyleSheet("color: #15803d;")
            self.warning_label.show()

    def _load(self) -> None:
        result = load_config_from_json_string(self.editor.toPlainText())
        self.result_payload = addon_config_to_dict(result.config)
        self.result_warnings = result.warnings
        self.accept()


class RingRowWidget(QFrame):
    def __init__(
        self,
        ring_payload: dict[str, Any],
        *,
        ring_index: int,
        on_changed: Callable[[bool], None],
        on_move_up: Callable[[], None],
        on_move_down: Callable[[], None],
        on_duplicate: Callable[[], None],
        on_remove: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ring_payload = ring_payload
        self._on_changed = on_changed
        self._loading = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid rgba(127,127,127,0.18); border-radius: 12px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        top_row = QGridLayout()
        top_row.setHorizontalSpacing(10)
        top_row.setVerticalSpacing(8)
        outer.addLayout(top_row)

        self.order_label = QLabel(f"Ring {ring_index + 1}", self)
        self.order_label.setStyleSheet("font-weight: 600;")
        top_row.addWidget(self.order_label, 0, 0)

        self.enabled_box = QCheckBox("Enabled", self)
        top_row.addWidget(self.enabled_box, 0, 1)

        self.label_edit = QLineEdit(self)
        self.label_edit.setPlaceholderText("Ring label")
        top_row.addWidget(self.label_edit, 0, 2)

        self.color_field = ColorField(allow_auto=True, placeholder="auto or #RRGGBB", parent=self)
        top_row.addWidget(self.color_field, 0, 3)

        self.track_color_field = ColorField(allow_auto=True, placeholder="auto or #RRGGBB", parent=self)
        top_row.addWidget(self.track_color_field, 0, 4)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.up_button = QPushButton("Up", self)
        self.down_button = QPushButton("Down", self)
        self.duplicate_button = QPushButton("Duplicate", self)
        self.remove_button = QPushButton("Remove", self)
        for button in (self.up_button, self.down_button, self.duplicate_button, self.remove_button):
            button.setAutoDefault(False)
            action_row.addWidget(button)
        top_row.addLayout(action_row, 0, 5)

        metric_form = QFormLayout()
        metric_form.setContentsMargins(0, 0, 0, 0)
        metric_form.setHorizontalSpacing(12)
        metric_form.setVerticalSpacing(8)
        outer.addLayout(metric_form)

        self.metric_editor = QueryFieldEditor(parent=self)
        metric_form.addRow("Metric", self.metric_editor)

        self.denominator_editor = QueryFieldEditor(parent=self)
        metric_form.addRow("Denominator", self.denominator_editor)

        self.color_field.connect_changed(lambda: self._store_color("color", refresh_data=False))
        self.track_color_field.connect_changed(lambda: self._store_color("track_color", refresh_data=False))
        self.enabled_box.toggled.connect(self._store_enabled)
        self.label_edit.textChanged.connect(self._store_label)
        self.metric_editor.connect_changed(lambda: self._store_query("metric", self.metric_editor))
        self.denominator_editor.connect_changed(
            lambda: self._store_query("denominator", self.denominator_editor)
        )
        qconnect(self.up_button.clicked, on_move_up)
        qconnect(self.down_button.clicked, on_move_down)
        qconnect(self.duplicate_button.clicked, on_duplicate)
        qconnect(self.remove_button.clicked, on_remove)

        self._load()

    def _load(self) -> None:
        self._loading = True
        self.enabled_box.setChecked(bool(self.ring_payload.get("enabled", True)))
        self.label_edit.setText(str(self.ring_payload.get("label", "")).strip())
        self.color_field.set_text(str(self.ring_payload.get("color", "auto")).strip())
        self.track_color_field.set_text(str(self.ring_payload.get("track_color", "auto")).strip())
        self.metric_editor.set_query_payload(
            deepcopy(self.ring_payload.get("metric", default_query_payload(builtin_name="mature")))
        )
        self.denominator_editor.set_query_payload(
            deepcopy(self.ring_payload.get("denominator", default_query_payload(builtin_name="unsuspended")))
        )
        self._loading = False

    def _store_enabled(self, checked: bool) -> None:
        if self._loading:
            return
        self.ring_payload["enabled"] = bool(checked)
        self._on_changed(True)

    def _store_label(self, text: str) -> None:
        if self._loading:
            return
        self.ring_payload["label"] = text.strip()
        self._on_changed(False)

    def _store_color(self, key: str, *, refresh_data: bool) -> None:
        if self._loading:
            return
        value = self.color_field.text() if key == "color" else self.track_color_field.text()
        self.ring_payload[key] = value or "auto"
        self._on_changed(refresh_data)

    def _store_query(self, key: str, editor: QueryFieldEditor) -> None:
        if self._loading:
            return
        self.ring_payload[key] = editor.payload()
        self._on_changed(True)


class RingListEditor(QWidget):
    def __init__(self, on_changed: Callable[[bool], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._change_callback = on_changed
        self._widget_payload: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        layout.addLayout(header)
        header.addWidget(QLabel("Ring Metrics", self))
        header.addStretch(1)
        self.add_button = QPushButton("Add Ring", self)
        self.add_button.setAutoDefault(False)
        header.addWidget(self.add_button)

        self.rows_container = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)
        layout.addWidget(self.rows_container)

        qconnect(self.add_button.clicked, self._add_ring)

    def set_widget_payload(self, widget_payload: dict[str, Any] | None) -> None:
        self._widget_payload = widget_payload
        self._rebuild()

    def _rings(self) -> list[dict[str, Any]]:
        if self._widget_payload is None:
            return []
        rings = self._widget_payload.setdefault("rings", [])
        if not isinstance(rings, list):
            rings = []
            self._widget_payload["rings"] = rings
        return rings

    def _rebuild(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        rings = self._rings()
        if not self._widget_payload:
            placeholder = QLabel("Select a widget to edit its rings.", self.rows_container)
            placeholder.setWordWrap(True)
            self.rows_layout.addWidget(placeholder)
            self.add_button.setEnabled(False)
            return

        self.add_button.setEnabled(True)
        if not rings:
            placeholder = QLabel("No rings configured yet. Add one to begin.", self.rows_container)
            placeholder.setWordWrap(True)
            self.rows_layout.addWidget(placeholder)
        else:
            for index, ring_payload in enumerate(rings):
                row = RingRowWidget(
                    ring_payload,
                    ring_index=index,
                    on_changed=self._on_changed,
                    on_move_up=lambda idx=index: self._move_ring(idx, -1),
                    on_move_down=lambda idx=index: self._move_ring(idx, 1),
                    on_duplicate=lambda idx=index: self._duplicate_ring(idx),
                    on_remove=lambda idx=index: self._remove_ring(idx),
                    parent=self.rows_container,
                )
                self.rows_layout.addWidget(row)
        self.rows_layout.addStretch(1)

    def _on_changed(self, refresh_data: bool) -> None:
        self._change_callback(refresh_data)

    def _add_ring(self) -> None:
        rings = self._rings()
        widget_payload = self._widget_payload or {}
        rings.append(_default_ring_payload_for_widget(widget_payload, len(rings)))
        self._rebuild()
        self._change_callback(True)

    def _duplicate_ring(self, index: int) -> None:
        rings = self._rings()
        if not (0 <= index < len(rings)):
            return
        clone = deepcopy(rings[index])
        label = str(clone.get("label", "")).strip() or "Ring"
        clone["label"] = f"{label} Copy"
        clone["id"] = _slugify(clone["label"], f"ring-{len(rings) + 1}")
        rings.insert(index + 1, clone)
        self._rebuild()
        self._change_callback(True)

    def _remove_ring(self, index: int) -> None:
        rings = self._rings()
        if not (0 <= index < len(rings)):
            return
        rings.pop(index)
        self._rebuild()
        self._change_callback(True)

    def _move_ring(self, index: int, delta: int) -> None:
        rings = self._rings()
        target = index + delta
        if not (0 <= index < len(rings) and 0 <= target < len(rings)):
            return
        rings[index], rings[target] = rings[target], rings[index]
        self._rebuild()
        self._change_callback(True)


class ActivityRingsSettingsDialog(QDialog):
    def __init__(self) -> None:
        super().__init__(mw)
        result = load_config()
        self._config_data = addon_config_to_dict(result.config)
        self._saved_config_data = deepcopy(self._config_data)
        self._warnings = list(result.warnings)
        self._dirty = False
        self._loading_form = False
        self._preview_snapshot: WidgetSnapshot | None = None
        self._preview_loading = False
        self._preview_request_serial = 0
        self._tag_names = self._collection_tags()
        self._deck_names = self._collection_decks()

        self.setWindowTitle(ADDON_NAME)
        self.resize(1480, 930)
        self.setModal(True)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(280)
        self._preview_timer.timeout.connect(self._start_preview_query)

        self._setup_ui()
        self._refresh_warning_banner()
        self._populate_widget_list()
        self._restore_initial_selection()
        restoreGeom(self, GEOMETRY_KEY)
        self._render_preview()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self._confirm_discard_if_needed():
            event.ignore()
            return
        saveGeom(self, GEOMETRY_KEY)
        super().closeEvent(event)

    def reject(self) -> None:  # type: ignore[override]
        if not self._confirm_discard_if_needed():
            return
        saveGeom(self, GEOMETRY_KEY)
        super().reject()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            "QGroupBox { font-weight: 600; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 2px; padding: 0 4px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        self.warning_banner = QLabel("", self)
        self.warning_banner.setWordWrap(True)
        self.warning_banner.setStyleSheet(
            "background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.28);"
            "border-radius: 10px; padding: 10px 12px;"
        )
        self.warning_banner.hide()
        root.addWidget(self.warning_banner)

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(main_splitter, 1)

        sidebar = QWidget(main_splitter)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)

        sidebar_title = QLabel("Widgets", sidebar)
        sidebar_title.setStyleSheet("font-weight: 700; font-size: 14px;")
        sidebar_layout.addWidget(sidebar_title)

        self.widget_list = QListWidget(sidebar)
        self.widget_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        sidebar_layout.addWidget(self.widget_list, 1)

        widget_buttons = QGridLayout()
        widget_buttons.setHorizontalSpacing(8)
        widget_buttons.setVerticalSpacing(8)
        sidebar_layout.addLayout(widget_buttons)

        self.add_widget_button = QPushButton("Add", sidebar)
        self.duplicate_widget_button = QPushButton("Duplicate", sidebar)
        self.remove_widget_button = QPushButton("Remove", sidebar)
        self.move_widget_up_button = QPushButton("Move Up", sidebar)
        self.move_widget_down_button = QPushButton("Move Down", sidebar)
        self.reset_widget_button = QPushButton("Reset Widget", sidebar)

        widget_buttons.addWidget(self.add_widget_button, 0, 0)
        widget_buttons.addWidget(self.duplicate_widget_button, 0, 1)
        widget_buttons.addWidget(self.remove_widget_button, 1, 0)
        widget_buttons.addWidget(self.move_widget_up_button, 1, 1)
        widget_buttons.addWidget(self.move_widget_down_button, 2, 0)
        widget_buttons.addWidget(self.reset_widget_button, 2, 1)

        content_splitter = QSplitter(Qt.Orientation.Horizontal, main_splitter)

        editor_container = QWidget(content_splitter)
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self.editor_scroll = QScrollArea(editor_container)
        self.editor_scroll.setWidgetResizable(True)
        editor_layout.addWidget(self.editor_scroll, 1)

        self.editor_content = QWidget(self.editor_scroll)
        self.editor_scroll.setWidget(self.editor_content)

        self.editor_stack = QVBoxLayout(self.editor_content)
        self.editor_stack.setContentsMargins(0, 0, 8, 0)
        self.editor_stack.setSpacing(14)

        self.basics_group = QGroupBox("Widget Basics", self.editor_content)
        self.editor_stack.addWidget(self.basics_group)
        self._build_basics_group()

        self.rings_group = QGroupBox("Rings", self.editor_content)
        self.editor_stack.addWidget(self.rings_group)
        rings_layout = QVBoxLayout(self.rings_group)
        rings_layout.setContentsMargins(12, 12, 12, 12)
        rings_layout.setSpacing(10)
        self.ring_list_editor = RingListEditor(self._on_ring_list_changed, self.rings_group)
        rings_layout.addWidget(self.ring_list_editor)

        advanced_content = QWidget(self.editor_content)
        self._build_advanced_group(advanced_content)
        self.editor_stack.addWidget(
            CollapsibleSection("Advanced Appearance", advanced_content, expanded=False, parent=self.editor_content)
        )

        global_content = QWidget(self.editor_content)
        self._build_global_group(global_content)
        self.editor_stack.addWidget(
            CollapsibleSection("Dashboard Defaults", global_content, expanded=False, parent=self.editor_content)
        )

        help_group = QGroupBox("Metric Help", self.editor_content)
        help_layout = QVBoxLayout(help_group)
        help_layout.setContentsMargins(12, 12, 12, 12)
        help_layout.setSpacing(8)
        help_text = QLabel(
            "Mature means review cards with interval >= 21 days. "
            "Young/Learning includes learning cards plus review cards under 21 days. "
            "Unsuspended means cards that are not suspended. "
            "A ring percentage is always numerator / denominator for the current widget source.",
            help_group,
        )
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        self.editor_stack.addWidget(help_group)
        self.editor_stack.addStretch(1)

        preview_container = QWidget(content_splitter)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)

        preview_title = QLabel("Live Preview", preview_container)
        preview_title.setStyleSheet("font-weight: 700; font-size: 14px;")
        preview_layout.addWidget(preview_title)

        self.preview_status_label = QLabel(
            "Preview updates as you edit titles, source, ring semantics, and appearance.",
            preview_container,
        )
        self.preview_status_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_status_label)

        self.preview_web = AnkiWebView(parent=preview_container)
        self.preview_web.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview_web, 1)

        main_splitter.addWidget(sidebar)
        main_splitter.addWidget(content_splitter)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([270, 1120])
        content_splitter.setSizes([700, 420])

        footer = QHBoxLayout()
        root.addLayout(footer)

        self.edit_json_button = QPushButton("Edit JSON...", self)
        self.restore_defaults_button = QPushButton("Restore Defaults", self)
        footer.addWidget(self.edit_json_button)
        footer.addWidget(self.restore_defaults_button)
        footer.addStretch(1)

        self.apply_button = QPushButton("Apply", self)
        self.save_button = QPushButton("Save", self)
        self.save_close_button = QPushButton("Save and Close", self)
        self.cancel_button = QPushButton("Cancel", self)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.save_button)
        footer.addWidget(self.save_close_button)
        footer.addWidget(self.cancel_button)

        self.widget_list.currentRowChanged.connect(self._on_widget_selection_changed)
        qconnect(self.add_widget_button.clicked, self._add_widget)
        qconnect(self.duplicate_widget_button.clicked, self._duplicate_widget)
        qconnect(self.remove_widget_button.clicked, self._remove_widget)
        qconnect(self.move_widget_up_button.clicked, lambda: self._move_widget(-1))
        qconnect(self.move_widget_down_button.clicked, lambda: self._move_widget(1))
        qconnect(self.reset_widget_button.clicked, self._reset_widget)
        qconnect(self.edit_json_button.clicked, self._open_json_editor)
        qconnect(self.restore_defaults_button.clicked, self._restore_defaults)
        qconnect(self.apply_button.clicked, self._apply_changes)
        qconnect(self.save_button.clicked, self._save_changes)
        qconnect(self.save_close_button.clicked, self._save_and_close)
        qconnect(self.cancel_button.clicked, self.reject)

    def _build_basics_group(self) -> None:
        layout = QGridLayout(self.basics_group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.title_edit = QLineEdit(self.basics_group)
        self.title_edit.setPlaceholderText("Widget title")
        layout.addWidget(QLabel("Title", self.basics_group), 0, 0)
        layout.addWidget(self.title_edit, 0, 1, 1, 3)

        self.layout_mode_combo = QComboBox(self.basics_group)
        self.layout_mode_combo.addItem("Compact ring-first", "compact")
        self.layout_mode_combo.addItem("Wide detailed", "wide")
        layout.addWidget(QLabel("Layout", self.basics_group), 1, 0)
        layout.addWidget(self.layout_mode_combo, 1, 1)

        self.title_position_combo = QComboBox(self.basics_group)
        self.title_position_combo.addItem("Above card", "above")
        self.title_position_combo.addItem("Inside card", "inside")
        self.title_position_combo.addItem("Center of ring", "center")
        self.title_position_combo.addItem("Hidden", "hidden")
        layout.addWidget(QLabel("Title Position", self.basics_group), 1, 2)
        layout.addWidget(self.title_position_combo, 1, 3)

        self.source_mode_combo = QComboBox(self.basics_group)
        self.source_mode_combo.addItem("Tag", "tag")
        self.source_mode_combo.addItem("Deck", "deck")
        self.source_mode_combo.addItem("Search", "search")
        self.source_mode_combo.addItem("Today's Progress", "today")
        layout.addWidget(QLabel("Source Type", self.basics_group), 2, 0)
        layout.addWidget(self.source_mode_combo, 2, 1)

        self.center_label_combo = QComboBox(self.basics_group)
        self.center_label_combo.addItem("Primary percent", "primary_percent")
        self.center_label_combo.addItem("Primary count", "primary_metric")
        self.center_label_combo.addItem("Card count", "card_count")
        self.center_label_combo.addItem("Title", "title")
        self.center_label_combo.addItem("Hidden", "none")
        layout.addWidget(QLabel("Center Label", self.basics_group), 2, 2)
        layout.addWidget(self.center_label_combo, 2, 3)

        self.primary_ring_combo = QComboBox(self.basics_group)
        layout.addWidget(QLabel("Center Metric", self.basics_group), 3, 0)
        layout.addWidget(self.primary_ring_combo, 3, 1)

        self.center_text_edit = QLineEdit(self.basics_group)
        self.center_text_edit.setPlaceholderText("Optional center caption override")
        layout.addWidget(QLabel("Center Text", self.basics_group), 3, 2)
        layout.addWidget(self.center_text_edit, 3, 3)

        self.tag_row = QWidget(self.basics_group)
        tag_row_layout = QHBoxLayout(self.tag_row)
        tag_row_layout.setContentsMargins(0, 0, 0, 0)
        tag_row_layout.setSpacing(8)
        self.tag_edit = QLineEdit(self.tag_row)
        self.tag_edit.setPlaceholderText("Choose or type a tag")
        completer = QCompleter(self._tag_names, self.tag_row)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.tag_edit.setCompleter(completer)
        self.tag_browse_button = QPushButton("Browse...", self.tag_row)
        self.include_children_box = QCheckBox("Include child tags", self.tag_row)
        tag_row_layout.addWidget(self.tag_edit, 1)
        tag_row_layout.addWidget(self.tag_browse_button)
        tag_row_layout.addWidget(self.include_children_box)

        self.search_row = QWidget(self.basics_group)
        search_row_layout = QHBoxLayout(self.search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(8)
        self.search_edit = QLineEdit(self.search_row)
        self.search_edit.setPlaceholderText("Anki search, e.g. deck:Step1 is:due")
        search_row_layout.addWidget(self.search_edit, 1)

        self.deck_row = QWidget(self.basics_group)
        deck_row_layout = QHBoxLayout(self.deck_row)
        deck_row_layout.setContentsMargins(0, 0, 0, 0)
        deck_row_layout.setSpacing(8)
        self.deck_edit = QLineEdit(self.deck_row)
        self.deck_edit.setPlaceholderText("Choose or type a deck")
        source_deck_completer = QCompleter(self._deck_names, self.deck_row)
        source_deck_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        source_deck_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.deck_edit.setCompleter(source_deck_completer)
        self.deck_browse_button = QPushButton("Browse...", self.deck_row)
        deck_row_layout.addWidget(self.deck_edit, 1)
        deck_row_layout.addWidget(self.deck_browse_button)

        self.today_row = QWidget(self.basics_group)
        today_row_layout = QHBoxLayout(self.today_row)
        today_row_layout.setContentsMargins(0, 0, 0, 0)
        today_row_layout.setSpacing(8)
        self.today_scope_combo = QComboBox(self.today_row)
        self.today_scope_combo.addItem("All decks", "all")
        self.today_scope_combo.addItem("Specific deck", "deck")
        self.today_deck_edit = QLineEdit(self.today_row)
        self.today_deck_edit.setPlaceholderText("Choose or type a deck name")
        deck_completer = QCompleter(self._deck_names, self.today_row)
        deck_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        deck_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.today_deck_edit.setCompleter(deck_completer)
        today_row_layout.addWidget(self.today_scope_combo)
        today_row_layout.addWidget(self.today_deck_edit, 1)

        self.source_stack_container = QWidget(self.basics_group)
        source_stack_layout = QVBoxLayout(self.source_stack_container)
        source_stack_layout.setContentsMargins(0, 0, 0, 0)
        source_stack_layout.setSpacing(0)
        source_stack_layout.addWidget(self.tag_row)
        source_stack_layout.addWidget(self.deck_row)
        source_stack_layout.addWidget(self.search_row)
        source_stack_layout.addWidget(self.today_row)
        layout.addWidget(QLabel("Source", self.basics_group), 4, 0)
        layout.addWidget(self.source_stack_container, 4, 1, 1, 3)

        self.show_source_subtitle_box = QCheckBox("Show source subtitle", self.basics_group)
        self.show_total_cards_box = QCheckBox("Show total card count", self.basics_group)
        self.show_counts_box = QCheckBox("Show counts", self.basics_group)
        self.show_percentages_box = QCheckBox("Show percentages", self.basics_group)
        self.show_legend_box = QCheckBox("Show legend rows", self.basics_group)

        toggles_row = QWidget(self.basics_group)
        toggles_layout = QHBoxLayout(toggles_row)
        toggles_layout.setContentsMargins(0, 0, 0, 0)
        toggles_layout.setSpacing(12)
        for checkbox in (
            self.show_source_subtitle_box,
            self.show_total_cards_box,
            self.show_counts_box,
            self.show_percentages_box,
            self.show_legend_box,
        ):
            toggles_layout.addWidget(checkbox)
        toggles_layout.addStretch(1)
        layout.addWidget(toggles_row, 5, 0, 1, 4)

        self.click_action_combo = QComboBox(self.basics_group)
        self.click_action_combo.addItem("Do nothing", "none")
        self.click_action_combo.addItem("Open source cards", "source")
        self.click_action_combo.addItem("Open primary metric", "numerator")
        layout.addWidget(QLabel("Card Click", self.basics_group), 6, 0)
        layout.addWidget(self.click_action_combo, 6, 1)

        self.ring_click_action_combo = QComboBox(self.basics_group)
        self.ring_click_action_combo.addItem("Do nothing", "none")
        self.ring_click_action_combo.addItem("Open source cards", "source")
        self.ring_click_action_combo.addItem("Open ring metric cards", "numerator")
        layout.addWidget(QLabel("Ring Click", self.basics_group), 6, 2)
        layout.addWidget(self.ring_click_action_combo, 6, 3)

        self.source_status_label = QLabel("", self.basics_group)
        self.source_status_label.setWordWrap(True)
        layout.addWidget(self.source_status_label, 7, 0, 1, 4)

        self.title_edit.textChanged.connect(
            lambda text: self._update_current_widget(
                "title",
                text,
                refresh_data=False,
                refresh_list=True,
            )
        )
        self.layout_mode_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "mode",
                self.layout_mode_combo.currentData(),
                refresh_data=False,
            )
        )
        self.title_position_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "title_position",
                self.title_position_combo.currentData(),
                refresh_data=False,
            )
        )
        self.center_label_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "center_label_mode",
                self.center_label_combo.currentData(),
                refresh_data=False,
            )
        )
        self.primary_ring_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "primary_ring_id",
                self.primary_ring_combo.currentData() or "",
                refresh_data=False,
            )
        )
        self.center_text_edit.textChanged.connect(
            lambda text: self._update_layout_field(
                "center_label_text",
                text,
                refresh_data=False,
            )
        )
        self.source_mode_combo.currentIndexChanged.connect(self._on_source_mode_changed)
        self.tag_edit.textChanged.connect(self._on_tag_changed)
        self.deck_edit.textChanged.connect(self._on_deck_source_changed)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.today_scope_combo.currentIndexChanged.connect(self._on_today_scope_changed)
        self.today_deck_edit.textChanged.connect(self._on_today_deck_changed)
        self.include_children_box.toggled.connect(
            lambda checked: self._update_source_field("include_children", bool(checked), refresh_data=True)
        )
        self.show_source_subtitle_box.toggled.connect(
            lambda checked: self._update_layout_field("show_source_subtitle", bool(checked), refresh_data=False, refresh_list=True)
        )
        self.show_total_cards_box.toggled.connect(
            lambda checked: self._update_layout_field("show_total_cards", bool(checked), refresh_data=False)
        )
        self.show_counts_box.toggled.connect(
            lambda checked: self._update_layout_field("show_counts", bool(checked), refresh_data=False)
        )
        self.show_percentages_box.toggled.connect(
            lambda checked: self._update_layout_field("show_percentages", bool(checked), refresh_data=False)
        )
        self.show_legend_box.toggled.connect(
            lambda checked: self._update_layout_field("show_legend", bool(checked), refresh_data=False)
        )
        self.click_action_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "click_action",
                self.click_action_combo.currentData(),
                refresh_data=False,
            )
        )
        self.ring_click_action_combo.currentIndexChanged.connect(
            lambda _index: self._update_layout_field(
                "ring_click_action",
                self.ring_click_action_combo.currentData(),
                refresh_data=False,
            )
        )
        qconnect(self.tag_browse_button.clicked, self._browse_tag)
        qconnect(self.deck_browse_button.clicked, self._browse_deck)

    def _build_advanced_group(self, container: QWidget) -> None:
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.ring_size_spin = QSpinBox(container)
        self.ring_size_spin.setRange(120, 320)
        self.ring_thickness_spin = QSpinBox(container)
        self.ring_thickness_spin.setRange(4, 80)
        self.ring_gap_spin = QSpinBox(container)
        self.ring_gap_spin.setRange(0, 20)
        self.card_padding_spin = QSpinBox(container)
        self.card_padding_spin.setRange(8, 36)
        self.card_min_width_spin = QSpinBox(container)
        self.card_min_width_spin.setRange(220, 600)
        self.card_max_width_spin = QSpinBox(container)
        self.card_max_width_spin.setRange(260, 720)
        self.card_aspect_ratio_spin = QDoubleSpinBox(container)
        self.card_aspect_ratio_spin.setRange(0.75, 2.5)
        self.card_aspect_ratio_spin.setSingleStep(0.05)
        self.card_aspect_ratio_spin.setDecimals(2)
        self.center_value_size_spin = QSpinBox(container)
        self.center_value_size_spin.setRange(14, 48)
        self.center_caption_size_spin = QSpinBox(container)
        self.center_caption_size_spin.setRange(8, 24)

        self.background_color_field = ColorField(allow_auto=True, placeholder="auto or #RRGGBB", parent=container)
        self.border_color_field = ColorField(allow_auto=True, placeholder="auto or #RRGGBB", parent=container)
        self.global_track_color_field = ColorField(allow_auto=True, placeholder="auto or #RRGGBB", parent=container)
        self.card_opacity_spin = QDoubleSpinBox(container)
        self.card_opacity_spin.setRange(0.0, 1.0)
        self.card_opacity_spin.setSingleStep(0.05)
        self.card_opacity_spin.setDecimals(2)
        self.center_value_auto_fit_box = QCheckBox("Auto-fit center percent text", container)
        self.center_caption_auto_fit_box = QCheckBox("Auto-fit center text", container)
        self.shadow_enabled_box = QCheckBox("Shadow", container)
        self.glow_enabled_box = QCheckBox("Glow", container)

        layout.addWidget(QLabel("Ring Size", container), 0, 0)
        layout.addWidget(self.ring_size_spin, 0, 1)
        layout.addWidget(QLabel("Ring Thickness", container), 0, 2)
        layout.addWidget(self.ring_thickness_spin, 0, 3)

        layout.addWidget(QLabel("Ring Gap", container), 1, 0)
        layout.addWidget(self.ring_gap_spin, 1, 1)
        layout.addWidget(QLabel("Card Padding", container), 1, 2)
        layout.addWidget(self.card_padding_spin, 1, 3)

        layout.addWidget(QLabel("Card Min Width", container), 2, 0)
        layout.addWidget(self.card_min_width_spin, 2, 1)
        layout.addWidget(QLabel("Card Max Width", container), 2, 2)
        layout.addWidget(self.card_max_width_spin, 2, 3)

        layout.addWidget(QLabel("Aspect Ratio", container), 3, 0)
        layout.addWidget(self.card_aspect_ratio_spin, 3, 1)
        layout.addWidget(QLabel("Center Percent Text Size", container), 3, 2)
        layout.addWidget(self.center_value_size_spin, 3, 3)

        layout.addWidget(QLabel("Center Text Size", container), 4, 0)
        layout.addWidget(self.center_caption_size_spin, 4, 1)
        layout.addWidget(QLabel("Card Opacity", container), 4, 2)
        layout.addWidget(self.card_opacity_spin, 4, 3)

        center_fit_row = QWidget(container)
        center_fit_layout = QHBoxLayout(center_fit_row)
        center_fit_layout.setContentsMargins(0, 0, 0, 0)
        center_fit_layout.setSpacing(12)
        center_fit_layout.addWidget(self.center_value_auto_fit_box)
        center_fit_layout.addWidget(self.center_caption_auto_fit_box)
        center_fit_layout.addStretch(1)
        layout.addWidget(center_fit_row, 5, 0, 1, 4)

        layout.addWidget(QLabel("Card Background", container), 6, 0)
        layout.addWidget(self.background_color_field, 6, 1)
        layout.addWidget(QLabel("Border Color", container), 6, 2)
        layout.addWidget(self.border_color_field, 6, 3)

        layout.addWidget(QLabel("Track Color", container), 7, 0)
        layout.addWidget(self.global_track_color_field, 7, 1)
        toggles = QWidget(container)
        toggles_layout = QHBoxLayout(toggles)
        toggles_layout.setContentsMargins(0, 0, 0, 0)
        toggles_layout.setSpacing(12)
        toggles_layout.addWidget(self.shadow_enabled_box)
        toggles_layout.addWidget(self.glow_enabled_box)
        toggles_layout.addStretch(1)
        layout.addWidget(toggles, 7, 2, 1, 2)

        self.ring_size_spin.valueChanged.connect(lambda value: self._update_layout_field("ring_size", int(value), refresh_data=False))
        self.ring_thickness_spin.valueChanged.connect(lambda value: self._update_layout_field("ring_thickness", int(value), refresh_data=False))
        self.ring_gap_spin.valueChanged.connect(lambda value: self._update_layout_field("ring_gap", int(value), refresh_data=False))
        self.card_padding_spin.valueChanged.connect(lambda value: self._update_layout_field("card_padding", int(value), refresh_data=False))
        self.card_min_width_spin.valueChanged.connect(lambda value: self._update_layout_field("card_min_width", int(value), refresh_data=False))
        self.card_max_width_spin.valueChanged.connect(lambda value: self._update_layout_field("card_max_width", int(value), refresh_data=False))
        self.card_aspect_ratio_spin.valueChanged.connect(lambda value: self._update_layout_field("card_aspect_ratio", float(value), refresh_data=False))
        self.center_value_size_spin.valueChanged.connect(
            lambda value: self._update_layout_field("center_value_font_size", int(value), refresh_data=False)
        )
        self.center_caption_size_spin.valueChanged.connect(
            lambda value: self._update_layout_field("center_caption_font_size", int(value), refresh_data=False)
        )
        self.card_opacity_spin.valueChanged.connect(lambda value: self._update_style_field("card_opacity", float(value), refresh_data=False))
        self.center_value_auto_fit_box.toggled.connect(
            lambda checked: self._on_center_auto_fit_toggled("center_value_auto_fit", bool(checked))
        )
        self.center_caption_auto_fit_box.toggled.connect(
            lambda checked: self._on_center_auto_fit_toggled("center_caption_auto_fit", bool(checked))
        )
        self.shadow_enabled_box.toggled.connect(lambda checked: self._update_style_field("shadow_enabled", bool(checked), refresh_data=False))
        self.glow_enabled_box.toggled.connect(lambda checked: self._update_style_field("use_glow", bool(checked), refresh_data=False))
        self.background_color_field.connect_changed(lambda: self._update_style_field("background_color", self.background_color_field.text() or "auto", refresh_data=False))
        self.border_color_field.connect_changed(lambda: self._update_style_field("border_color", self.border_color_field.text() or "auto", refresh_data=False))
        self.global_track_color_field.connect_changed(lambda: self._update_style_field("track_color", self.global_track_color_field.text() or "auto", refresh_data=False))

    def _build_global_group(self, container: QWidget) -> None:
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.show_deck_browser_box = QCheckBox("Deck Browser", container)
        self.show_overview_box = QCheckBox("Overview", container)
        screens_row = QWidget(container)
        screens_layout = QHBoxLayout(screens_row)
        screens_layout.setContentsMargins(0, 0, 0, 0)
        screens_layout.setSpacing(12)
        screens_layout.addWidget(self.show_deck_browser_box)
        screens_layout.addWidget(self.show_overview_box)
        screens_layout.addStretch(1)
        layout.addWidget(QLabel("Show On", container), 0, 0)
        layout.addWidget(screens_row, 0, 1, 1, 3)

        self.theme_combo = QComboBox(container)
        self.theme_combo.addItem("Auto", "auto")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        layout.addWidget(QLabel("Theme", container), 1, 0)
        layout.addWidget(self.theme_combo, 1, 1)

        self.palette_combo = QComboBox(container)
        self.palette_combo.addItem("Soft", "soft")
        self.palette_combo.addItem("Vibrant", "vibrant")
        self.palette_combo.addItem("Colorblind Friendly", "colorblind")
        layout.addWidget(QLabel("Palette", container), 1, 2)
        layout.addWidget(self.palette_combo, 1, 3)

        self.dashboard_position_combo = QComboBox(container)
        self.dashboard_position_combo.addItem("Above dashboard content", "top")
        self.dashboard_position_combo.addItem("Below dashboard content", "bottom")
        layout.addWidget(QLabel("Placement", container), 2, 0)
        layout.addWidget(self.dashboard_position_combo, 2, 1)

        self.panel_margin_spin = QSpinBox(container)
        self.panel_margin_spin.setRange(0, 64)
        self.panel_spacing_spin = QSpinBox(container)
        self.panel_spacing_spin.setRange(0, 48)
        layout.addWidget(QLabel("Panel Margin", container), 2, 2)
        layout.addWidget(self.panel_margin_spin, 2, 3)
        layout.addWidget(QLabel("Panel Spacing", container), 3, 0)
        layout.addWidget(self.panel_spacing_spin, 3, 1)

        self.cache_ttl_spin = QSpinBox(container)
        self.cache_ttl_spin.setRange(0, 600)
        self.debug_timing_box = QCheckBox("Enable debug timing logs", container)
        self.match_widget_sizes_box = QCheckBox("Match widget sizes", container)
        layout.addWidget(QLabel("Cache TTL (seconds)", container), 4, 0)
        layout.addWidget(self.cache_ttl_spin, 4, 1)
        layout.addWidget(self.match_widget_sizes_box, 4, 2)
        layout.addWidget(self.debug_timing_box, 4, 3)

        self.show_deck_browser_box.toggled.connect(self._update_show_screens)
        self.show_overview_box.toggled.connect(self._update_show_screens)
        self.theme_combo.currentIndexChanged.connect(
            lambda _index: self._update_global_field("theme", self.theme_combo.currentData())
        )
        self.palette_combo.currentIndexChanged.connect(
            lambda _index: self._update_global_field("palette", self.palette_combo.currentData())
        )
        self.dashboard_position_combo.currentIndexChanged.connect(
            lambda _index: self._update_global_field("dashboard_position", self.dashboard_position_combo.currentData())
        )
        self.panel_margin_spin.valueChanged.connect(lambda value: self._update_global_field("panel_margin", int(value)))
        self.panel_spacing_spin.valueChanged.connect(lambda value: self._update_global_field("panel_spacing", int(value)))
        self.cache_ttl_spin.valueChanged.connect(lambda value: self._update_global_field("cache_ttl_seconds", int(value)))
        self.match_widget_sizes_box.toggled.connect(
            lambda checked: self._update_global_field("match_widget_sizes", bool(checked))
        )
        self.debug_timing_box.toggled.connect(lambda checked: self._update_global_field("debug_timing", bool(checked)))

    def _collection_tags(self) -> list[str]:
        if not getattr(mw, "col", None):
            return []
        tags: list[str] = []
        for tag in mw.col.tags.all():
            name = getattr(tag, "name", tag)
            if isinstance(name, str) and name.strip():
                tags.append(name.strip())
        return sorted(set(tags), key=str.casefold)

    def _collection_decks(self) -> list[str]:
        if not getattr(mw, "col", None):
            return []
        decks: list[str] = []
        for deck_name_id in mw.col.decks.all_names_and_ids():
            name = getattr(deck_name_id, "name", "")
            if isinstance(name, str) and name.strip():
                decks.append(name.strip())
        return sorted(set(decks), key=str.casefold)

    def _restore_initial_selection(self) -> None:
        if self._config_data.get("widgets"):
            self.widget_list.setCurrentRow(0)
        else:
            self._set_editor_enabled(False)

    def _populate_widget_list(self) -> None:
        selected_id = self._current_widget_id()
        self.widget_list.blockSignals(True)
        self.widget_list.clear()
        for widget_payload in self._widgets():
            raw_title = str(widget_payload.get("title", ""))
            title = raw_title if raw_title.strip() else "Untitled Widget"
            summary = _source_summary(widget_payload)
            item = QListWidgetItem(f"{title}\n{summary}")
            item.setToolTip(summary)
            item.setData(Qt.ItemDataRole.UserRole, str(widget_payload.get("id", "")).strip())
            self.widget_list.addItem(item)
        self.widget_list.blockSignals(False)
        self._restore_selection_by_id(selected_id)
        self._update_sidebar_buttons()

    def _restore_selection_by_id(self, widget_id: str | None) -> None:
        if not widget_id:
            if self.widget_list.count():
                self.widget_list.setCurrentRow(0)
            else:
                self._on_widget_selection_changed(-1)
            return
        for index in range(self.widget_list.count()):
            item = self.widget_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == widget_id:
                self.widget_list.setCurrentRow(index)
                return
        if self.widget_list.count():
            self.widget_list.setCurrentRow(min(self.widget_list.count() - 1, 0))
        else:
            self._on_widget_selection_changed(-1)

    def _widgets(self) -> list[dict[str, Any]]:
        widgets = self._config_data.setdefault("widgets", [])
        if not isinstance(widgets, list):
            widgets = []
            self._config_data["widgets"] = widgets
        return widgets

    def _current_widget_index(self) -> int:
        row = self.widget_list.currentRow()
        if 0 <= row < len(self._widgets()):
            return row
        return -1

    def _current_widget(self) -> dict[str, Any] | None:
        index = self._current_widget_index()
        if index < 0:
            return None
        return self._widgets()[index]

    def _current_widget_id(self) -> str | None:
        widget = self._current_widget()
        if not widget:
            return None
        return str(widget.get("id", "")).strip() or None

    def _on_widget_selection_changed(self, _row: int) -> None:
        self._populate_widget_editor()
        self._update_sidebar_buttons()
        self._preview_snapshot = None
        self._schedule_preview_refresh()

    def _populate_widget_editor(self) -> None:
        widget = self._current_widget()
        if not widget:
            self._set_editor_enabled(False)
            self.ring_list_editor.set_widget_payload(None)
            self.source_status_label.setText("Add a widget to begin.")
            self._render_preview()
            return

        self._set_editor_enabled(True)
        self._loading_form = True

        source = widget.setdefault("source", default_source_payload())
        layout = widget.setdefault("layout", deepcopy(default_widget_payload()["layout"]))
        style = widget.setdefault("style", deepcopy(default_widget_payload()["style"]))

        self.title_edit.setText(str(widget.get("title", "")))
        self.layout_mode_combo.setCurrentIndex(max(self.layout_mode_combo.findData(layout.get("mode", "compact")), 0))
        self.title_position_combo.setCurrentIndex(max(self.title_position_combo.findData(layout.get("title_position", "inside")), 0))
        self.center_label_combo.setCurrentIndex(max(self.center_label_combo.findData(layout.get("center_label_mode", "primary_percent")), 0))
        self._refresh_primary_ring_options(widget, str(layout.get("primary_ring_id", "") or ""))
        self.center_text_edit.setText(str(layout.get("center_label_text", "") or ""))
        self.source_mode_combo.setCurrentIndex(max(self.source_mode_combo.findData(source.get("type", "tag")), 0))
        self.tag_edit.setText(str(source.get("tag", "")).strip())
        self.tag_edit.setToolTip(self.tag_edit.text())
        self.deck_edit.setText(str(source.get("deck", "")).strip())
        self.deck_edit.setToolTip(self.deck_edit.text())
        self.search_edit.setText(str(source.get("search", "")).strip())
        self.today_scope_combo.setCurrentIndex(max(self.today_scope_combo.findData(source.get("scope", "all")), 0))
        self.today_deck_edit.setText(str(source.get("deck", "")).strip())
        self.today_deck_edit.setToolTip(self.today_deck_edit.text())
        self.include_children_box.setChecked(bool(source.get("include_children", True)))
        self.show_source_subtitle_box.setChecked(bool(layout.get("show_source_subtitle", False)))
        self.show_total_cards_box.setChecked(bool(layout.get("show_total_cards", True)))
        self.show_counts_box.setChecked(bool(layout.get("show_counts", True)))
        self.show_percentages_box.setChecked(bool(layout.get("show_percentages", True)))
        self.show_legend_box.setChecked(bool(layout.get("show_legend", True)))
        self.click_action_combo.setCurrentIndex(max(self.click_action_combo.findData(layout.get("click_action", "source")), 0))
        self.ring_click_action_combo.setCurrentIndex(max(self.ring_click_action_combo.findData(layout.get("ring_click_action", "numerator")), 0))

        self.ring_size_spin.setValue(int(layout.get("ring_size", 204)))
        self.ring_thickness_spin.setValue(int(layout.get("ring_thickness", 18)))
        self.ring_gap_spin.setValue(int(layout.get("ring_gap", 8)))
        self.card_padding_spin.setValue(int(layout.get("card_padding", 18)))
        self.card_min_width_spin.setValue(int(layout.get("card_min_width", 290)))
        self.card_max_width_spin.setValue(int(layout.get("card_max_width", 390)))
        self.card_aspect_ratio_spin.setValue(float(layout.get("card_aspect_ratio", 1.08)))
        self.center_value_size_spin.setValue(int(layout.get("center_value_font_size", 30)))
        self.center_caption_size_spin.setValue(int(layout.get("center_caption_font_size", 11)))
        self.center_value_auto_fit_box.setChecked(bool(layout.get("center_value_auto_fit", True)))
        self.center_caption_auto_fit_box.setChecked(bool(layout.get("center_caption_auto_fit", True)))
        self.card_opacity_spin.setValue(float(style.get("card_opacity", 0.92)))
        self.shadow_enabled_box.setChecked(bool(style.get("shadow_enabled", True)))
        self.glow_enabled_box.setChecked(bool(style.get("use_glow", False)))
        self.background_color_field.set_text(str(style.get("background_color", "auto")))
        self.border_color_field.set_text(str(style.get("border_color", "auto")))
        self.global_track_color_field.set_text(str(style.get("track_color", "auto")))

        global_config = self._config_data.setdefault("global", deepcopy(default_config_dict()["global"]))
        screens = tuple(global_config.get("show_on_screens", ["deckBrowser", "overview"]))
        self.show_deck_browser_box.setChecked("deckBrowser" in screens)
        self.show_overview_box.setChecked("overview" in screens)
        self.theme_combo.setCurrentIndex(max(self.theme_combo.findData(global_config.get("theme", "auto")), 0))
        self.palette_combo.setCurrentIndex(max(self.palette_combo.findData(global_config.get("palette", "soft")), 0))
        self.dashboard_position_combo.setCurrentIndex(
            max(self.dashboard_position_combo.findData(global_config.get("dashboard_position", "top")), 0)
        )
        self.panel_margin_spin.setValue(int(global_config.get("panel_margin", 18)))
        self.panel_spacing_spin.setValue(int(global_config.get("panel_spacing", 16)))
        self.cache_ttl_spin.setValue(int(global_config.get("cache_ttl_seconds", 30)))
        self.match_widget_sizes_box.setChecked(bool(global_config.get("match_widget_sizes", True)))
        self.debug_timing_box.setChecked(bool(global_config.get("debug_timing", False)))

        self._sync_center_size_controls()
        self._sync_source_mode_widgets()
        self.ring_list_editor.set_widget_payload(widget)
        self._loading_form = False

    def _refresh_primary_ring_options(self, widget: dict[str, Any], selected_id: str = "") -> None:
        self.primary_ring_combo.blockSignals(True)
        self.primary_ring_combo.clear()
        rings = widget.get("rings", []) if isinstance(widget, dict) else []
        if not isinstance(rings, list):
            rings = []
        layout = widget.setdefault("layout", deepcopy(default_widget_payload()["layout"]))
        for index, ring in enumerate(rings):
            if not isinstance(ring, dict):
                continue
            ring_id = str(ring.get("id", "")).strip() or f"ring-{index + 1}"
            label = str(ring.get("label", "")).strip() or f"Ring {index + 1}"
            self.primary_ring_combo.addItem(label, ring_id)

        if self.primary_ring_combo.count():
            target = selected_id or str(layout.get("primary_ring_id", "") or "")
            index = self.primary_ring_combo.findData(target)
            if index < 0:
                index = 0
            self.primary_ring_combo.setCurrentIndex(index)
            layout["primary_ring_id"] = self.primary_ring_combo.currentData() or ""
        else:
            layout["primary_ring_id"] = ""
        self.primary_ring_combo.setEnabled(self.primary_ring_combo.count() > 0)
        self.primary_ring_combo.blockSignals(False)

    def _sync_center_size_controls(self) -> None:
        self.center_value_size_spin.setEnabled(not self.center_value_auto_fit_box.isChecked())
        self.center_caption_size_spin.setEnabled(not self.center_caption_auto_fit_box.isChecked())

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.basics_group,
            self.rings_group,
            self.ring_list_editor,
            self.editor_content,
        ):
            widget.setEnabled(enabled)

    def _update_sidebar_buttons(self) -> None:
        has_widget = self._current_widget() is not None
        count = len(self._widgets())
        index = self._current_widget_index()
        self.duplicate_widget_button.setEnabled(has_widget)
        self.remove_widget_button.setEnabled(has_widget)
        self.move_widget_up_button.setEnabled(has_widget and index > 0)
        self.move_widget_down_button.setEnabled(has_widget and 0 <= index < count - 1)
        self.reset_widget_button.setEnabled(has_widget)

    def _browse_tag(self) -> None:
        dialog = TagPickerDialog(self._tag_names, current_tag=self.tag_edit.text().strip(), parent=self)
        if dialog.exec():
            self.tag_edit.setText(dialog.selected_tag())

    def _browse_deck(self) -> None:
        dialog = DeckPickerDialog(self._deck_names, current_deck=self.deck_edit.text().strip(), parent=self)
        if dialog.exec():
            self.deck_edit.setText(dialog.selected_deck())

    def _sync_source_mode_widgets(self) -> None:
        source_type = self.source_mode_combo.currentData()
        self.tag_row.setVisible(source_type == "tag")
        self.deck_row.setVisible(source_type == "deck")
        self.search_row.setVisible(source_type == "search")
        self.today_row.setVisible(source_type == "today")
        deck_mode = self.today_scope_combo.currentData() == "deck"
        self.today_deck_edit.setVisible(deck_mode)
        self.include_children_box.setVisible(source_type == "tag")

    def _on_source_mode_changed(self) -> None:
        if self._loading_form:
            return
        source_type = self.source_mode_combo.currentData()
        widget = self._current_widget()
        if not widget:
            return
        source = widget.setdefault("source", default_source_payload())
        previous_type = str(source.get("type", "tag") or "tag")
        source["type"] = source_type
        if source_type == "tag":
            source.setdefault("tag", "")
            source["deck"] = ""
            source["search"] = ""
            source["scope"] = "all"
            source["include_children"] = True
        elif source_type == "deck":
            source.setdefault("deck", "")
            source["tag"] = ""
            source["search"] = ""
            source["scope"] = "all"
            source["include_children"] = False
        elif source_type == "search":
            source.setdefault("search", "")
            source["tag"] = ""
            source["deck"] = ""
            source["include_children"] = False
            source["scope"] = "all"
        else:
            source["tag"] = ""
            source["search"] = ""
            source["deck"] = ""
            source["include_children"] = False
            source.setdefault("scope", "all")
            source.setdefault("deck", "")
        if previous_type != source_type:
            if source_type == "today":
                widget["rings"] = deepcopy(default_today_widget_payload()["rings"])
                widget.setdefault("layout", deepcopy(default_widget_payload()["layout"]))["primary_ring_id"] = (
                    "today-review-completed"
                )
            elif previous_type == "today":
                widget["rings"] = deepcopy(default_widget_payload()["rings"])
                widget.setdefault("layout", deepcopy(default_widget_payload()["layout"]))["primary_ring_id"] = ""
        self._sync_source_mode_widgets()
        self._refresh_primary_ring_options(widget)
        self.ring_list_editor.set_widget_payload(widget)
        self._after_widget_edit(refresh_data=True, refresh_list=True)

    def _on_tag_changed(self, text: str) -> None:
        self.tag_edit.setToolTip(text.strip())
        self._update_source_field("tag", text.strip(), refresh_data=True, refresh_list=True)

    def _on_search_changed(self, text: str) -> None:
        self._update_source_field("search", text.strip(), refresh_data=True, refresh_list=True)

    def _on_deck_source_changed(self, text: str) -> None:
        cleaned = text.strip()
        self.deck_edit.setToolTip(cleaned)
        self._update_source_field("deck", cleaned, refresh_data=True, refresh_list=True)

    def _on_today_scope_changed(self, _index: int) -> None:
        if self._loading_form:
            return
        scope = str(self.today_scope_combo.currentData() or "all")
        self._sync_source_mode_widgets()
        self._update_source_field("scope", scope, refresh_data=True, refresh_list=True)

    def _on_today_deck_changed(self, text: str) -> None:
        cleaned = text.strip()
        self.today_deck_edit.setToolTip(cleaned)
        self._update_source_field("deck", cleaned, refresh_data=True, refresh_list=True)

    def _on_center_auto_fit_toggled(self, key: str, checked: bool) -> None:
        self._sync_center_size_controls()
        self._update_layout_field(key, bool(checked), refresh_data=False)

    def _update_current_widget(self, key: str, value: Any, *, refresh_data: bool, refresh_list: bool = False) -> None:
        if self._loading_form:
            return
        widget = self._current_widget()
        if not widget:
            return
        widget[key] = value
        if key == "title" and not str(widget.get("id", "")).strip():
            widget["id"] = self._unique_widget_id(value or "widget")
        self._after_widget_edit(refresh_data=refresh_data, refresh_list=refresh_list)

    def _update_source_field(self, key: str, value: Any, *, refresh_data: bool, refresh_list: bool = False) -> None:
        if self._loading_form:
            return
        widget = self._current_widget()
        if not widget:
            return
        source = widget.setdefault("source", default_source_payload())
        source[key] = value
        if key == "tag":
            self.tag_edit.setToolTip(str(value))
        if key == "deck":
            self.today_deck_edit.setToolTip(str(value))
        self._after_widget_edit(refresh_data=refresh_data, refresh_list=refresh_list)

    def _update_layout_field(self, key: str, value: Any, *, refresh_data: bool, refresh_list: bool = False) -> None:
        if self._loading_form:
            return
        widget = self._current_widget()
        if not widget:
            return
        widget.setdefault("layout", deepcopy(default_widget_payload()["layout"]))[key] = value
        self._after_widget_edit(refresh_data=refresh_data, refresh_list=refresh_list)

    def _update_style_field(self, key: str, value: Any, *, refresh_data: bool) -> None:
        if self._loading_form:
            return
        widget = self._current_widget()
        if not widget:
            return
        widget.setdefault("style", deepcopy(default_widget_payload()["style"]))[key] = value
        self._after_widget_edit(refresh_data=refresh_data, refresh_list=False)

    def _update_global_field(self, key: str, value: Any) -> None:
        if self._loading_form:
            return
        self._config_data.setdefault("global", deepcopy(default_config_dict()["global"]))[key] = value
        self._mark_dirty()
        self._render_preview()

    def _update_show_screens(self) -> None:
        if self._loading_form:
            return
        screens: list[str] = []
        if self.show_deck_browser_box.isChecked():
            screens.append("deckBrowser")
        if self.show_overview_box.isChecked():
            screens.append("overview")
        if not screens:
            screens = ["deckBrowser"]
        self._update_global_field("show_on_screens", screens)

    def _after_widget_edit(self, *, refresh_data: bool, refresh_list: bool) -> None:
        self._mark_dirty()
        if refresh_list:
            self._populate_widget_list()
        if refresh_data:
            self._preview_snapshot = None
            self._schedule_preview_refresh()
        else:
            self._render_preview()

    def _on_ring_list_changed(self, refresh_data: bool) -> None:
        widget = self._current_widget()
        if widget:
            self._refresh_primary_ring_options(widget)
        self._mark_dirty()
        if refresh_data:
            self._preview_snapshot = None
            self._schedule_preview_refresh()
        else:
            self._render_preview()

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_window_title()

    def _clear_dirty(self) -> None:
        self._dirty = False
        self._update_window_title()

    def _update_window_title(self) -> None:
        suffix = " *" if self._dirty else ""
        self.setWindowTitle(f"{ADDON_NAME}{suffix}")

    def _schedule_preview_refresh(self) -> None:
        self._preview_loading = True
        self._preview_status_text("Refreshing preview with current source and metric rules...")
        self._render_preview()
        self._preview_timer.start()

    def _start_preview_query(self) -> None:
        normalized = self._normalized_single_widget_result()
        if not normalized.config.widgets:
            self._preview_loading = False
            self._preview_snapshot = None
            self.source_status_label.setText("Choose a valid source to preview this widget.")
            self._preview_status_text("Previewing the current layout with sample data until the source is valid.")
            self._render_preview()
            return
        if not getattr(mw, "col", None):
            self._preview_loading = False
            self._preview_snapshot = None
            self.source_status_label.setText("Open a collection to preview real data.")
            self._render_preview()
            return

        self._preview_request_serial += 1
        request_id = self._preview_request_serial
        config = normalized.config
        op = QueryOp(
            parent=self,
            op=lambda col, cfg=config: collect_dashboard_stats(col, cfg),
            success=lambda snapshot, rid=request_id: self._on_preview_query_success(rid, snapshot),
        )
        op.failure(lambda error, rid=request_id: self._on_preview_query_failure(rid, error))
        op.run_in_background()

    def _on_preview_query_success(self, request_id: int, snapshot: DashboardSnapshot) -> None:
        if request_id != self._preview_request_serial:
            return
        self._preview_loading = False
        self._preview_snapshot = snapshot.widgets[0] if snapshot.widgets else None
        self._sync_source_status_from_preview()
        self._preview_status_text("Preview is showing the same renderer used on the dashboard.")
        self._render_preview()

    def _on_preview_query_failure(self, request_id: int, error: Exception) -> None:
        if request_id != self._preview_request_serial:
            return
        self._preview_loading = False
        self._preview_snapshot = None
        self.source_status_label.setText(f"Preview query failed: {error}")
        self._preview_status_text("Preview fell back to sample data because the live query failed.")
        self._render_preview()

    def _sync_source_status_from_preview(self) -> None:
        widget = self._current_widget()
        if not widget:
            self.source_status_label.setText("Add a widget to begin.")
            return
        source = widget.get("source", {}) if isinstance(widget, dict) else {}
        if isinstance(source, dict):
            source_type = str(source.get("type", "tag")).strip()
            if source_type == "tag" and not str(source.get("tag", "")).strip():
                self.source_status_label.setText("No tag selected yet. Click Browse or click the dashboard card to choose one.")
                return
            if source_type == "deck" and not str(source.get("deck", "")).strip():
                self.source_status_label.setText("No deck selected yet. Click Browse to choose one.")
                return
        if self._preview_snapshot is None:
            self.source_status_label.setText("Previewing sample data while the source is incomplete.")
            return
        snapshot = self._preview_snapshot
        if snapshot.state == "missing":
            source_type = str(source.get("type", "tag")).strip() if isinstance(source, dict) else "tag"
            self.source_status_label.setText("Deck was not found in this collection." if source_type == "deck" else "Tag was not found in this collection.")
        elif snapshot.state == "empty":
            self.source_status_label.setText("No cards matched this tag or search.")
        elif snapshot.state == "error":
            self.source_status_label.setText(snapshot.status_message or "The source could not be queried.")
        else:
            self.source_status_label.setText(f"{snapshot.total_cards:,} cards matched this widget source.")

    def _preview_status_text(self, text: str) -> None:
        self.preview_status_label.setText(text)

    def _normalized_single_widget_result(self):
        widget = self._current_widget()
        payload = {
            "global": deepcopy(self._config_data.get("global", default_config_dict()["global"])),
            "widgets": [deepcopy(widget)] if widget else [],
        }
        return load_config_from_object(payload)

    def _normalized_preview_result(self):
        result = self._normalized_single_widget_result()
        if result.config.widgets or self._current_widget() is None:
            return result

        widget = deepcopy(self._current_widget())
        assert widget is not None
        source = widget.setdefault("source", default_source_payload())
        if source.get("type") == "today":
            fallback = default_today_widget_payload()
            widget["source"] = fallback["source"]
            widget["rings"] = widget.get("rings") or fallback["rings"]
        else:
            source["type"] = "search"
            source["search"] = source.get("search") or "is:new"
            source["tag"] = ""
            source["include_children"] = False
        payload = {
            "global": deepcopy(self._config_data.get("global", default_config_dict()["global"])),
            "widgets": [widget],
        }
        return load_config_from_object(payload)

    def _render_preview(self) -> None:
        normalized = self._normalized_preview_result()
        config = normalized.config
        if config.widgets and self._preview_snapshot and self._preview_snapshot.widget_id != config.widgets[0].id:
            self._preview_snapshot = None

        snapshot: DashboardSnapshot | None = None
        if config.widgets and self._preview_snapshot:
            snapshot = DashboardSnapshot(widgets=(self._preview_snapshot,), generated_at=0.0)

        html = render_dashboard_html(config, snapshot, surface="preview", is_loading=self._preview_loading)
        self.preview_web.stdHtml(html, context=self)

    def _add_widget(self) -> None:
        widgets = self._widgets()
        if widgets:
            new_payload = default_widget_payload(widget_number=len(widgets) + 1)
        else:
            new_payload = default_today_widget_payload(widget_number=1)
        new_payload["id"] = self._unique_widget_id(new_payload["id"])
        widgets.append(new_payload)
        self._mark_dirty()
        self._populate_widget_list()
        self._restore_selection_by_id(new_payload["id"])
        self._preview_snapshot = None
        self._schedule_preview_refresh()

    def _duplicate_widget(self) -> None:
        widget = self._current_widget()
        if not widget:
            return
        widgets = self._widgets()
        clone = _deepcopy_widget(widget)
        title = str(clone.get("title", "")).strip() or "Widget"
        clone["title"] = f"{title} Copy"
        clone["id"] = self._unique_widget_id(clone["title"])
        widgets.insert(self._current_widget_index() + 1, clone)
        self._mark_dirty()
        self._populate_widget_list()
        self._restore_selection_by_id(clone["id"])
        self._preview_snapshot = None
        self._schedule_preview_refresh()

    def _remove_widget(self) -> None:
        index = self._current_widget_index()
        if index < 0:
            return
        widgets = self._widgets()
        widgets.pop(index)
        self._mark_dirty()
        self._populate_widget_list()
        if widgets:
            self.widget_list.setCurrentRow(min(index, len(widgets) - 1))
        else:
            self._on_widget_selection_changed(-1)

    def _move_widget(self, delta: int) -> None:
        index = self._current_widget_index()
        target = index + delta
        widgets = self._widgets()
        if not (0 <= index < len(widgets) and 0 <= target < len(widgets)):
            return
        widgets[index], widgets[target] = widgets[target], widgets[index]
        selected_id = str(widgets[target].get("id", "")).strip()
        self._mark_dirty()
        self._populate_widget_list()
        self._restore_selection_by_id(selected_id)

    def _reset_widget(self) -> None:
        widget = self._current_widget()
        if not widget:
            return
        response = QMessageBox.question(
            self,
            "Reset Widget",
            "Reset the selected widget to the default ring setup while keeping its current source?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return

        source = deepcopy(widget.get("source", default_source_payload()))
        title = str(widget.get("title", "")).strip()
        if str(source.get("type", "tag")) == "today":
            reset = default_today_widget_payload(
                title=title or "Today's Progress",
                widget_number=self._current_widget_index() + 1,
                scope=str(source.get("scope", "all") or "all"),
                deck=str(source.get("deck", "") or ""),
            )
        else:
            reset = default_widget_payload(title=title or "Widget", widget_number=self._current_widget_index() + 1)
            reset["source"] = source
        reset["id"] = self._unique_widget_id(widget.get("id") or title or "widget")
        self._widgets()[self._current_widget_index()] = reset
        self._mark_dirty()
        self._populate_widget_list()
        self._restore_selection_by_id(reset["id"])
        self._preview_snapshot = None
        self._schedule_preview_refresh()

    def _restore_defaults(self) -> None:
        response = QMessageBox.question(
            self,
            "Restore Defaults",
            "Replace the entire Activity Rings configuration with defaults?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self._config_data = default_config_dict()
        self._warnings = []
        self._mark_dirty()
        self._refresh_warning_banner()
        self._populate_widget_list()
        self._restore_initial_selection()
        self._preview_snapshot = None
        self._preview_loading = False
        self._render_preview()

    def _unique_widget_id(self, base: Any) -> str:
        existing = {
            str(widget.get("id", "")).strip()
            for widget in self._widgets()
            if widget is not self._current_widget()
        }
        root = _slugify(str(base or "widget"), "widget")
        candidate = root
        suffix = 2
        while candidate in existing:
            candidate = f"{root}-{suffix}"
            suffix += 1
        return candidate

    def _open_json_editor(self) -> None:
        dialog = JsonEditorDialog(deepcopy(self._config_data), parent=self)
        if not dialog.exec():
            return
        if dialog.result_payload is None:
            return
        self._config_data = dialog.result_payload
        self._warnings = list(dialog.result_warnings)
        self._mark_dirty()
        self._refresh_warning_banner()
        self._populate_widget_list()
        self._restore_initial_selection()
        self._preview_snapshot = None
        self._schedule_preview_refresh()

    def _apply_changes(self) -> None:
        self._write_config(show_saved_tooltip=True)

    def _save_changes(self) -> None:
        self._write_config(show_saved_tooltip=True)

    def _save_and_close(self) -> None:
        if self._write_config(show_saved_tooltip=True):
            saveGeom(self, GEOMETRY_KEY)
            super().accept()

    def _write_config(self, *, show_saved_tooltip: bool) -> bool:
        result = load_config_from_object(self._config_data)
        normalized_payload = addon_config_to_dict(result.config)
        raw_count = len(self._widgets())
        saved_count = len(result.config.widgets)
        warnings = list(result.warnings)
        selected_id = self._current_widget_id()

        if warnings or saved_count != raw_count:
            message = (
                "The current configuration needed repair before saving.\n\n"
                + "\n".join(warnings or ["Some invalid widgets would be skipped."])
                + "\n\nSave the repaired version?"
            )
            response = QMessageBox.question(self, "Confirm Save", message)
            if response != QMessageBox.StandardButton.Yes:
                return False

        mw.addonManager.writeConfig(MODULE, normalized_payload)
        try:
            from .dashboard import notify_config_saved

            notify_config_saved(normalized_payload)
        except Exception:
            pass
        self._config_data = normalized_payload
        self._saved_config_data = deepcopy(normalized_payload)
        self._warnings = warnings
        self._clear_dirty()
        self._refresh_warning_banner()

        self._populate_widget_list()
        self._restore_selection_by_id(selected_id)
        self._preview_snapshot = None
        self._schedule_preview_refresh()
        if show_saved_tooltip:
            tooltip("Activity Rings settings saved.")
        return True

    def _refresh_warning_banner(self) -> None:
        if self._warnings:
            self.warning_banner.setText("\n".join(self._warnings))
            self.warning_banner.show()
        else:
            self.warning_banner.hide()

    def _confirm_discard_if_needed(self) -> bool:
        if not self._dirty:
            return True
        response = QMessageBox.question(
            self,
            "Discard Unsaved Changes?",
            "You have unsaved changes. Close without saving?",
        )
        return response == QMessageBox.StandardButton.Yes


def open_settings_dialog() -> bool:
    dialog = ActivityRingsSettingsDialog()
    dialog.exec()
    return True


def install_settings_entrypoints() -> None:
    global _MENU_ACTION
    mw.addonManager.setConfigAction(MODULE, open_settings_dialog)
    if _MENU_ACTION is None:
        _MENU_ACTION = QAction("Activity Rings", mw)
        qconnect(_MENU_ACTION.triggered, open_settings_dialog)
        mw.form.menuTools.addAction(_MENU_ACTION)
