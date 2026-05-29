from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import pi
from urllib.parse import quote

from aqt import colors
from aqt.qt import QColor
from aqt.theme import theme_manager

from .config import AddonConfig, QueryConfig, WidgetConfig, query_display_label
from .metrics import (
    BUILTIN_ALL,
    BUILTIN_TODAY_ALL_COMPLETED,
    BUILTIN_TODAY_ALL_TOTAL,
    BUILTIN_TODAY_NEW_COMPLETED,
    BUILTIN_TODAY_NEW_TOTAL,
    BUILTIN_TODAY_REVIEW_COMPLETED,
    BUILTIN_TODAY_REVIEW_TOTAL,
    BUILTIN_UNSUSPENDED,
    default_palette_color,
)
from .stats import DashboardSnapshot, RingSnapshot, WidgetSnapshot

MESSAGE_PREFIX = "activity_rings_dashboard:"


@dataclass(frozen=True)
class WebTheme:
    night_mode: bool
    canvas: QColor
    card_bg: QColor
    card_bg_top: QColor
    card_border: QColor
    card_shadow: QColor
    text: QColor
    muted: QColor
    pill_bg: QColor
    pill_border: QColor
    pill_text: QColor
    subtle_track: QColor
    empty_bg: QColor
    empty_border: QColor
    empty_text: QColor
    center_hole: QColor
    center_glass: QColor


@dataclass(frozen=True)
class SizingProfile:
    card_min_width: int
    card_max_width: int
    min_height: int


@dataclass(frozen=True)
class CenterLayout:
    inset_px: float
    value_font_size: int
    caption_font_size: int
    title_font_size: int
    gap_px: int


def render_dashboard_html(
    config: AddonConfig,
    snapshot: DashboardSnapshot | None,
    *,
    surface: str,
    is_loading: bool = False,
) -> str:
    theme = current_web_theme(config)
    widgets = config.widgets

    if not widgets:
        if config.global_config.hide_when_no_widgets:
            return ""
        return _render_empty_state(theme, config, surface=surface)

    sizing = _sizing_profile(config)
    widgets_by_id = {widget_snapshot.widget_id: widget_snapshot for widget_snapshot in (snapshot.widgets if snapshot else tuple())}
    cards = "".join(
        _render_widget_slot(
            config=config,
            widget=widget,
            snapshot=widgets_by_id.get(widget.id),
            theme=theme,
            sizing=sizing,
            widget_index=index,
            surface=surface,
            is_loading=is_loading and snapshot is None,
        )
        for index, widget in enumerate(widgets)
    )
    if not cards:
        return ""

    return f"""
<style>
{_styles(theme, config, surface=surface)}
</style>
<section class="ard-shell ard-shell-{escape(surface)}" data-activity-rings-dashboard="1">
  <div class="ard-grid">
    {cards}
  </div>
</section>
"""


def preview_snapshot_for_widget(widget: WidgetConfig) -> WidgetSnapshot:
    if widget.source.type == "today":
        total_cards = 58
        review_total = 42
        new_total = 16
        unsuspended_total = total_cards
    else:
        total_cards = 4820
        review_total = 0
        new_total = 0
        unsuspended_total = 4180
    rings: list[RingSnapshot] = []
    for index, ring in enumerate(widget.rings):
        denominator_count = _preview_denominator_count(
            ring.denominator,
            total_cards,
            unsuspended_total,
            review_total,
            new_total,
        )
        percent = _preview_percent_for_query(ring.metric, index)
        numerator_count = int(round(denominator_count * (percent / 100.0)))
        rings.append(
            RingSnapshot(
                ring_id=ring.id,
                label=ring.label,
                color=ring.color,
                track_color=ring.track_color,
                numerator_count=numerator_count,
                denominator_count=denominator_count,
                percent=percent,
                metric_label=query_display_label(ring.metric),
                denominator_label=query_display_label(ring.denominator),
                tooltip=(
                    f"{ring.label}: {numerator_count:,} {query_display_label(ring.metric).lower()} cards out of "
                    f"{denominator_count:,} {query_display_label(ring.denominator).lower()} cards."
                ),
                browser_query=None,
                error=None,
            )
        )

    center_value, center_caption = _center_display(widget, tuple(rings), total_cards, "ok", None)
    return WidgetSnapshot(
        widget_id=widget.id,
        title=widget.title,
        subtitle=None,
        total_cards=total_cards,
        rings=tuple(rings),
        state="ok",
        status_message=None,
        source_query=None,
        center_value=center_value,
        center_caption=center_caption,
    )


