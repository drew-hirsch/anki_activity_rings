from __future__ import annotations

from copy import deepcopy
import json
import re
from dataclasses import dataclass
from typing import Any

from aqt import mw
from aqt.qt import QColor

from .metrics import (
    BUILTIN_ALL,
    BUILTIN_MATURE,
    BUILTIN_TODAY_ALL_COMPLETED,
    BUILTIN_TODAY_ALL_TOTAL,
    BUILTIN_TODAY_NEW_COMPLETED,
    BUILTIN_TODAY_NEW_TOTAL,
    BUILTIN_TODAY_REVIEW_COMPLETED,
    BUILTIN_TODAY_REVIEW_TOTAL,
    BUILTIN_UNSUSPENDED,
    BUILTIN_YOUNG,
    builtin_metric_definition,
    builtin_metric_label,
    is_builtin_metric_supported,
)

MODULE = __name__.split(".", 1)[0]

VALID_SCREEN_NAMES = {"deckBrowser", "overview"}
VALID_SOURCE_TYPES = {"tag", "deck", "search", "today"}
VALID_SOURCE_SCOPES = {"all", "deck"}
VALID_QUERY_TYPES = {"builtin", "search"}
VALID_LAYOUT_MODES = {"compact", "wide"}
VALID_TITLE_POSITIONS = {"above", "inside", "center", "hidden"}
VALID_DASHBOARD_POSITIONS = {"top", "bottom"}
VALID_CENTER_LABEL_MODES = {
    "none",
    "card_count",
    "primary_percent",
    "primary_metric",
    "title",
}
VALID_CLICK_ACTIONS = {"none", "source", "numerator"}
VALID_THEME_MODES = {"auto", "light", "dark"}
VALID_PALETTES = {"soft", "vibrant", "colorblind"}

DEFAULT_GLOBALS: dict[str, Any] = {
    "show_on_screens": ["deckBrowser", "overview"],
    "panel_margin": 18,
    "panel_spacing": 16,
    "match_widget_sizes": True,
    "cache_ttl_seconds": 30,
    "hide_when_no_widgets": False,
    "dashboard_position": "top",
    "theme": "auto",
    "palette": "soft",
    "default_card_style": "native",
    "debug_timing": False,
}
DEFAULT_SOURCE: dict[str, Any] = {
    "type": "tag",
    "tag": "",
    "include_children": True,
    "search": "",
    "scope": "all",
    "deck": "",
}
DEFAULT_LAYOUT: dict[str, Any] = {
    "mode": "compact",
    "title_position": "inside",
    "show_source_subtitle": False,
    "show_total_cards": True,
    "show_legend": True,
    "show_counts": True,
    "show_percentages": True,
    "ring_size": 204,
    "ring_thickness": 18,
    "ring_gap": 8,
    "card_min_width": 290,
    "card_max_width": 390,
    "card_aspect_ratio": 1.08,
    "card_padding": 18,
    "center_label_mode": "primary_percent",
    "primary_ring_id": "",
    "center_label_text": "",
    "center_value_font_size": 30,
    "center_value_auto_fit": True,
    "center_caption_font_size": 11,
    "center_caption_auto_fit": True,
    "click_action": "source",
    "ring_click_action": "numerator",
}
DEFAULT_STYLE: dict[str, Any] = {
    "background_color": "auto",
    "card_opacity": 0.92,
    "border_color": "auto",
    "shadow_enabled": True,
    "track_color": "auto",
    "use_glow": False,
}
DEFAULT_RINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "mature",
        "enabled": True,
        "label": "Mature",
        "metric": {"type": "builtin", "name": BUILTIN_MATURE},
        "denominator": {"type": "builtin", "name": BUILTIN_UNSUSPENDED},
        "color": "auto",
        "track_color": "auto",
    },
    {
        "id": "young",
        "enabled": True,
        "label": "Young/Learning",
        "metric": {"type": "builtin", "name": BUILTIN_YOUNG},
        "denominator": {"type": "builtin", "name": BUILTIN_UNSUSPENDED},
        "color": "auto",
        "track_color": "auto",
    },
    {
        "id": "unsuspended",
        "enabled": True,
        "label": "Unsuspended",
        "metric": {"type": "builtin", "name": BUILTIN_UNSUSPENDED},
        "denominator": {"type": "builtin", "name": BUILTIN_ALL},
        "color": "auto",
        "track_color": "auto",
    },
)
DEFAULT_TODAY_RINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "today_review_completed",
        "enabled": True,
        "label": "Review Done",
        "metric": {"type": "builtin", "name": BUILTIN_TODAY_REVIEW_COMPLETED},
        "denominator": {"type": "builtin", "name": BUILTIN_TODAY_REVIEW_TOTAL},
        "color": "auto",
        "track_color": "auto",
    },
    {
        "id": "today_new_completed",
        "enabled": True,
        "label": "New Done",
        "metric": {"type": "builtin", "name": BUILTIN_TODAY_NEW_COMPLETED},
        "denominator": {"type": "builtin", "name": BUILTIN_TODAY_NEW_TOTAL},
        "color": "auto",
        "track_color": "auto",
    },
)


def default_placeholder_tag_widget_payload(
    *,
    title: str,
    widget_number: int,
) -> dict[str, Any]:
    payload = default_widget_payload(title=title, widget_number=widget_number)
    payload["id"] = f"tag-{widget_number}"
    payload["layout"]["title_position"] = "inside"
    payload["layout"]["center_label_mode"] = "primary_percent"
    payload["layout"]["primary_ring_id"] = "unsuspended"
    payload["layout"]["center_value_font_size"] = 25
    payload["layout"]["show_source_subtitle"] = False
    payload["layout"]["show_total_cards"] = True
    payload["layout"]["show_legend"] = True
    payload["layout"]["show_counts"] = True
    payload["layout"]["show_percentages"] = True
    payload["layout"]["ring_size"] = 204
    payload["layout"]["ring_thickness"] = 18
    payload["layout"]["ring_gap"] = 8
    payload["layout"]["card_min_width"] = 290
    payload["layout"]["card_max_width"] = 390
    payload["layout"]["card_aspect_ratio"] = 1.08
    payload["layout"]["card_padding"] = 18
    payload["style"]["background_color"] = "auto"
    payload["style"]["card_opacity"] = 0.92
    payload["style"]["border_color"] = "auto"
    payload["style"]["shadow_enabled"] = True
    payload["style"]["track_color"] = "auto"
    payload["style"]["use_glow"] = False
    payload["source"]["type"] = "tag"
    payload["source"]["tag"] = ""
    payload["source"]["include_children"] = True
    payload["rings"][1]["label"] = "Learning"
    payload["rings"][2]["label"] = "Active"
    return payload