def current_web_theme(config: AddonConfig) -> WebTheme:
    forced = config.global_config.theme
    if forced == "dark":
        night_mode = True
        canvas = QColor("#111214")
        base = QColor("#1b1d21")
        elevated = QColor("#24262b")
        border = QColor("#3a3f47")
        text = QColor("#f6f7fb")
        muted = QColor("#b2b7c3")
    elif forced == "light":
        night_mode = False
        canvas = QColor("#f4f6fa")
        base = QColor("#ffffff")
        elevated = QColor("#fbfcfe")
        border = QColor("#d8dce5")
        text = QColor("#101114")
        muted = QColor("#5d6472")
    else:
        night_mode = bool(theme_manager.night_mode)
        canvas = theme_manager.qcolor(colors.CANVAS)
        base = theme_manager.qcolor(colors.CANVAS_ELEVATED)
        elevated = _mix(base, QColor("#ffffff" if night_mode else "#fbfdff"), 0.06 if night_mode else 0.22)
        border = theme_manager.qcolor(colors.BORDER_SUBTLE)
        text = theme_manager.qcolor(colors.FG)
        muted = theme_manager.qcolor(colors.FG_SUBTLE)

    card_bg = _mix(elevated, canvas, 0.16 if night_mode else 0.1)
    card_bg_top = _mix(card_bg, QColor("#ffffff" if night_mode else "#fafdff"), 0.08 if night_mode else 0.28)
    card_border = _with_alpha(border, 0.88 if night_mode else 0.9)
    card_shadow = _with_alpha(QColor("#000000"), 0.34 if night_mode else 0.12)
    pill_bg = _with_alpha(QColor("#ffffff" if night_mode else "#0f172a"), 0.08 if night_mode else 0.05)
    pill_border = _with_alpha(QColor("#ffffff" if night_mode else "#111827"), 0.1 if night_mode else 0.08)
    pill_text = _with_alpha(text, 0.92 if night_mode else 0.84)
    subtle_track = _mix(card_bg, QColor("#ffffff" if night_mode else "#111827"), 0.12 if night_mode else 0.08)
    empty_bg = _with_alpha(base, 0.78 if night_mode else 0.92)
    empty_border = _with_alpha(border, 0.9 if night_mode else 0.8)
    empty_text = _with_alpha(muted, 0.98)
    center_hole = _mix(card_bg, QColor("#090a0d" if night_mode else "#ffffff"), 0.32 if night_mode else 0.48)
    center_glass = _with_alpha(QColor("#ffffff"), 0.08 if night_mode else 0.55)

    return WebTheme(
        night_mode=night_mode,
        canvas=canvas,
        card_bg=card_bg,
        card_bg_top=card_bg_top,
        card_border=card_border,
        card_shadow=card_shadow,
        text=text,
        muted=muted,
        pill_bg=pill_bg,
        pill_border=pill_border,
        pill_text=pill_text,
        subtle_track=subtle_track,
        empty_bg=empty_bg,
        empty_border=empty_border,
        empty_text=empty_text,
        center_hole=center_hole,
        center_glass=center_glass,
    )