@dataclass(frozen=True)
class QueryConfig:
    type: str
    name: str | None
    search: str | None


@dataclass(frozen=True)
class SourceConfig:
    type: str
    tag: str | None
    include_children: bool
    search: str | None
    scope: str
    deck: str | None


@dataclass(frozen=True)
class LayoutConfig:
    mode: str
    title_position: str
    show_source_subtitle: bool
    show_total_cards: bool
    show_legend: bool
    show_counts: bool
    show_percentages: bool
    ring_size: int
    ring_thickness: int
    ring_gap: int
    card_min_width: int
    card_max_width: int
    card_aspect_ratio: float
    card_padding: int
    center_label_mode: str
    primary_ring_id: str | None
    center_label_text: str | None
    center_value_font_size: int
    center_value_auto_fit: bool
    center_caption_font_size: int
    center_caption_auto_fit: bool
    click_action: str
    ring_click_action: str


@dataclass(frozen=True)
class StyleConfig:
    background_color: str | None
    card_opacity: float
    border_color: str | None
    shadow_enabled: bool
    track_color: str | None
    use_glow: bool


@dataclass(frozen=True)
class RingConfig:
    id: str
    enabled: bool
    label: str
    metric: QueryConfig
    denominator: QueryConfig
    color: str | None
    track_color: str | None


@dataclass(frozen=True)
class WidgetConfig:
    id: str
    title: str
    source: SourceConfig
    layout: LayoutConfig
    style: StyleConfig
    rings: tuple[RingConfig, ...]


@dataclass(frozen=True)
class GlobalConfig:
    show_on_screens: tuple[str, ...]
    panel_margin: int
    panel_spacing: int
    match_widget_sizes: bool
    cache_ttl_seconds: int
    hide_when_no_widgets: bool
    dashboard_position: str
    theme: str
    palette: str
    default_card_style: str
    debug_timing: bool


@dataclass(frozen=True)
class AddonConfig:
    global_config: GlobalConfig
    widgets: tuple[WidgetConfig, ...]


@dataclass(frozen=True)
class ConfigLoadResult:
    config: AddonConfig
    warnings: tuple[str, ...]


def load_config() -> ConfigLoadResult:
    raw = mw.addonManager.getConfig(MODULE) or {}
    return load_config_from_object(raw)


def load_config_from_json_string(raw_json: str) -> ConfigLoadResult:
    try:
        parsed = json.loads(raw_json)
    except Exception:
        parsed = {}
    return load_config_from_object(parsed)


def default_query_payload(*, builtin_name: str | None = None, search: str = "") -> dict[str, Any]:
    if builtin_name:
        return {"type": "builtin", "name": builtin_name}
    return {"type": "search", "search": search}


def default_ring_payload(index: int = 0) -> dict[str, Any]:
    ring = deepcopy(DEFAULT_RINGS[index % len(DEFAULT_RINGS)])
    return ring


def default_source_payload(
    *,
    source_type: str = "tag",
    tag: str = "",
    search: str = "",
    scope: str = "all",
    deck: str = "",
) -> dict[str, Any]:
    payload = deepcopy(DEFAULT_SOURCE)
    payload["type"] = source_type
    payload["tag"] = tag.strip()
    payload["search"] = search.strip()
    payload["scope"] = scope if scope in VALID_SOURCE_SCOPES else DEFAULT_SOURCE["scope"]
    payload["deck"] = deck.strip()
    return payload


def default_widget_payload(
    *,
    title: str = "",
    tag: str = "",
    widget_number: int = 1,
) -> dict[str, Any]:
    fallback_title = title.strip() or tag.strip() or f"Widget {widget_number}"
    source = default_source_payload(tag=tag.strip())
    return {
        "id": _normalize_slug(fallback_title or f"widget-{widget_number}", fallback=f"widget-{widget_number}"),
        "title": fallback_title,
        "source": source,
        "layout": deepcopy(DEFAULT_LAYOUT),
        "style": deepcopy(DEFAULT_STYLE),
        "rings": [default_ring_payload(0), default_ring_payload(1), default_ring_payload(2)],
    }


def default_today_widget_payload(
    *,
    title: str = "Today's Progress",
    widget_number: int = 1,
    scope: str = "all",
    deck: str = "",
) -> dict[str, Any]:
    payload = default_widget_payload(title=title, widget_number=widget_number)
    payload["source"] = default_source_payload(
        source_type="today",
        scope=scope,
        deck=deck,
    )
    payload["layout"]["title_position"] = "inside"
    payload["layout"]["center_label_mode"] = "primary_percent"
    payload["layout"]["primary_ring_id"] = "today-review-completed"
    payload["layout"]["center_label_text"] = "Done"
    payload["layout"]["center_value_font_size"] = 25
    payload["layout"]["show_source_subtitle"] = False
    payload["layout"]["show_total_cards"] = True
    payload["layout"]["ring_size"] = 210
    payload["layout"]["ring_thickness"] = 18
    payload["layout"]["ring_gap"] = 9
    payload["rings"] = [
        {
            "id": "today-review-completed",
            "enabled": True,
            "label": "Total Cards",
            "metric": {"type": "builtin", "name": BUILTIN_TODAY_ALL_COMPLETED},
            "denominator": {"type": "builtin", "name": BUILTIN_TODAY_ALL_TOTAL},
            "color": "auto",
            "track_color": "auto",
        },
        {
            "id": "review-done-copy",
            "enabled": True,
            "label": "Review Cards",
            "metric": {"type": "builtin", "name": BUILTIN_TODAY_REVIEW_COMPLETED},
            "denominator": {"type": "builtin", "name": BUILTIN_TODAY_REVIEW_TOTAL},
            "color": "auto",
            "track_color": "auto",
        },
        {
            "id": "today-new-completed",
            "enabled": True,
            "label": "New Cards",
            "metric": {"type": "builtin", "name": BUILTIN_TODAY_NEW_COMPLETED},
            "denominator": {"type": "builtin", "name": BUILTIN_TODAY_NEW_TOTAL},
            "color": "auto",
            "track_color": "auto",
        },
    ]
    payload["id"] = _normalize_slug(title, fallback=f"today-progress-{widget_number}")
    return payload


def default_config_dict() -> dict[str, Any]:
    return {
        "global": {
            **deepcopy(DEFAULT_GLOBALS),
            "show_on_screens": ["deckBrowser"],
        },
        "widgets": [
            default_today_widget_payload(widget_number=1),
            default_placeholder_tag_widget_payload(title="Click to Configure", widget_number=2),
            default_placeholder_tag_widget_payload(title="Click to Configure", widget_number=3),
        ],
    }


def addon_config_to_dict(config: AddonConfig) -> dict[str, Any]:
    return {
        "global": global_config_to_dict(config.global_config),
        "widgets": [widget_config_to_dict(widget) for widget in config.widgets],
    }


def global_config_to_dict(global_config: GlobalConfig) -> dict[str, Any]:
    return {
        "show_on_screens": list(global_config.show_on_screens),
        "panel_margin": global_config.panel_margin,
        "panel_spacing": global_config.panel_spacing,
        "match_widget_sizes": global_config.match_widget_sizes,
        "cache_ttl_seconds": global_config.cache_ttl_seconds,
        "hide_when_no_widgets": global_config.hide_when_no_widgets,
        "dashboard_position": global_config.dashboard_position,
        "theme": global_config.theme,
        "palette": global_config.palette,
        "default_card_style": global_config.default_card_style,
        "debug_timing": global_config.debug_timing,
    }


def widget_config_to_dict(widget: WidgetConfig) -> dict[str, Any]:
    return {
        "id": widget.id,
        "title": widget.title,
        "source": source_config_to_dict(widget.source),
        "layout": layout_config_to_dict(widget.layout),
        "style": style_config_to_dict(widget.style),
        "rings": [ring_config_to_dict(ring) for ring in widget.rings],
    }


def source_config_to_dict(source: SourceConfig) -> dict[str, Any]:
    payload = {
        "type": source.type,
        "include_children": source.include_children,
    }
    if source.type == "tag":
        payload["tag"] = source.tag or ""
    if source.type == "deck":
        payload["deck"] = source.deck or ""
    if source.type == "search" and source.search:
        payload["search"] = source.search
    if source.type == "today":
        payload["scope"] = source.scope
        if source.deck:
            payload["deck"] = source.deck
    return payload


def layout_config_to_dict(layout: LayoutConfig) -> dict[str, Any]:
    return {
        "mode": layout.mode,
        "title_position": layout.title_position,
        "show_source_subtitle": layout.show_source_subtitle,
        "show_total_cards": layout.show_total_cards,
        "show_legend": layout.show_legend,
        "show_counts": layout.show_counts,
        "show_percentages": layout.show_percentages,
        "ring_size": layout.ring_size,
        "ring_thickness": layout.ring_thickness,
        "ring_gap": layout.ring_gap,
        "card_min_width": layout.card_min_width,
        "card_max_width": layout.card_max_width,
        "card_aspect_ratio": layout.card_aspect_ratio,
        "card_padding": layout.card_padding,
        "center_label_mode": layout.center_label_mode,
        "primary_ring_id": layout.primary_ring_id or "",
        "center_label_text": layout.center_label_text or "",
        "center_value_font_size": layout.center_value_font_size,
        "center_value_auto_fit": layout.center_value_auto_fit,
        "center_caption_font_size": layout.center_caption_font_size,
        "center_caption_auto_fit": layout.center_caption_auto_fit,
        "click_action": layout.click_action,
        "ring_click_action": layout.ring_click_action,
    }


def style_config_to_dict(style: StyleConfig) -> dict[str, Any]:
    return {
        "background_color": style.background_color or "auto",
        "card_opacity": style.card_opacity,
        "border_color": style.border_color or "auto",
        "shadow_enabled": style.shadow_enabled,
        "track_color": style.track_color or "auto",
        "use_glow": style.use_glow,
    }


def ring_config_to_dict(ring: RingConfig) -> dict[str, Any]:
    return {
        "id": ring.id,
        "enabled": ring.enabled,
        "label": ring.label,
        "metric": query_config_to_dict(ring.metric),
        "denominator": query_config_to_dict(ring.denominator),
        "color": ring.color or "auto",
        "track_color": ring.track_color or "auto",
    }