def _styles(theme: WebTheme, config: AddonConfig, *, surface: str) -> str:
    margin_top = 10 if surface == "deckBrowser" else 14
    if surface == "preview":
        margin_top = 0

    return f"""
.ard-shell {{
  margin: {margin_top}px {config.global_config.panel_margin}px 16px;
  background: transparent;
}}
.ard-shell-preview {{
  margin: 0;
}}
.ard-grid {{
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  justify-content: center;
  gap: {config.global_config.panel_spacing}px;
}}
.ard-slot {{
  flex: 0 1 var(--ard-card-min);
  min-width: min(100%, var(--ard-card-min));
  max-width: var(--ard-card-max);
  display: flex;
  flex-direction: column;
  gap: 8px;
}}
.ard-title-above {{
  margin: 0 4px;
  color: {_rgba(_with_alpha(theme.text, 0.96))};
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}}
.ard-card {{
  position: relative;
  overflow: hidden;
  min-height: var(--ard-min-height);
  border-radius: 24px;
  border: var(--ard-border-width) solid var(--ard-border);
  background:
    linear-gradient(180deg, var(--ard-card-top) 0%, var(--ard-card-bg) 100%);
  box-shadow: var(--ard-shadow);
  backdrop-filter: blur(20px) saturate(1.08);
  -webkit-backdrop-filter: blur(20px) saturate(1.08);
}}
.ard-card::before {{
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 22% 16%, rgba(255,255,255,{0.12 if theme.night_mode else 0.9}), transparent 38%),
    radial-gradient(circle at 100% 0%, rgba(255,255,255,{0.04 if theme.night_mode else 0.42}), transparent 34%);
  pointer-events: none;
}}
.ard-card-loading::after {{
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,{0.06 if theme.night_mode else 0.5}), transparent);
  transform: translateX(-100%);
  animation: ard-sheen 1.7s ease-in-out infinite;
  pointer-events: none;
}}
@keyframes ard-sheen {{
  0% {{ transform: translateX(-100%); }}
  100% {{ transform: translateX(100%); }}
}}
.ard-card-overlay {{
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: inherit;
}}
.ard-card-overlay-command {{
  z-index: 5;
}}
.ard-card-body {{
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: var(--ard-padding);
  min-height: 100%;
}}
.ard-layout-compact .ard-card-body {{
  justify-content: flex-start;
}}
.ard-layout-compact .ard-main {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}}
.ard-layout-wide .ard-main {{
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  align-items: center;
  gap: 18px;
}}
.ard-header {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}}
.ard-header-meta {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}}
.ard-header-copy {{
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}}
.ard-title {{
  color: {_rgba(theme.text)};
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.15;
}}
.ard-subtitle {{
  color: {_rgba(_with_alpha(theme.muted, 0.98))};
  font-size: 12px;
  font-weight: 600;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}}
.ard-status {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 5px 10px;
  border-radius: 999px;
  background: {_rgba(theme.pill_bg)};
  border: 1px solid {_rgba(theme.pill_border)};
  color: {_rgba(theme.pill_text)};
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}}
.ard-status-count {{
  color: {_rgba(theme.text)};
}}
.ard-ring-panel {{
  position: relative;
  width: var(--ard-ring-size);
  min-width: var(--ard-ring-size);
  height: var(--ard-ring-size);
  display: grid;
  place-items: center;
  margin: 0 auto;
}}
.ard-layout-wide .ard-ring-panel {{
  margin: 0;
}}
.ard-ring-hit {{
  position: relative;
  z-index: 3;
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 999px;
}}
.ard-ring-hit svg {{
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}}
.ard-center {{
  pointer-events: none;
  position: absolute;
  inset: var(--ard-center-inset);
  z-index: 4;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--ard-center-gap);
  text-align: center;
}}
.ard-center-title {{
  color: {_rgba(_with_alpha(theme.muted, 0.92))};
  font-size: var(--ard-center-title-size);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: 0.01em;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.ard-center-value {{
  color: {_rgba(theme.text)};
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
  font-size: clamp(18px, calc(var(--ard-center-value-size) * 1px), 42px);
  font-weight: 760;
  line-height: 0.95;
  letter-spacing: -0.03em;
}}
.ard-center-caption {{
  color: {_rgba(_with_alpha(theme.muted, 0.96))};
  font-size: var(--ard-center-caption-size);
  font-weight: 700;
  line-height: 1.12;
}}
.ard-legend {{
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}}
.ard-metric-row,
.ard-metric-static {{
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 16px;
  background: rgba(255,255,255,{0.03 if theme.night_mode else 0.5});
  border: 1px solid rgba(255,255,255,{0.04 if theme.night_mode else 0.6});
}}
.ard-metric-row {{
  position: relative;
  z-index: 3;
}}
.ard-metric-row:hover {{
  background: rgba(255,255,255,{0.05 if theme.night_mode else 0.72});
}}
.ard-metric-dot {{
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--ard-ring-color);
  box-shadow: 0 0 0 4px rgba(255,255,255,{0.02 if theme.night_mode else 0.3});
}}
.ard-metric-copy {{
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}}
.ard-metric-label {{
  color: {_rgba(theme.text)};
  font-size: 13px;
  font-weight: 700;
  line-height: 1.1;
}}
.ard-metric-detail {{
  color: {_rgba(_with_alpha(theme.muted, 0.98))};
  font-size: 12px;
  font-weight: 600;
  line-height: 1.1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.ard-metric-value {{
  color: var(--ard-ring-color);
  font-size: 15px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
}}
.ard-footer {{
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}}
.ard-chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: {_rgba(theme.pill_bg)};
  border: 1px solid {_rgba(theme.pill_border)};
  color: {_rgba(theme.pill_text)};
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}}
.ard-empty {{
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  border-radius: 22px;
  border: 1px solid {_rgba(theme.empty_border)};
  background: {_rgba(theme.empty_bg)};
  padding: 18px;
  color: {_rgba(theme.empty_text)};
  box-shadow: 0 16px 30px {_rgba(_with_alpha(theme.card_shadow, 0.8 if theme.night_mode else 0.55))};
}}
.ard-empty-copy {{
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}}
.ard-empty-button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 9px 13px;
  border-radius: 999px;
  background: {_rgba(_with_alpha(theme.text, 0.08 if theme.night_mode else 0.07))};
  border: 1px solid {_rgba(_with_alpha(theme.text, 0.1 if theme.night_mode else 0.06))};
  color: {_rgba(theme.text)};
  font-size: 12px;
  font-weight: 700;
}}
@media (max-width: 780px) {{
  .ard-layout-wide .ard-main {{
    grid-template-columns: 1fr;
    gap: 14px;
  }}
  .ard-layout-wide .ard-ring-panel {{
    margin: 0 auto;
  }}
}}
@media (max-width: 520px) {{
  .ard-slot {{
    max-width: 100%;
  }}
}}
"""


def _render_empty_state(theme: WebTheme, config: AddonConfig, *, surface: str) -> str:
    return f"""
<style>
{_styles(theme, config, surface=surface)}
</style>
<section class="ard-shell ard-shell-{escape(surface)}" data-activity-rings-dashboard="1">
  <div class="ard-empty">
    <div class="ard-empty-copy">No activity ring widgets are configured yet. Open the visual editor to add one.</div>
    {_bridge_button("Open Activity Rings", "settings", class_name="ard-empty-button")}
  </div>
</section>
"""


def _render_widget_slot(
    *,
    config: AddonConfig,
    widget: WidgetConfig,
    snapshot: WidgetSnapshot | None,
    theme: WebTheme,
    sizing: SizingProfile,
    widget_index: int,
    surface: str,
    is_loading: bool,
) -> str:
    resolved_snapshot = snapshot or (
        preview_snapshot_for_widget(widget)
        if surface == "preview"
        else _empty_widget_snapshot(widget, loading=is_loading)
    )
    state = "loading" if is_loading and snapshot is None else resolved_snapshot.state
    source_tooltip = escape(resolved_snapshot.subtitle or resolved_snapshot.title or widget.title)
    title_above = ""
    if widget.layout.title_position == "above" and widget.title:
        title_above = f'<div class="ard-title-above">{escape(widget.title)}</div>'

    min_height = sizing.min_height if config.global_config.match_widget_sizes else _card_min_height(widget)
    ring_size = _resolved_ring_size(widget)
    background = _resolved_card_background(widget, theme)
    border = _resolved_card_border(widget, theme, background)
    border_width = _resolved_card_border_width(widget)
    shadow = _resolved_card_shadow(widget, theme)
    card_min_width = sizing.card_min_width if config.global_config.match_widget_sizes else widget.layout.card_min_width
    card_max_width = sizing.card_max_width if config.global_config.match_widget_sizes else widget.layout.card_max_width
    card_classes = ["ard-card", f"ard-layout-{widget.layout.mode}", f"ard-state-{state}"]
    if is_loading:
        card_classes.append("ard-card-loading")

    return f"""
<div
  class="ard-slot"
  style="--ard-card-min:{card_min_width}px; --ard-card-max:{card_max_width}px;"
>
  {title_above}
  <article
    class="{' '.join(card_classes)}"
    title="{source_tooltip}"
    style="
      --ard-padding:{widget.layout.card_padding}px;
      --ard-ring-size:{ring_size}px;
      --ard-center-value-size:{widget.layout.center_value_font_size};
      --ard-min-height:{min_height}px;
      --ard-card-bg:{_rgba(background)};
      --ard-card-top:{_rgba(_mix(background, theme.card_bg_top, 0.45))};
      --ard-border-width:{border_width}px;
      --ard-border:{_rgba(border)};
      --ard-shadow:{shadow};
    "
  >
    {_card_overlay(widget, resolved_snapshot)}
    {_render_widget_card(config, widget, resolved_snapshot, theme, widget_index=widget_index)}
  </article>
</div>
"""


def _render_widget_card(
    config: AddonConfig,
    widget: WidgetConfig,
    snapshot: WidgetSnapshot,
    theme: WebTheme,
    *,
    widget_index: int,
) -> str:
    header_html = _render_header(widget, snapshot)
    ring_html = _render_ring_panel(config, widget, snapshot, theme, widget_index=widget_index)
    legend_html = _render_legend(config, widget, snapshot)
    footer_html = _render_footer(widget, snapshot)

    return f"""
<div class="ard-card-body">
  {header_html}
  <div class="ard-main">
    {ring_html}
    {legend_html}
  </div>
  {footer_html}
</div>
"""


def _render_header(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str:
    show_title = widget.layout.title_position == "inside" and bool(snapshot.title)
    show_subtitle = bool(snapshot.subtitle)
    show_status = bool(snapshot.status_message)
    show_total_cards = widget.layout.show_total_cards
    if not (show_title or show_subtitle or show_status or show_total_cards):
        return ""

    title_html = f'<div class="ard-title">{escape(snapshot.title)}</div>' if show_title else ""
    subtitle_html = (
        f'<div class="ard-subtitle" title="{escape(snapshot.subtitle)}">{escape(snapshot.subtitle)}</div>'
        if show_subtitle
        else ""
    )
    meta_parts: list[str] = []
    if show_total_cards:
        label = "cards today" if widget.source.type == "today" else "cards"
        meta_parts.append(f'<div class="ard-status ard-status-count">{snapshot.total_cards:,} {label}</div>')
    if show_status:
        meta_parts.append(f'<div class="ard-status">{escape(snapshot.status_message)}</div>')
    meta_html = f'<div class="ard-header-meta">{"".join(meta_parts)}</div>' if meta_parts else ""

    return f"""
<div class="ard-header">
  <div class="ard-header-copy">
    {title_html}
    {subtitle_html}
  </div>
  {meta_html}
</div>
"""


def _render_ring_panel(
    config: AddonConfig,
    widget: WidgetConfig,
    snapshot: WidgetSnapshot,
    theme: WebTheme,
    *,
    widget_index: int,
) -> str:
    ring_query = _primary_ring_query(widget, snapshot)
    svg = _render_rings_svg(config, widget, snapshot, theme, widget_index=widget_index)
    center_html = _render_center(widget, snapshot)
    content = f"{svg}{center_html}"
    if ring_query:
        return f'<div class="ard-ring-panel">{_bridge_anchor(content, ring_query, "ard-ring-hit", "Click to open matching cards")}</div>'
    return f'<div class="ard-ring-panel"><div class="ard-ring-hit">{content}</div></div>'


def _render_center(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str:
    if widget.layout.center_label_mode == "none":
        return ""

    center_layout = _center_layout(widget, snapshot)
    title_line = ""
    if widget.layout.title_position == "center" and snapshot.title:
        title_line = f'<div class="ard-center-title">{escape(snapshot.title)}</div>'

    value = escape(snapshot.center_value) if snapshot.center_value else ""
    caption = escape(snapshot.center_caption) if snapshot.center_caption else ""
    caption_html = f'<div class="ard-center-caption">{caption}</div>' if caption else ""
    return f"""
<div
  class="ard-center"
  style="
    --ard-center-inset:{center_layout.inset_px:.1f}px;
    --ard-center-gap:{center_layout.gap_px}px;
    --ard-center-title-size:{center_layout.title_font_size}px;
    --ard-center-caption-size:{center_layout.caption_font_size}px;
  "
>
  {title_line}
  <div class="ard-center-value" style="font-size:{center_layout.value_font_size}px;">{value}</div>
  {caption_html}
</div>
"""


def _render_legend(config: AddonConfig, widget: WidgetConfig, snapshot: WidgetSnapshot) -> str:
    if not widget.layout.show_legend:
        return ""

    rows = "".join(
        _render_metric_row(config, widget, ring, snapshot.state)
        for ring in _display_rings(widget, snapshot)
    )
    return f'<div class="ard-legend">{rows}</div>'


def _render_metric_row(
    config: AddonConfig,
    widget: WidgetConfig,
    ring: RingSnapshot,
    widget_state: str,
) -> str:
    color = _resolved_ring_color(config, ring)
    detail = _metric_detail(widget, ring)
    percent_html = (
        f'<div class="ard-metric-value">{escape(_percent_text(ring))}</div>'
        if widget.layout.show_percentages
        else '<div class="ard-metric-value"></div>'
    )
    detail_html = f'<div class="ard-metric-detail">{escape(detail)}</div>' if detail else ""
    inner_html = f"""
<span class="ard-metric-dot"></span>
<span class="ard-metric-copy">
  <span class="ard-metric-label">{escape(ring.label)}</span>
  {detail_html}
</span>
{percent_html}
"""

    tooltip = ring.tooltip or ring.error or ""
    title_attr = f' title="{escape(tooltip)}"' if tooltip else ""
    style_attr = f' style="--ard-ring-color:{escape(color)};"'

    if ring.browser_query and widget_state == "ok":
        return _bridge_anchor(
            inner_html,
            ring.browser_query,
            "ard-metric-row",
            tooltip or "Click to open matching cards",
            extra_attrs=style_attr,
        )
    return f'<div class="ard-metric-static"{title_attr}{style_attr}>{inner_html}</div>'


def _render_footer(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str:
    chips: list[str] = []
    if widget.layout.title_position in {"above", "center", "hidden"} and snapshot.subtitle:
        chips.append(
            f'<div class="ard-chip" title="{escape(snapshot.subtitle)}">{escape(snapshot.subtitle)}</div>'
        )
    if not chips:
        return ""
    return f'<div class="ard-footer">{"".join(chips)}</div>'


def _render_rings_svg(
    config: AddonConfig,
    widget: WidgetConfig,
    snapshot: WidgetSnapshot,
    theme: WebTheme,
    *,
    widget_index: int,
) -> str:
    rings = _display_rings(widget, snapshot)
    size = _resolved_ring_size(widget)
    thickness = widget.layout.ring_thickness
    gap = widget.layout.ring_gap
    half = size / 2.0
    outer_radius = max((size / 2.0) - thickness / 2.0 - 6.0, 26.0)
    hole_radius = max(outer_radius - (len(rings) * thickness) - (max(0, len(rings) - 1) * gap) + 4.0, size * 0.16)
    defs: list[str] = []
    shapes: list[str] = []

    for ring_index, ring in enumerate(rings):
        radius = outer_radius - (ring_index * (thickness + gap))
        if radius <= thickness / 2.0 + 4.0:
            continue

        color = QColor(_resolved_ring_color(config, ring))
        track_color = _resolved_track_color(widget, ring, theme, color)
        dash, gap_dash = _dash_pattern(radius, thickness, ring.percent)
        gradient_id = _safe_id(f"ard-grad-{widget.id}-{widget_index}-{ring_index}")
        glow_id = _safe_id(f"ard-glow-{widget.id}-{widget_index}-{ring_index}")

        defs.append(
            f"""
<linearGradient id="{gradient_id}" x1="0%" y1="10%" x2="100%" y2="100%">
  <stop offset="0%" stop-color="{_rgba(_mix(color, QColor('#ffffff'), 0.22))}" />
  <stop offset="55%" stop-color="{_rgba(color)}" />
  <stop offset="100%" stop-color="{_rgba(_mix(color, QColor('#000000'), 0.18))}" />
</linearGradient>
<filter id="{glow_id}" x="-45%" y="-45%" width="190%" height="190%">
  <feDropShadow
    dx="0"
    dy="{1 if theme.night_mode else 0.8}"
    stdDeviation="{2.4 if widget.style.use_glow else 0.01}"
    flood-color="{_rgba(_with_alpha(color, 0.24 if widget.style.use_glow else 0.0))}"
  />
</filter>
"""
        )

        shapes.append(
            f"""
<circle
  cx="{half:.2f}"
  cy="{half:.2f}"
  r="{radius:.2f}"
  fill="none"
  stroke="{_rgba(track_color)}"
  stroke-width="{thickness}"
  stroke-linecap="butt"
/>
<circle
  cx="{half:.2f}"
  cy="{half:.2f}"
  r="{radius:.2f}"
  fill="none"
  stroke="url(#{gradient_id})"
  stroke-width="{thickness}"
  stroke-linecap="round"
  stroke-dasharray="{dash:.3f} {gap_dash:.3f}"
  transform="rotate(-90 {half:.2f} {half:.2f})"
  filter="url(#{glow_id})"
/>
"""
        )

    return f"""
<svg viewBox="0 0 {size} {size}" role="img" aria-label="{escape(snapshot.title or widget.title)}">
  <defs>{''.join(defs)}</defs>
  <circle cx="{half:.2f}" cy="{half:.2f}" r="{outer_radius + thickness / 2.0:.2f}" fill="rgba(255,255,255,{0.02 if theme.night_mode else 0.35})" />
  {''.join(shapes)}
  <circle cx="{half:.2f}" cy="{half:.2f}" r="{hole_radius:.2f}" fill="{_rgba(theme.center_hole)}" />
  <circle cx="{half:.2f}" cy="{half:.2f}" r="{max(hole_radius - 1.5, 0):.2f}" fill="none" stroke="{_rgba(theme.center_glass)}" stroke-width="1.6" />
</svg>
"""


def _display_rings(widget: WidgetConfig, snapshot: WidgetSnapshot) -> tuple[RingSnapshot, ...]:
    if snapshot.rings:
        return snapshot.rings

    fallback: list[RingSnapshot] = []
    for ring in widget.rings:
        fallback.append(
            RingSnapshot(
                ring_id=ring.id,
                label=ring.label,
                color=ring.color,
                track_color=ring.track_color,
                numerator_count=0,
                denominator_count=0,
                percent=0.0,
                metric_label=query_display_label(ring.metric),
                denominator_label=query_display_label(ring.denominator),
                tooltip="",
                browser_query=None,
                error=None,
            )
        )
    return tuple(fallback)


def _empty_widget_snapshot(widget: WidgetConfig, *, loading: bool) -> WidgetSnapshot:
    rings = _display_rings(
        widget,
        WidgetSnapshot(
            widget_id=widget.id,
            title=widget.title,
            subtitle=None,
            total_cards=0,
            rings=tuple(),
            state="loading" if loading else "empty",
            status_message="Loading..." if loading else None,
            source_query=None,
            center_value="…"
            if loading and widget.layout.center_label_mode != "none"
            else "0"
            if widget.layout.center_label_mode != "none"
            else "",
            center_caption="Loading" if loading else "No cards",
        ),
    )
    return WidgetSnapshot(
        widget_id=widget.id,
        title=widget.title,
        subtitle=None,
        total_cards=0,
        rings=rings,
        state="loading" if loading else "empty",
        status_message="Loading..." if loading else None,
        source_query=None,
        center_value="…" if loading and widget.layout.center_label_mode != "none" else "0",
        center_caption="Loading" if loading else "No cards",
    )


def _sizing_profile(config: AddonConfig) -> SizingProfile:
    widgets = config.widgets or tuple()
    if not widgets:
        return SizingProfile(card_min_width=290, card_max_width=390, min_height=260)

    if not config.global_config.match_widget_sizes:
        first = widgets[0]
        return SizingProfile(
            card_min_width=first.layout.card_min_width,
            card_max_width=first.layout.card_max_width,
            min_height=_card_min_height(first),
        )

    return SizingProfile(
        card_min_width=max(widget.layout.card_min_width for widget in widgets),
        card_max_width=max(widget.layout.card_max_width for widget in widgets),
        min_height=max(_card_min_height(widget) for widget in widgets),
    )


def _center_layout(widget: WidgetConfig, snapshot: WidgetSnapshot) -> CenterLayout:
    size, _, hole_radius = _ring_geometry(widget, snapshot)
    safe_margin = max(4.0, size * 0.035)
    available_diameter = max(20.0, (hole_radius * 2.0) - (safe_margin * 2.0))
    inset_px = max((size - available_diameter) / 2.0, 0.0)

    value_text = snapshot.center_value or ""
    caption_text = snapshot.center_caption or ""
    show_title = widget.layout.title_position == "center" and bool(snapshot.title)
    show_caption = bool(caption_text)

    title_font_size = max(8, min(11, int(available_diameter * 0.17)))
    gap_px = 1 if available_diameter < 52 else 2
    reserved_title = title_font_size + gap_px if show_title else 0
    reserved_caption = gap_px if show_caption else 0
    remaining_height = max(14.0, available_diameter - reserved_title - reserved_caption)

    if show_caption:
        value_height_limit = remaining_height * 0.62
        caption_height_limit = remaining_height * 0.18
    else:
        value_height_limit = remaining_height * 0.76
        caption_height_limit = remaining_height * 0.18

    value_font_size = widget.layout.center_value_font_size
    if widget.layout.center_value_auto_fit:
        value_font_size = _fit_text_size(
            value_text,
            max_size=widget.layout.center_value_font_size,
            min_size=12,
            width_limit=available_diameter * 0.9,
            height_limit=value_height_limit,
            kind="value",
        )

    caption_font_size = widget.layout.center_caption_font_size
    if widget.layout.center_caption_auto_fit:
        caption_font_size = _fit_text_size(
            caption_text,
            max_size=widget.layout.center_caption_font_size,
            min_size=8,
            width_limit=available_diameter * 0.88,
            height_limit=caption_height_limit,
            kind="caption",
        )

    return CenterLayout(
        inset_px=inset_px,
        value_font_size=value_font_size,
        caption_font_size=caption_font_size,
        title_font_size=title_font_size,
        gap_px=gap_px,
    )


def _ring_geometry(widget: WidgetConfig, snapshot: WidgetSnapshot) -> tuple[int, float, float]:
    rings = _display_rings(widget, snapshot)
    size = _resolved_ring_size(widget)
    thickness = widget.layout.ring_thickness
    gap = widget.layout.ring_gap
    outer_radius = max((size / 2.0) - thickness / 2.0 - 6.0, 26.0)
    hole_radius = max(
        outer_radius - (len(rings) * thickness) - (max(0, len(rings) - 1) * gap) + 4.0,
        size * 0.16,
    )
    return size, outer_radius, hole_radius


def _fit_text_size(
    text: str,
    *,
    max_size: int,
    min_size: int,
    width_limit: float,
    height_limit: float,
    kind: str,
) -> int:
    if not text:
        return max(min_size, min(max_size, int(height_limit)))
    units = _text_units(text, kind=kind)
    width_fit = width_limit / max(units, 1.0)
    height_fit = height_limit
    fitted = int(min(max_size, width_fit, height_fit))
    return max(min_size, fitted)


def _text_units(text: str, *, kind: str) -> float:
    total = 0.0
    for char in text:
        if char in {" ", "\t"}:
            total += 0.28 if kind == "caption" else 0.22
        elif char.isdigit():
            total += 0.58 if kind == "value" else 0.52
        elif char.isalpha():
            total += 0.54 if kind == "caption" else 0.62
        elif char in {".", ",", ":", ";", "'", '"'}:
            total += 0.22
        elif char in {"%", "!", "?", "+", "-"}:
            total += 0.4
        else:
            total += 0.48
    return max(total, 1.0)


def _resolved_ring_size(widget: WidgetConfig) -> int:
    ring_size = widget.layout.ring_size
    if widget.layout.mode == "wide":
        ring_size = min(ring_size + 18, 296)
    return max(150, min(ring_size, 296))


def _card_min_height(widget: WidgetConfig) -> int:
    ring_size = _resolved_ring_size(widget)
    if widget.layout.mode == "compact":
        return max(int(ring_size * widget.layout.card_aspect_ratio) + 54, ring_size + 120)
    return max(ring_size + 36, 252)


def _resolved_card_background(widget: WidgetConfig, theme: WebTheme) -> QColor:
    base = QColor(widget.style.background_color) if widget.style.background_color else QColor(theme.card_bg)
    if not base.isValid():
        base = QColor(theme.card_bg)
    base.setAlphaF(max(0.02, min(1.0, widget.style.card_opacity)))
    return base


def _resolved_card_border(widget: WidgetConfig, theme: WebTheme, background: QColor) -> QColor:
    if widget.style.border_color:
        border = QColor(widget.style.border_color)
        if border.isValid():
            return border
    transparent = QColor(background)
    transparent.setAlpha(0)
    return transparent


def _resolved_card_border_width(widget: WidgetConfig) -> int:
    if widget.style.border_color:
        border = QColor(widget.style.border_color)
        if border.isValid():
            return 1
    return 0


def _resolved_card_shadow(widget: WidgetConfig, theme: WebTheme) -> str:
    if not widget.style.shadow_enabled:
        return "none"
    return (
        f"0 16px 34px {_rgba(theme.card_shadow)}, "
        f"inset 0 1px 0 rgba(255,255,255,{0.06 if theme.night_mode else 0.8})"
    )


def _resolved_ring_color(config: AddonConfig, ring: RingSnapshot) -> str:
    if ring.color:
        color = QColor(ring.color)
        if color.isValid():
            return color.name()
    metric_name = _query_metric_name(ring.metric_label)
    if metric_name:
        return default_palette_color(metric_name, config.global_config.palette)
    return "#8e8e93"


def _resolved_track_color(
    widget: WidgetConfig,
    ring: RingSnapshot,
    theme: WebTheme,
    active_color: QColor,
) -> QColor:
    for candidate in (ring.track_color, widget.style.track_color):
        if candidate:
            color = QColor(candidate)
            if color.isValid():
                return color
    mix_ratio = 0.18 if theme.night_mode else 0.12
    track = _mix(theme.subtle_track, active_color, mix_ratio)
    track.setAlphaF(0.34 if theme.night_mode else 0.2)
    return track


def _metric_detail(widget: WidgetConfig, ring: RingSnapshot) -> str:
    if ring.error:
        return ring.error
    parts: list[str] = []
    if widget.layout.show_counts:
        parts.append(f"{ring.numerator_count:,} / {ring.denominator_count:,}")
    if not widget.layout.show_counts and widget.layout.show_percentages:
        parts.append(f"{ring.metric_label} of {ring.denominator_label}")
    return " · ".join(parts)


def _percent_text(ring: RingSnapshot) -> str:
    return f"{ring.percent:.0f}%"


def _preview_percent_for_query(query: QueryConfig, index: int) -> float:
    if query.type == "builtin":
        metric_name = query.name or ""
        mapping = {
            "mature": 47.0,
            "young": 66.0,
            "unsuspended": 86.0,
            "due": 18.0,
            "reviewed": 58.0,
            "learning": 22.0,
            "new": 34.0,
            "review": 61.0,
            "buried": 4.0,
            "suspended": 14.0,
            "leech": 3.0,
            "non_new": 64.0,
            "all": 100.0,
            "today_review_completed": 64.0,
            "today_review_total": 100.0,
            "today_new_completed": 38.0,
            "today_new_total": 100.0,
            "today_all_completed": 57.0,
            "today_all_total": 100.0,
        }
        return mapping.get(metric_name, 52.0)
    return (62.0, 38.0, 74.0, 57.0)[index % 4]


def _preview_denominator_count(
    query: QueryConfig,
    total_cards: int,
    unsuspended_total: int,
    review_total: int,
    new_total: int,
) -> int:
    if query.type == "builtin" and query.name == BUILTIN_UNSUSPENDED:
        return unsuspended_total
    if query.type == "builtin" and query.name == BUILTIN_ALL:
        return total_cards
    if query.type == "builtin" and query.name in {BUILTIN_TODAY_REVIEW_COMPLETED, BUILTIN_TODAY_REVIEW_TOTAL}:
        return review_total
    if query.type == "builtin" and query.name in {BUILTIN_TODAY_NEW_COMPLETED, BUILTIN_TODAY_NEW_TOTAL}:
        return new_total
    if query.type == "builtin" and query.name in {BUILTIN_TODAY_ALL_COMPLETED, BUILTIN_TODAY_ALL_TOTAL}:
        return total_cards
    return unsuspended_total


def _center_display(
    widget: WidgetConfig,
    rings: tuple[RingSnapshot, ...],
    total_cards: int,
    state: str,
    status_message: str | None,
) -> tuple[str, str]:
    if widget.layout.center_label_mode == "none":
        return "", ""
    if state in {"missing", "error"}:
        return "!", status_message or "Unavailable"
    if state == "empty":
        return "0", "No cards"

    primary = _primary_ring(widget, rings)
    custom_caption = (widget.layout.center_label_text or "").strip()
    if widget.layout.center_label_mode == "card_count":
        return f"{total_cards:,}", custom_caption or "cards"
    if widget.layout.center_label_mode == "title":
        return widget.title, custom_caption
    if primary is None:
        return f"{total_cards:,}", custom_caption or "cards"
    if widget.layout.center_label_mode == "primary_metric":
        return f"{primary.numerator_count:,}", custom_caption or primary.label
    return f"{primary.percent:.0f}%", custom_caption or primary.label


def _primary_ring(widget: WidgetConfig, rings: tuple[RingSnapshot, ...]) -> RingSnapshot | None:
    if not rings:
        return None
    if widget.layout.primary_ring_id:
        for ring in rings:
            if ring.ring_id == widget.layout.primary_ring_id:
                return ring
    return rings[0]


def _primary_ring_query(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str | None:
    if widget.layout.ring_click_action == "none":
        return None
    primary = _primary_ring(widget, snapshot.rings)
    if primary and primary.browser_query:
        return primary.browser_query
    return snapshot.source_query


def _card_overlay(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str:
    command = _widget_click_command(widget)
    if command:
        return _bridge_command_anchor("", command, "ard-card-overlay ard-card-overlay-command", "Click to choose a tag or deck")
    query = _widget_click_query(widget, snapshot)
    if not query:
        return ""
    return _bridge_anchor("", query, "ard-card-overlay", "Click to open matching cards")


def _widget_click_command(widget: WidgetConfig) -> str | None:
    if widget.source.type == "tag" and not (widget.source.tag or "").strip():
        return f"picktag:{widget.id}"
    if widget.source.type == "deck" and not (widget.source.deck or "").strip():
        return f"picktag:{widget.id}"
    return None


def _widget_click_query(widget: WidgetConfig, snapshot: WidgetSnapshot) -> str | None:
    if widget.layout.click_action == "none":
        return None
    if widget.layout.click_action == "source":
        return snapshot.source_query
    primary = _primary_ring(widget, snapshot.rings)
    if primary and primary.browser_query:
        return primary.browser_query
    return snapshot.source_query


def _bridge_button(label: str, command: str, *, class_name: str) -> str:
    payload = escape(MESSAGE_PREFIX + command)
    return (
        f'<a class="{class_name}" href="#" onclick="pycmd(\'{payload}\'); return false;">'
        f"{escape(label)}</a>"
    )


def _bridge_command_anchor(
    inner_html: str,
    command: str,
    class_name: str,
    tooltip: str,
    *,
    extra_attrs: str = "",
) -> str:
    payload = escape(MESSAGE_PREFIX + command)
    title_attr = f' title="{escape(tooltip)}"' if tooltip else ""
    return (
        f'<a class="{class_name}" href="#" onclick="pycmd(\'{payload}\'); return false;"'
        f"{title_attr}{extra_attrs}>{inner_html}</a>"
    )


def _bridge_anchor(
    inner_html: str,
    query: str,
    class_name: str,
    tooltip: str,
    *,
    extra_attrs: str = "",
) -> str:
    payload = escape(MESSAGE_PREFIX + "search:" + quote(query, safe=""))
    title_attr = f' title="{escape(tooltip)}"' if tooltip else ""
    return (
        f'<a class="{class_name}" href="#" onclick="pycmd(\'{payload}\'); return false;"'
        f"{title_attr}{extra_attrs}>{inner_html}</a>"
    )


def _query_metric_name(metric_label: str) -> str | None:
    lookup = {
        "All Cards": "all",
        "Mature": "mature",
        "Young/Learning": "young",
        "Unsuspended": "unsuspended",
        "Suspended": "suspended",
        "Buried": "buried",
        "New": "new",
        "Non-New": "non_new",
        "Learning": "learning",
        "Review": "review",
        "Due Today": "due",
        "Leech": "leech",
        "Reviewed At Least Once": "reviewed",
        "Review Done Today": "today_review_completed",
        "Today's Review Total": "today_review_total",
        "New Done Today": "today_new_completed",
        "Today's New Total": "today_new_total",
        "All Done Today": "today_all_completed",
        "Today's Total": "today_all_total",
    }
    return lookup.get(metric_label)


def _dash_pattern(radius: float, thickness: int, percent: float) -> tuple[float, float]:
    circumference = 2.0 * pi * radius
    bounded = max(0.0, min(100.0, percent))
    if bounded <= 0.0:
        return 0.0, circumference
    raw_dash = circumference * (bounded / 100.0)
    min_dash = max(thickness * 0.9, circumference * 0.015)
    dash = min(circumference - 0.6, max(raw_dash, min_dash))
    return dash, max(circumference - dash, 0.6)


def _safe_id(value: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "ard-id"


def _with_alpha(color: QColor, alpha: float) -> QColor:
    output = QColor(color)
    output.setAlphaF(max(0.0, min(1.0, alpha)))
    return output


def _mix(primary: QColor, secondary: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(1.0, ratio))
    inverse = 1.0 - ratio
    return QColor(
        int(primary.red() * inverse + secondary.red() * ratio),
        int(primary.green() * inverse + secondary.green() * ratio),
        int(primary.blue() * inverse + secondary.blue() * ratio),
        int(primary.alpha() * inverse + secondary.alpha() * ratio),
    )


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.3f})"