def query_config_to_dict(query: QueryConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": query.type}
    if query.name:
        payload["name"] = query.name
    if query.search:
        payload["search"] = query.search
    return payload


def load_config_from_object(raw: Any) -> ConfigLoadResult:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        warnings.append("Top-level config must be a JSON object. Falling back to defaults.")
        raw = {}

    migrated, migration_warnings = _migrate_if_needed(raw)
    warnings.extend(migration_warnings)

    raw_global = migrated.get("global", {})
    raw_widgets = migrated.get("widgets", [])
    if not isinstance(raw_global, dict):
        warnings.append("`global` must be an object. Using defaults.")
        raw_global = {}
    if not isinstance(raw_widgets, list):
        warnings.append("`widgets` must be a list. Falling back to an empty widget list.")
        raw_widgets = []

    global_config = _normalize_global(raw_global, warnings)

    widgets: list[WidgetConfig] = []
    seen_widget_ids: set[str] = set()
    for index, raw_widget in enumerate(raw_widgets):
        widget = _normalize_widget(raw_widget, index, seen_widget_ids, warnings)
        if widget:
            widgets.append(widget)

    return ConfigLoadResult(
        config=AddonConfig(global_config=global_config, widgets=tuple(widgets)),
        warnings=tuple(warnings),
    )


def _migrate_if_needed(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if "global" in raw:
        return deepcopy(raw), []

    if "widgets" not in raw and "show_on_screens" not in raw:
        return deepcopy(default_config_dict()), []

    migrated = default_config_dict()
    warnings = [
        "Migrated legacy Activity Rings config into the newer source/layout schema.",
    ]

    migrated["global"]["show_on_screens"] = deepcopy(
        raw.get("show_on_screens", DEFAULT_GLOBALS["show_on_screens"])
    )
    migrated["global"]["panel_margin"] = raw.get("panel_margin", DEFAULT_GLOBALS["panel_margin"])
    migrated["global"]["panel_spacing"] = raw.get("panel_spacing", DEFAULT_GLOBALS["panel_spacing"])
    migrated["global"]["cache_ttl_seconds"] = raw.get(
        "cache_ttl_seconds", DEFAULT_GLOBALS["cache_ttl_seconds"]
    )
    migrated["global"]["hide_when_no_widgets"] = raw.get(
        "hide_when_no_widgets", DEFAULT_GLOBALS["hide_when_no_widgets"]
    )

    widgets = raw.get("widgets", [])
    if not isinstance(widgets, list):
        widgets = []

    migrated_widgets: list[dict[str, Any]] = []
    for index, raw_widget in enumerate(widgets):
        if not isinstance(raw_widget, dict):
            continue

        source_tag = str(raw_widget.get("tag", "")).strip()
        title = str(raw_widget.get("title", "")).strip() or source_tag or f"Widget {index + 1}"
        widget = default_widget_payload(title=title, tag=source_tag, widget_number=index + 1)
        widget["id"] = str(raw_widget.get("id", "")).strip() or widget["id"]

        layout = widget["layout"]
        layout["title_position"] = str(raw_widget.get("title_position", layout["title_position"])).strip() or layout["title_position"]
        layout["show_counts"] = bool(raw_widget.get("show_counts", False))
        layout["show_percentages"] = bool(raw_widget.get("show_percent_text", True))
        layout["show_total_cards"] = bool(raw_widget.get("show_total_cards", True))
        layout["ring_size"] = raw_widget.get("size", layout["ring_size"])
        layout["ring_thickness"] = raw_widget.get("ring_thickness", layout["ring_thickness"])
        layout["ring_gap"] = raw_widget.get("ring_gap", layout["ring_gap"])
        layout["card_padding"] = raw_widget.get("padding", layout["card_padding"])
        layout["mode"] = "wide"
        if layout["title_position"] == "inside":
            layout["center_label_mode"] = "card_count"

        style = widget["style"]
        style["background_color"] = raw_widget.get("background_color", style["background_color"])
        style["track_color"] = raw_widget.get("track_color", style["track_color"])

        migrated_rings: list[dict[str, Any]] = []
        raw_rings = raw_widget.get("rings", [])
        if isinstance(raw_rings, list):
            for ring_index, raw_ring in enumerate(raw_rings):
                if not isinstance(raw_ring, dict):
                    continue
                metric_name = str(raw_ring.get("metric", "")).strip()
                if metric_name == "custom_search":
                    metric_query = {
                        "type": "search",
                        "search": str(raw_ring.get("search", "")).strip(),
                    }
                else:
                    metric_query = {
                        "type": "builtin",
                        "name": metric_name or DEFAULT_RINGS[ring_index % len(DEFAULT_RINGS)]["metric"]["name"],
                    }

                denominator_name = BUILTIN_UNSUSPENDED
                builtin_name = metric_query.get("name")
                if builtin_name in {BUILTIN_UNSUSPENDED, "suspended"}:
                    denominator_name = BUILTIN_ALL

                migrated_rings.append(
                    {
                        "id": str(raw_ring.get("id", "")).strip() or _normalize_slug(
                            str(raw_ring.get("label", "")).strip() or metric_name or f"ring-{ring_index + 1}",
                            fallback=f"ring-{ring_index + 1}",
                        ),
                        "enabled": True,
                        "label": str(raw_ring.get("label", "")).strip()
                        or _legacy_ring_label(metric_query),
                        "metric": metric_query,
                        "denominator": {"type": "builtin", "name": denominator_name},
                        "color": raw_ring.get("color", "auto"),
                        "track_color": raw_ring.get("track_color", "auto"),
                    }
                )
        if migrated_rings:
            widget["rings"] = migrated_rings

        migrated_widgets.append(widget)

    migrated["widgets"] = migrated_widgets
    return migrated, warnings


def _legacy_ring_label(metric_query: dict[str, Any]) -> str:
    if metric_query.get("type") == "search":
        return "Custom Search"
    return builtin_metric_label(str(metric_query.get("name", "")))


def _normalize_global(raw: dict[str, Any], warnings: list[str]) -> GlobalConfig:
    screens = _normalize_screens(raw.get("show_on_screens"), warnings)
    panel_margin = _normalize_int(
        raw.get("panel_margin"),
        DEFAULT_GLOBALS["panel_margin"],
        0,
        64,
        "global.panel_margin",
        warnings,
    )
    panel_spacing = _normalize_int(
        raw.get("panel_spacing"),
        DEFAULT_GLOBALS["panel_spacing"],
        0,
        48,
        "global.panel_spacing",
        warnings,
    )
    cache_ttl_seconds = _normalize_int(
        raw.get("cache_ttl_seconds"),
        DEFAULT_GLOBALS["cache_ttl_seconds"],
        0,
        600,
        "global.cache_ttl_seconds",
        warnings,
    )
    match_widget_sizes = _normalize_bool(
        raw.get("match_widget_sizes"),
        DEFAULT_GLOBALS["match_widget_sizes"],
        "global.match_widget_sizes",
        warnings,
    )
    hide_when_no_widgets = _normalize_bool(
        raw.get("hide_when_no_widgets"),
        DEFAULT_GLOBALS["hide_when_no_widgets"],
        "global.hide_when_no_widgets",
        warnings,
    )
    dashboard_position = _normalize_choice(
        raw.get("dashboard_position"),
        DEFAULT_GLOBALS["dashboard_position"],
        VALID_DASHBOARD_POSITIONS,
        "global.dashboard_position",
        warnings,
    )
    theme = _normalize_choice(
        raw.get("theme"),
        DEFAULT_GLOBALS["theme"],
        VALID_THEME_MODES,
        "global.theme",
        warnings,
    )
    palette = _normalize_choice(
        raw.get("palette"),
        DEFAULT_GLOBALS["palette"],
        VALID_PALETTES,
        "global.palette",
        warnings,
    )
    default_card_style = _normalize_text(
        raw.get("default_card_style"), DEFAULT_GLOBALS["default_card_style"]
    )
    debug_timing = _normalize_bool(
        raw.get("debug_timing"),
        DEFAULT_GLOBALS["debug_timing"],
        "global.debug_timing",
        warnings,
    )
    return GlobalConfig(
        show_on_screens=tuple(screens),
        panel_margin=panel_margin,
        panel_spacing=panel_spacing,
        match_widget_sizes=match_widget_sizes,
        cache_ttl_seconds=cache_ttl_seconds,
        hide_when_no_widgets=hide_when_no_widgets,
        dashboard_position=dashboard_position,
        theme=theme,
        palette=palette,
        default_card_style=default_card_style,
        debug_timing=debug_timing,
    )


def _normalize_widget(
    raw_widget: Any,
    index: int,
    seen_widget_ids: set[str],
    warnings: list[str],
) -> WidgetConfig | None:
    if not isinstance(raw_widget, dict):
        warnings.append(f"Widget #{index + 1} must be an object. Skipping it.")
        return None

    source = _normalize_source(raw_widget.get("source"), index, warnings)
    if source is None:
        warnings.append(f"Widget #{index + 1} has no valid source. Skipping it.")
        return None

    fallback_title = _default_title_for_source(source, index)
    title = _normalize_text(raw_widget.get("title"), fallback_title)
    widget_id = _normalize_widget_id(
        raw_widget.get("id"),
        title,
        fallback_title,
        index,
        seen_widget_ids,
    )
    layout = _normalize_layout(raw_widget.get("layout"), widget_id, warnings)
    style = _normalize_style(raw_widget.get("style"), widget_id, warnings)
    rings = _normalize_rings(raw_widget.get("rings"), widget_id, warnings)

    max_width = max(layout.card_min_width, layout.card_max_width)
    min_width = min(layout.card_min_width, max_width)
    if min_width != layout.card_min_width or max_width != layout.card_max_width:
        warnings.append(
            f"`{widget_id}.layout.card_min_width` and `.card_max_width` were adjusted to a valid range."
        )
        layout = LayoutConfig(
            mode=layout.mode,
            title_position=layout.title_position,
            show_source_subtitle=layout.show_source_subtitle,
            show_total_cards=layout.show_total_cards,
            show_legend=layout.show_legend,
            show_counts=layout.show_counts,
            show_percentages=layout.show_percentages,
            ring_size=layout.ring_size,
            ring_thickness=min(
                layout.ring_thickness,
                _max_ring_thickness(layout.ring_size, layout.ring_gap, len(rings)),
            ),
            ring_gap=layout.ring_gap,
            card_min_width=min_width,
            card_max_width=max_width,
            card_aspect_ratio=layout.card_aspect_ratio,
            card_padding=layout.card_padding,
            center_label_mode=layout.center_label_mode,
            primary_ring_id=layout.primary_ring_id,
            center_label_text=layout.center_label_text,
            center_value_font_size=layout.center_value_font_size,
            center_value_auto_fit=layout.center_value_auto_fit,
            center_caption_font_size=layout.center_caption_font_size,
            center_caption_auto_fit=layout.center_caption_auto_fit,
            click_action=layout.click_action,
            ring_click_action=layout.ring_click_action,
        )

    return WidgetConfig(
        id=widget_id,
        title=title,
        source=source,
        layout=layout,
        style=style,
        rings=rings,
    )


def _normalize_source(
    raw_source: Any,
    index: int,
    warnings: list[str],
) -> SourceConfig | None:
    if raw_source is None:
        raw_source = {}
    if not isinstance(raw_source, dict):
        warnings.append(f"`widgets[{index}].source` must be an object.")
        return None

    source_type = _normalize_choice(
        raw_source.get("type"),
        DEFAULT_SOURCE["type"],
        VALID_SOURCE_TYPES,
        f"widgets[{index}].source.type",
        warnings,
    )
    include_children = _normalize_bool(
        raw_source.get("include_children"),
        DEFAULT_SOURCE["include_children"],
        f"widgets[{index}].source.include_children",
        warnings,
    )
    tag = _normalize_text(raw_source.get("tag"), "")
    search = _normalize_text(raw_source.get("search"), "")
    scope = _normalize_choice(
        raw_source.get("scope"),
        DEFAULT_SOURCE["scope"],
        VALID_SOURCE_SCOPES,
        f"widgets[{index}].source.scope",
        warnings,
    )
    deck = _normalize_text(raw_source.get("deck"), "")

    if source_type == "tag":
        return SourceConfig(
            type=source_type,
            tag=tag or None,
            include_children=include_children,
            search=None,
            scope=DEFAULT_SOURCE["scope"],
            deck=None,
        )

    if source_type == "deck":
        return SourceConfig(
            type=source_type,
            tag=None,
            include_children=False,
            search=None,
            scope=DEFAULT_SOURCE["scope"],
            deck=deck or None,
        )

    if source_type == "search":
        if not search:
            return None
        return SourceConfig(
            type=source_type,
            tag=None,
            include_children=False,
            search=search,
            scope=DEFAULT_SOURCE["scope"],
            deck=None,
        )

    if scope == "deck" and not deck:
        warnings.append(
            f"`widgets[{index}].source.deck` is required when `source.type` is `today` and `scope` is `deck`."
        )
        return None
    return SourceConfig(
        type=source_type,
        tag=None,
        include_children=False,
        search=None,
        scope=scope,
        deck=deck or None,
    )


def _normalize_layout(raw_layout: Any, widget_id: str, warnings: list[str]) -> LayoutConfig:
    if raw_layout is None:
        raw_layout = {}
    if not isinstance(raw_layout, dict):
        warnings.append(f"`{widget_id}.layout` must be an object. Using defaults.")
        raw_layout = {}

    mode = _normalize_choice(
        raw_layout.get("mode"),
        DEFAULT_LAYOUT["mode"],
        VALID_LAYOUT_MODES,
        f"{widget_id}.layout.mode",
        warnings,
    )
    title_position = _normalize_choice(
        raw_layout.get("title_position"),
        DEFAULT_LAYOUT["title_position"],
        VALID_TITLE_POSITIONS,
        f"{widget_id}.layout.title_position",
        warnings,
    )
    show_source_subtitle = _normalize_bool(
        raw_layout.get("show_source_subtitle"),
        DEFAULT_LAYOUT["show_source_subtitle"],
        f"{widget_id}.layout.show_source_subtitle",
        warnings,
    )
    show_total_cards = _normalize_bool(
        raw_layout.get("show_total_cards"),
        DEFAULT_LAYOUT["show_total_cards"],
        f"{widget_id}.layout.show_total_cards",
        warnings,
    )
    show_legend = _normalize_bool(
        raw_layout.get("show_legend"),
        DEFAULT_LAYOUT["show_legend"],
        f"{widget_id}.layout.show_legend",
        warnings,
    )
    show_counts = _normalize_bool(
        raw_layout.get("show_counts"),
        DEFAULT_LAYOUT["show_counts"],
        f"{widget_id}.layout.show_counts",
        warnings,
    )
    show_percentages = _normalize_bool(
        raw_layout.get("show_percentages"),
        DEFAULT_LAYOUT["show_percentages"],
        f"{widget_id}.layout.show_percentages",
        warnings,
    )
    ring_size = _normalize_int(
        raw_layout.get("ring_size"),
        DEFAULT_LAYOUT["ring_size"],
        120,
        320,
        f"{widget_id}.layout.ring_size",
        warnings,
    )
    ring_gap = _normalize_int(
        raw_layout.get("ring_gap"),
        DEFAULT_LAYOUT["ring_gap"],
        0,
        20,
        f"{widget_id}.layout.ring_gap",
        warnings,
    )
    ring_thickness = _normalize_int(
        raw_layout.get("ring_thickness"),
        DEFAULT_LAYOUT["ring_thickness"],
        4,
        80,
        f"{widget_id}.layout.ring_thickness",
        warnings,
    )
    card_min_width = _normalize_int(
        raw_layout.get("card_min_width"),
        DEFAULT_LAYOUT["card_min_width"],
        220,
        600,
        f"{widget_id}.layout.card_min_width",
        warnings,
    )
    card_max_width = _normalize_int(
        raw_layout.get("card_max_width"),
        DEFAULT_LAYOUT["card_max_width"],
        260,
        720,
        f"{widget_id}.layout.card_max_width",
        warnings,
    )
    card_aspect_ratio = _normalize_float(
        raw_layout.get("card_aspect_ratio"),
        DEFAULT_LAYOUT["card_aspect_ratio"],
        0.75,
        2.5,
        f"{widget_id}.layout.card_aspect_ratio",
        warnings,
    )
    card_padding = _normalize_int(
        raw_layout.get("card_padding"),
        DEFAULT_LAYOUT["card_padding"],
        8,
        36,
        f"{widget_id}.layout.card_padding",
        warnings,
    )
    center_label_mode = _normalize_choice(
        raw_layout.get("center_label_mode"),
        DEFAULT_LAYOUT["center_label_mode"],
        VALID_CENTER_LABEL_MODES,
        f"{widget_id}.layout.center_label_mode",
        warnings,
    )
    primary_ring_id = _normalize_text(raw_layout.get("primary_ring_id"), "") or None
    center_label_text = _normalize_text(raw_layout.get("center_label_text"), "") or None
    center_value_font_size = _normalize_int(
        raw_layout.get("center_value_font_size"),
        DEFAULT_LAYOUT["center_value_font_size"],
        14,
        48,
        f"{widget_id}.layout.center_value_font_size",
        warnings,
    )
    center_value_auto_fit = _normalize_bool(
        raw_layout.get("center_value_auto_fit"),
        DEFAULT_LAYOUT["center_value_auto_fit"],
        f"{widget_id}.layout.center_value_auto_fit",
        warnings,
    )
    center_caption_font_size = _normalize_int(
        raw_layout.get("center_caption_font_size"),
        DEFAULT_LAYOUT["center_caption_font_size"],
        8,
        24,
        f"{widget_id}.layout.center_caption_font_size",
        warnings,
    )
    center_caption_auto_fit = _normalize_bool(
        raw_layout.get("center_caption_auto_fit"),
        DEFAULT_LAYOUT["center_caption_auto_fit"],
        f"{widget_id}.layout.center_caption_auto_fit",
        warnings,
    )
    click_action = _normalize_choice(
        raw_layout.get("click_action"),
        DEFAULT_LAYOUT["click_action"],
        VALID_CLICK_ACTIONS,
        f"{widget_id}.layout.click_action",
        warnings,
    )
    ring_click_action = _normalize_choice(
        raw_layout.get("ring_click_action"),
        DEFAULT_LAYOUT["ring_click_action"],
        VALID_CLICK_ACTIONS,
        f"{widget_id}.layout.ring_click_action",
        warnings,
    )

    max_thickness = _max_ring_thickness(ring_size, ring_gap, len(DEFAULT_RINGS))
    if ring_thickness > max_thickness:
        warnings.append(
            f"`{widget_id}.layout.ring_thickness` was clamped to fit inside the configured ring size."
        )
        ring_thickness = max_thickness

    return LayoutConfig(
        mode=mode,
        title_position=title_position,
        show_source_subtitle=show_source_subtitle,
        show_total_cards=show_total_cards,
        show_legend=show_legend,
        show_counts=show_counts,
        show_percentages=show_percentages,
        ring_size=ring_size,
        ring_thickness=ring_thickness,
        ring_gap=ring_gap,
        card_min_width=card_min_width,
        card_max_width=card_max_width,
        card_aspect_ratio=card_aspect_ratio,
        card_padding=card_padding,
        center_label_mode=center_label_mode,
        primary_ring_id=primary_ring_id,
        center_label_text=center_label_text,
        center_value_font_size=center_value_font_size,
        center_value_auto_fit=center_value_auto_fit,
        center_caption_font_size=center_caption_font_size,
        center_caption_auto_fit=center_caption_auto_fit,
        click_action=click_action,
        ring_click_action=ring_click_action,
    )


def _normalize_style(raw_style: Any, widget_id: str, warnings: list[str]) -> StyleConfig:
    if raw_style is None:
        raw_style = {}
    if not isinstance(raw_style, dict):
        warnings.append(f"`{widget_id}.style` must be an object. Using defaults.")
        raw_style = {}

    background_color = _normalize_color(
        raw_style.get("background_color"),
        None,
        allow_auto=True,
        field_name=f"{widget_id}.style.background_color",
        warnings=warnings,
    )
    card_opacity = _normalize_float(
        raw_style.get("card_opacity"),
        DEFAULT_STYLE["card_opacity"],
        0.0,
        1.0,
        f"{widget_id}.style.card_opacity",
        warnings,
    )
    border_color = _normalize_color(
        raw_style.get("border_color"),
        None,
        allow_auto=True,
        field_name=f"{widget_id}.style.border_color",
        warnings=warnings,
    )
    shadow_enabled = _normalize_bool(
        raw_style.get("shadow_enabled"),
        DEFAULT_STYLE["shadow_enabled"],
        f"{widget_id}.style.shadow_enabled",
        warnings,
    )
    track_color = _normalize_color(
        raw_style.get("track_color"),
        None,
        allow_auto=True,
        field_name=f"{widget_id}.style.track_color",
        warnings=warnings,
    )
    use_glow = _normalize_bool(
        raw_style.get("use_glow"),
        DEFAULT_STYLE["use_glow"],
        f"{widget_id}.style.use_glow",
        warnings,
    )
    return StyleConfig(
        background_color=background_color,
        card_opacity=card_opacity,
        border_color=border_color,
        shadow_enabled=shadow_enabled,
        track_color=track_color,
        use_glow=use_glow,
    )


def _normalize_rings(raw_rings: Any, widget_id: str, warnings: list[str]) -> tuple[RingConfig, ...]:
    if raw_rings is None:
        raw_rings = []
    if not isinstance(raw_rings, list):
        warnings.append(f"`{widget_id}.rings` must be a list. Using the default rings.")
        raw_rings = []

    rings: list[RingConfig] = []
    seen_ring_ids: set[str] = set()

    for index, raw_ring in enumerate(raw_rings):
        if not isinstance(raw_ring, dict):
            warnings.append(f"`{widget_id}.rings[{index}]` must be an object. Skipping it.")
            continue

        ring_id = _normalize_widget_id(
            raw_ring.get("id"),
            _normalize_text(raw_ring.get("label"), f"Ring {index + 1}"),
            f"ring-{index + 1}",
            index,
            seen_ring_ids,
        )
        enabled = _normalize_bool(
            raw_ring.get("enabled"),
            True,
            f"{widget_id}.rings[{index}].enabled",
            warnings,
        )
        metric = _normalize_query(
            raw_ring.get("metric"),
            f"{widget_id}.rings[{index}].metric",
            warnings,
        )
        denominator = _normalize_query(
            raw_ring.get("denominator"),
            f"{widget_id}.rings[{index}].denominator",
            warnings,
        )
        if metric is None or denominator is None:
            warnings.append(f"`{widget_id}.rings[{index}]` is missing a usable metric or denominator. Skipping it.")
            continue

        label = _normalize_text(
            raw_ring.get("label"),
            _default_ring_label(metric, denominator),
        )
        color = _normalize_color(
            raw_ring.get("color"),
            None,
            allow_auto=True,
            field_name=f"{widget_id}.rings[{index}].color",
            warnings=warnings,
        )
        track_color = _normalize_color(
            raw_ring.get("track_color"),
            None,
            allow_auto=True,
            field_name=f"{widget_id}.rings[{index}].track_color",
            warnings=warnings,
        )
        rings.append(
            RingConfig(
                id=ring_id,
                enabled=enabled,
                label=label,
                metric=metric,
                denominator=denominator,
                color=color,
                track_color=track_color,
            )
        )

    enabled_rings = tuple(ring for ring in rings if ring.enabled)
    if enabled_rings:
        return enabled_rings

    warnings.append(f"`{widget_id}` had no enabled usable rings. Using the default ring set.")
    return tuple(_default_ring_configs())


def _default_ring_configs() -> list[RingConfig]:
    return [
        RingConfig(
            id=str(ring["id"]),
            enabled=bool(ring["enabled"]),
            label=str(ring["label"]),
            metric=_normalize_query(ring["metric"], "default.metric", []),  # type: ignore[arg-type]
            denominator=_normalize_query(ring["denominator"], "default.denominator", []),  # type: ignore[arg-type]
            color=None,
            track_color=None,
        )
        for ring in DEFAULT_RINGS
    ]


def _normalize_query(
    raw_query: Any,
    field_name: str,
    warnings: list[str],
) -> QueryConfig | None:
    if raw_query is None:
        return None

    if isinstance(raw_query, str):
        metric_name = raw_query.strip()
        if is_builtin_metric_supported(metric_name):
            return QueryConfig(type="builtin", name=metric_name, search=None)
        if metric_name:
            return QueryConfig(type="search", name=None, search=metric_name)
        return None

    if not isinstance(raw_query, dict):
        warnings.append(f"`{field_name}` must be an object. Skipping it.")
        return None

    query_type = _normalize_choice(
        raw_query.get("type"),
        "builtin",
        VALID_QUERY_TYPES,
        field_name + ".type",
        warnings,
    )
    if query_type == "builtin":
        name = _normalize_text(raw_query.get("name"), "")
        if not name or not is_builtin_metric_supported(name):
            warnings.append(f"`{field_name}.name` must be one of the supported built-in metrics.")
            return None
        return QueryConfig(type=query_type, name=name, search=None)

    search = _normalize_text(raw_query.get("search"), "")
    if not search:
        warnings.append(f"`{field_name}.search` must be a non-empty Anki search string.")
        return None
    return QueryConfig(type=query_type, name=None, search=search)


def _default_ring_label(metric: QueryConfig, denominator: QueryConfig) -> str:
    if metric.type == "builtin" and metric.name:
        if metric.name == BUILTIN_YOUNG:
            return "Young/Learning"
        return builtin_metric_label(metric.name)
    if denominator.type == "builtin" and denominator.name:
        return f"{query_display_label(metric)} / {builtin_metric_label(denominator.name)}"
    return query_display_label(metric)


def _default_title_for_source(source: SourceConfig, index: int) -> str:
    if source.type == "tag" and source.tag:
        return source.tag.split("::")[-1]
    if source.type == "deck" and source.deck:
        return source.deck.split("::")[-1]
    if source.type == "search" and source.search:
        return f"Search {index + 1}"
    if source.type == "today":
        if source.scope == "deck" and source.deck:
            return source.deck.split("::")[-1] + " Today"
        return "Today's Progress"
    if source.type == "deck":
        return "Deck"
    return f"Widget {index + 1}"


def _normalize_widget_id(
    raw_id: Any,
    title: str,
    fallback: str,
    index: int,
    seen_ids: set[str],
) -> str:
    base = _normalize_text(raw_id, "") or title or fallback or f"widget-{index + 1}"
    slug = _normalize_slug(base, fallback=f"widget-{index + 1}")
    candidate = slug
    suffix = 2
    while candidate in seen_ids:
        candidate = f"{slug}-{suffix}"
        suffix += 1
    seen_ids.add(candidate)
    return candidate


def _normalize_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or fallback


def _normalize_screens(raw: Any, warnings: list[str]) -> list[str]:
    if raw is None:
        raw = DEFAULT_GLOBALS["show_on_screens"]
    if not isinstance(raw, list):
        warnings.append("`global.show_on_screens` must be a list. Using both deck browser and overview.")
        return list(DEFAULT_GLOBALS["show_on_screens"])

    screens = [
        screen
        for screen in (_normalize_text(value, "") for value in raw)
        if screen in VALID_SCREEN_NAMES
    ]
    if screens:
        return screens
    warnings.append("`global.show_on_screens` must include at least one supported screen. Using defaults.")
    return list(DEFAULT_GLOBALS["show_on_screens"])


def _normalize_choice(
    raw: Any,
    fallback: str,
    valid_values: set[str],
    field_name: str,
    warnings: list[str],
) -> str:
    value = _normalize_text(raw, fallback)
    if value in valid_values:
        return value
    warnings.append(f"`{field_name}` must be one of {sorted(valid_values)}. Using `{fallback}`.")
    return fallback


def _normalize_text(raw: Any, fallback: str) -> str:
    if isinstance(raw, str):
        value = raw.strip()
        if value:
            return value
    return fallback


def _normalize_bool(raw: Any, fallback: bool, field_name: str, warnings: list[str]) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return fallback
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    warnings.append(f"`{field_name}` must be a boolean. Using `{fallback}`.")
    return fallback


def _normalize_int(
    raw: Any,
    fallback: int,
    minimum: int,
    maximum: int,
    field_name: str,
    warnings: list[str],
) -> int:
    if raw is None:
        return fallback
    try:
        parsed = int(raw)
    except Exception:
        warnings.append(f"`{field_name}` must be an integer. Using `{fallback}`.")
        return fallback
    clamped = max(minimum, min(maximum, parsed))
    if clamped != parsed:
        warnings.append(f"`{field_name}` was clamped into the supported range {minimum}-{maximum}.")
    return clamped


def _normalize_float(
    raw: Any,
    fallback: float,
    minimum: float,
    maximum: float,
    field_name: str,
    warnings: list[str],
) -> float:
    if raw is None:
        return fallback
    try:
        parsed = float(raw)
    except Exception:
        warnings.append(f"`{field_name}` must be a number. Using `{fallback}`.")
        return fallback
    clamped = max(minimum, min(maximum, parsed))
    if clamped != parsed:
        warnings.append(f"`{field_name}` was clamped into the supported range {minimum}-{maximum}.")
    return clamped


def _normalize_color(
    raw: Any,
    fallback: str | None,
    *,
    allow_auto: bool,
    field_name: str,
    warnings: list[str],
) -> str | None:
    if raw is None:
        return fallback
    if isinstance(raw, str):
        value = raw.strip()
        if allow_auto and value.lower() == "auto":
            return None
        color = QColor(value)
        if color.isValid():
            return value
    warnings.append(
        f"`{field_name}` must be a valid Qt color string"
        + (" or `auto`." if allow_auto else ".")
        + f" Using `{fallback or 'auto'}`."
    )
    return fallback


def _max_ring_thickness(ring_size: int, ring_gap: int, ring_count: int) -> int:
    return max(4, (ring_size - max(0, ring_count - 1) * ring_gap) // max(2 * max(1, ring_count), 1))


def source_display_label(source: SourceConfig) -> str:
    if source.type == "tag":
        return source.tag or "No tag selected"
    if source.type == "deck":
        return source.deck or "No deck selected"
    if source.type == "search":
        return source.search or "Search"
    if source.scope == "deck" and source.deck:
        return f"Today's Progress · {source.deck}"
    return "Today's Progress · All Decks"


def query_display_label(query: QueryConfig) -> str:
    if query.type == "builtin" and query.name:
        if query.name == BUILTIN_YOUNG:
            return "Young/Learning"
        return builtin_metric_label(query.name)
    return "Custom Search"
