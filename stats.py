from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from time import perf_counter

from anki.collection import Collection

from .config import (
    AddonConfig,
    QueryConfig,
    RingConfig,
    SourceConfig,
    WidgetConfig,
    query_display_label,
    source_display_label,
)
from .metrics import (
    BUILTIN_ALL,
    BUILTIN_TODAY_ALL_COMPLETED,
    BUILTIN_TODAY_ALL_TOTAL,
    BUILTIN_TODAY_NEW_COMPLETED,
    BUILTIN_TODAY_NEW_TOTAL,
    BUILTIN_TODAY_REVIEW_COMPLETED,
    BUILTIN_TODAY_REVIEW_TOTAL,
    BUILTIN_UNSUSPENDED,
    builtin_metric_definition,
    builtin_metric_description,
    builtin_metric_label,
    builtin_metric_names,
    builtin_metric_search_expression,
    card_matches_builtin,
    quoted_search_text,
)

LOGGER = logging.getLogger(__name__.split(".", 1)[0])


@dataclass(frozen=True)
class RingSnapshot:
    ring_id: str
    label: str
    color: str | None
    track_color: str | None
    numerator_count: int
    denominator_count: int
    percent: float
    metric_label: str
    denominator_label: str
    tooltip: str
    browser_query: str | None
    error: str | None = None


@dataclass(frozen=True)
class WidgetSnapshot:
    widget_id: str
    title: str
    subtitle: str | None
    total_cards: int
    rings: tuple[RingSnapshot, ...]
    state: str
    status_message: str | None
    source_query: str | None
    center_value: str
    center_caption: str


@dataclass(frozen=True)
class DashboardSnapshot:
    widgets: tuple[WidgetSnapshot, ...]
    generated_at: float


@dataclass(frozen=True)
class _SourceKey:
    type: str
    text: str
    include_children: bool
    scope: str = "all"


@dataclass
class _SourceResult:
    card_ids: set[int]
    source_query: str | None
    display_label: str
    exists: bool
    error: str | None = None


@dataclass(frozen=True)
class _TodaySourceResult:
    source_query: str | None
    display_label: str
    total_cards: int
    review_completed: int
    review_total: int
    new_completed: int
    new_total: int
    exists: bool
    error: str | None = None


def collect_dashboard_stats(col: Collection, config: AddonConfig) -> DashboardSnapshot:
    if not config.widgets:
        return DashboardSnapshot(widgets=tuple(), generated_at=time.time())

    debug_timing = config.global_config.debug_timing
    start = perf_counter()

    source_widgets = tuple(widget for widget in config.widgets if widget.source.type in {"tag", "deck", "search"})
    today_widgets = tuple(widget for widget in config.widgets if widget.source.type == "today")
    source_keys = _unique_source_keys(source_widgets)
    existing_tags = _existing_tags(col)
    existing_decks = _existing_decks(col)
    source_results = _collect_sources(col, source_keys, existing_tags, existing_decks)
    source_card_rows = _load_card_rows_for_sources(col, source_results)
    query_cache = _build_query_cache(col, config.widgets)
    today_results = _collect_today_sources(col, today_widgets)

    if debug_timing:
        LOGGER.info(
            "Stats prep finished in %.1f ms for %d widgets and %d unique sources.",
            (perf_counter() - start) * 1000.0,
            len(config.widgets),
            len(source_keys),
        )

    widgets: list[WidgetSnapshot] = []
    for widget in config.widgets:
        if widget.source.type == "today":
            today_result = today_results.get(
                _source_key(widget.source),
                _TodaySourceResult(
                    source_query=_source_browser_query(widget.source),
                    display_label=source_display_label(widget.source),
                    total_cards=0,
                    review_completed=0,
                    review_total=0,
                    new_completed=0,
                    new_total=0,
                    exists=False,
                    error="Today's progress source was not available.",
                ),
            )
            widgets.append(_build_today_widget_snapshot(widget=widget, source_result=today_result))
            continue
        source_key = _source_key(widget.source)
        source_result = source_results.get(
            source_key,
            _SourceResult(
                card_ids=set(),
                source_query=_source_browser_query(widget.source),
                display_label=source_display_label(widget.source),
                exists=False,
                error="Source was not available.",
            ),
        )
        card_rows = source_card_rows.get(source_key, {})
        widgets.append(
            _build_widget_snapshot(
                widget=widget,
                source_result=source_result,
                card_rows=card_rows,
                query_cache=query_cache,
            )
        )

    if debug_timing:
        LOGGER.info(
            "Stats snapshot completed in %.1f ms total.",
            (perf_counter() - start) * 1000.0,
        )

    return DashboardSnapshot(widgets=tuple(widgets), generated_at=time.time())


def _build_widget_snapshot(
    *,
    widget: WidgetConfig,
    source_result: _SourceResult,
    card_rows: dict[int, tuple[int, int, int]],
    query_cache: dict[str, tuple[set[int], str | None]],
) -> WidgetSnapshot:
    source_label = source_display_label(widget.source)
    title = widget.title.strip() or source_label
    subtitle = source_label if widget.layout.show_source_subtitle else None
    total_cards = len(source_result.card_ids)

    if widget.source.type == "tag" and not (widget.source.tag or "").strip():
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=0,
            rings=tuple(),
            state="empty",
            status_message=None,
            source_query=None,
            center_value="0",
            center_caption="Tag Empty",
        )

    if widget.source.type == "deck" and not (widget.source.deck or "").strip():
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=0,
            rings=tuple(),
            state="empty",
            status_message=None,
            source_query=None,
            center_value="0",
            center_caption="Deck Empty",
        )

    if source_result.error:
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=total_cards,
            rings=tuple(),
            state="error",
            status_message=source_result.error,
            source_query=_source_browser_query(widget.source),
            center_value="!",
            center_caption="Error",
        )

    if total_cards == 0 and not source_result.exists and widget.source.type == "tag":
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=0,
            rings=tuple(),
            state="missing",
            status_message="Tag not found",
            source_query=_source_browser_query(widget.source),
            center_value="0",
            center_caption="Tag not found",
        )

    if total_cards == 0 and not source_result.exists and widget.source.type == "deck":
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=0,
            rings=tuple(),
            state="missing",
            status_message="Deck not found",
            source_query=_source_browser_query(widget.source),
            center_value="0",
            center_caption="Deck not found",
        )

    ring_snapshots: list[RingSnapshot] = []
    for ring in widget.rings:
        ring_snapshots.append(
            _build_ring_snapshot(
                widget=widget,
                ring=ring,
                source_label=source_label,
                source_result=source_result,
                card_rows=card_rows,
                query_cache=query_cache,
            )
        )

    status_message = _widget_status_message(total_cards, ring_snapshots)
    state = "ok"
    if total_cards == 0:
        state = "empty"
        status_message = "No cards found for this source."

    center_value, center_caption = _center_label(widget, total_cards, ring_snapshots, status_message)
    return WidgetSnapshot(
        widget_id=widget.id,
        title=title,
        subtitle=subtitle,
        total_cards=total_cards,
        rings=tuple(ring_snapshots),
        state=state,
        status_message=status_message,
        source_query=_source_browser_query(widget.source),
        center_value=center_value,
        center_caption=center_caption,
    )


def _build_today_widget_snapshot(
    *,
    widget: WidgetConfig,
    source_result: _TodaySourceResult,
) -> WidgetSnapshot:
    source_label = source_display_label(widget.source)
    title = widget.title.strip() or source_label
    subtitle = source_label if widget.layout.show_source_subtitle else None
    total_cards = source_result.total_cards

    if source_result.error:
        return WidgetSnapshot(
            widget_id=widget.id,
            title=title,
            subtitle=subtitle,
            total_cards=total_cards,
            rings=tuple(),
            state="error",
            status_message=source_result.error,
            source_query=source_result.source_query,
            center_value="!",
            center_caption="Error",
        )

    ring_snapshots: list[RingSnapshot] = [
        _build_today_ring_snapshot(
            widget=widget,
            ring=ring,
            source_label=source_label,
            source_result=source_result,
        )
        for ring in widget.rings
    ]

    status_message: str | None = None
    state = "ok"
    if total_cards == 0:
        state = "empty"
        status_message = "No new or review cards are scheduled for today."

    center_value, center_caption = _center_label(widget, total_cards, ring_snapshots, status_message)
    return WidgetSnapshot(
        widget_id=widget.id,
        title=title,
        subtitle=subtitle,
        total_cards=total_cards,
        rings=tuple(ring_snapshots),
        state=state,
        status_message=status_message,
        source_query=source_result.source_query,
        center_value=center_value,
        center_caption=center_caption,
    )


def _build_ring_snapshot(
    *,
    widget: WidgetConfig,
    ring: RingConfig,
    source_label: str,
    source_result: _SourceResult,
    card_rows: dict[int, tuple[int, int, int]],
    query_cache: dict[str, tuple[set[int], str | None]],
) -> RingSnapshot:
    metric_label = query_display_label(ring.metric)
    denominator_label = query_display_label(ring.denominator)

    numerator_count, numerator_error = _count_query_for_source(
        ring.metric, source_result.card_ids, card_rows, query_cache
    )
    denominator_count, denominator_error = _count_query_for_source(
        ring.denominator, source_result.card_ids, card_rows, query_cache
    )
    error = numerator_error or denominator_error
    percent = 0.0 if denominator_count <= 0 else (numerator_count / denominator_count) * 100.0
    tooltip = _ring_tooltip(
        ring=ring,
        numerator_count=numerator_count,
        denominator_count=denominator_count,
        source_result=source_result,
        source_label=source_label,
        metric_label=metric_label,
        denominator_label=denominator_label,
        error=error,
    )
    browser_query = _ring_browser_query(widget, ring, source_result)

    return RingSnapshot(
        ring_id=ring.id,
        label=ring.label,
        color=ring.color,
        track_color=ring.track_color,
        numerator_count=numerator_count,
        denominator_count=denominator_count,
        percent=percent,
        metric_label=metric_label,
        denominator_label=denominator_label,
        tooltip=tooltip,
        browser_query=browser_query,
        error=error,
    )


def _build_today_ring_snapshot(
    *,
    widget: WidgetConfig,
    ring: RingConfig,
    source_label: str,
    source_result: _TodaySourceResult,
) -> RingSnapshot:
    metric_label = query_display_label(ring.metric)
    denominator_label = query_display_label(ring.denominator)

    numerator_count, numerator_error = _count_today_query(ring.metric, source_result)
    denominator_count, denominator_error = _count_today_query(ring.denominator, source_result)
    error = numerator_error or denominator_error
    percent = 0.0 if denominator_count <= 0 else (numerator_count / denominator_count) * 100.0
    tooltip = _ring_tooltip(
        ring=ring,
        numerator_count=numerator_count,
        denominator_count=denominator_count,
        source_result=None,
        source_label=source_label,
        metric_label=metric_label,
        denominator_label=denominator_label,
        error=error,
    )
    browser_query = _today_ring_browser_query(widget.source, ring)

    return RingSnapshot(
        ring_id=ring.id,
        label=ring.label,
        color=ring.color,
        track_color=ring.track_color,
        numerator_count=numerator_count,
        denominator_count=denominator_count,
        percent=percent,
        metric_label=metric_label,
        denominator_label=denominator_label,
        tooltip=tooltip,
        browser_query=browser_query,
        error=error,
    )


def _widget_status_message(total_cards: int, ring_snapshots: list[RingSnapshot]) -> str | None:
    if total_cards == 0:
        return "No cards found for this source."
    unsuspended_ring = next(
        (ring for ring in ring_snapshots if ring.metric_label == builtin_metric_label(BUILTIN_UNSUSPENDED)),
        None,
    )
    if unsuspended_ring and unsuspended_ring.numerator_count == 0:
        return "All cards in this source are suspended."
    return None


def _center_label(
    widget: WidgetConfig,
    total_cards: int,
    ring_snapshots: list[RingSnapshot],
    status_message: str | None,
) -> tuple[str, str]:
    primary_ring = _primary_ring(widget, ring_snapshots)
    mode = widget.layout.center_label_mode
    custom_caption = (widget.layout.center_label_text or "").strip()
    if status_message and mode != "none":
        return ("0" if total_cards == 0 else "!", status_message)
    if mode == "none":
        return "", ""
    if mode == "title":
        return widget.title, custom_caption
    if mode == "card_count":
        return str(total_cards), custom_caption or "cards"
    if primary_ring is None:
        return str(total_cards), custom_caption or "cards"
    if mode == "primary_metric":
        return f"{primary_ring.numerator_count:,}", custom_caption or primary_ring.label
    return f"{primary_ring.percent:.0f}%", custom_caption or primary_ring.label


def _primary_ring(widget: WidgetConfig, ring_snapshots: list[RingSnapshot]) -> RingSnapshot | None:
    if not ring_snapshots:
        return None
    if widget.layout.primary_ring_id:
        for ring in ring_snapshots:
            if ring.ring_id == widget.layout.primary_ring_id:
                return ring
    return ring_snapshots[0]


def _ring_tooltip(
    *,
    ring: RingConfig,
    numerator_count: int,
    denominator_count: int,
    source_result: _SourceResult | None,
    source_label: str,
    metric_label: str,
    denominator_label: str,
    error: str | None,
) -> str:
    if error:
        return error
    return (
        f"{ring.label}: {numerator_count:,} {metric_label.lower()} cards out of "
        f"{denominator_count:,} {denominator_label.lower()} cards in {source_label}."
    )


def _collect_sources(
    col: Collection,
    source_keys: tuple[_SourceKey, ...],
    existing_tags: tuple[str, ...],
    existing_decks: tuple[str, ...],
) -> dict[_SourceKey, _SourceResult]:
    tag_sources = tuple(source for source in source_keys if source.type == "tag")
    deck_sources = tuple(source for source in source_keys if source.type == "deck")
    search_sources = tuple(source for source in source_keys if source.type == "search")
    results: dict[_SourceKey, _SourceResult] = {}

    if tag_sources:
        results.update(_collect_tag_sources(col, tag_sources, existing_tags))
    if deck_sources:
        results.update(_collect_deck_sources(col, deck_sources, existing_decks))
    if search_sources:
        results.update(_collect_search_sources(col, search_sources))
    return results


def _collect_today_sources(
    col: Collection,
    widgets: tuple[WidgetConfig, ...],
) -> dict[_SourceKey, _TodaySourceResult]:
    if not widgets:
        return {}

    source_keys = _unique_source_keys(widgets)
    deck_ids = _deck_name_to_id_map(col)
    results: dict[_SourceKey, _TodaySourceResult] = {}

    for source_key in source_keys:
        scope_label = _today_display_label_from_key(source_key)
        source_query = _today_source_query_from_key(source_key)
        if source_key.scope == "deck":
            deck_id = deck_ids.get(source_key.text)
            if deck_id is None:
                results[source_key] = _TodaySourceResult(
                    source_query=source_query,
                    display_label=scope_label,
                    total_cards=0,
                    review_completed=0,
                    review_total=0,
                    new_completed=0,
                    new_total=0,
                    exists=False,
                    error="Deck not found",
                )
                continue
            due_tree = col.sched.deck_due_tree(deck_id)
        else:
            due_tree = col.sched.deck_due_tree()

        remaining_review = int(getattr(due_tree, "review_count", 0) or 0)
        remaining_new = int(getattr(due_tree, "new_count", 0) or 0)
        scope_query = _today_scope_filter_from_key(source_key)
        review_completed, review_error = _safe_find_cards_count(
            col,
            _and_query(scope_query, "rated:1", "is:review"),
        )
        new_completed, new_error = _safe_find_cards_count(
            col,
            _and_query(scope_query, "introduced:1"),
        )
        error = review_error or new_error
        review_total = remaining_review + review_completed
        new_total = remaining_new + new_completed

        results[source_key] = _TodaySourceResult(
            source_query=source_query,
            display_label=scope_label,
            total_cards=review_total + new_total,
            review_completed=review_completed,
            review_total=review_total,
            new_completed=new_completed,
            new_total=new_total,
            exists=True,
            error=error,
        )

    return results


def _collect_tag_sources(
    col: Collection,
    source_keys: tuple[_SourceKey, ...],
    existing_tags: tuple[str, ...],
) -> dict[_SourceKey, _SourceResult]:
    if not source_keys:
        return {}

    placeholder_sources = tuple(source_key for source_key in source_keys if not source_key.text)
    real_sources = tuple(source_key for source_key in source_keys if source_key.text)

    results: dict[_SourceKey, _SourceResult] = {
        source_key: _SourceResult(
            card_ids=set(),
            source_query=None,
            display_label="No tag selected",
            exists=True,
            error=None,
        )
        for source_key in placeholder_sources
    }

    if not real_sources:
        return results

    clauses: list[str] = []
    params: list[str] = []
    for source_key in real_sources:
        patterns = _tag_like_patterns(source_key.text, include_children=source_key.include_children)
        clauses.append("(" + " OR ".join("n.tags LIKE ? ESCAPE '\\' COLLATE NOCASE" for _ in patterns) + ")")
        params.extend(patterns)

    sql = f"""
SELECT c.id, n.tags
FROM cards c
JOIN notes n ON n.id = c.nid
WHERE {" OR ".join(clauses)}
"""
    rows = col.db.all(sql, *params)
    results.update({
        source_key: _SourceResult(
            card_ids=set(),
            source_query=_source_browser_query_from_key(source_key),
            display_label=source_key.text,
            exists=_tag_exists(existing_tags, source_key.text, include_children=source_key.include_children),
            error=None,
        )
        for source_key in real_sources
    })

    for card_id, tag_string in rows:
        note_tags = _note_tags(str(tag_string or ""))
        card_id_int = int(card_id)
        for source_key in real_sources:
            if _tag_matches_source(note_tags, source_key.text, include_children=source_key.include_children):
                results[source_key].card_ids.add(card_id_int)

    return results


def _collect_search_sources(
    col: Collection,
    source_keys: tuple[_SourceKey, ...],
) -> dict[_SourceKey, _SourceResult]:
    results: dict[_SourceKey, _SourceResult] = {}
    deduped: dict[str, tuple[set[int], str | None]] = {}

    for source_key in source_keys:
        cached = deduped.get(source_key.text)
        if cached is None:
            try:
                cached = ({int(card_id) for card_id in col.find_cards(source_key.text)}, None)
            except Exception as exc:
                cached = (set(), f"Invalid search source: {exc}")
            deduped[source_key.text] = cached
        card_ids, error = cached
        results[source_key] = _SourceResult(
            card_ids=set(card_ids),
            source_query=source_key.text,
            display_label=source_key.text,
            exists=not error,
            error=error,
        )
    return results


def _collect_deck_sources(
    col: Collection,
    source_keys: tuple[_SourceKey, ...],
    existing_decks: tuple[str, ...],
) -> dict[_SourceKey, _SourceResult]:
    if not source_keys:
        return {}

    results: dict[_SourceKey, _SourceResult] = {}
    deduped: dict[str, tuple[set[int], str | None]] = {}

    for source_key in source_keys:
        if not source_key.text:
            results[source_key] = _SourceResult(
                card_ids=set(),
                source_query=None,
                display_label="No deck selected",
                exists=True,
                error=None,
            )
            continue

        query = _source_browser_query_from_key(source_key)
        if query is None:
            results[source_key] = _SourceResult(
                card_ids=set(),
                source_query=None,
                display_label=source_key.text,
                exists=False,
                error=None,
            )
            continue

        cached = deduped.get(query)
        if cached is None:
            try:
                cached = ({int(card_id) for card_id in col.find_cards(query)}, None)
            except Exception as exc:
                cached = (set(), f"Invalid deck source: {exc}")
            deduped[query] = cached
        card_ids, error = cached
        results[source_key] = _SourceResult(
            card_ids=set(card_ids),
            source_query=query,
            display_label=source_key.text,
            exists=_deck_exists(existing_decks, source_key.text),
            error=error,
        )

    return results


def _build_query_cache(
    col: Collection,
    widgets: tuple[WidgetConfig, ...],
) -> dict[str, tuple[set[int], str | None]]:
    queries: dict[str, tuple[set[int], str | None]] = {}
    needed_expressions: set[str] = set()

    for widget in widgets:
        for ring in widget.rings:
            for query in (ring.metric, ring.denominator):
                expression = _query_search_expression(query)
                if expression:
                    needed_expressions.add(expression)

    for expression in needed_expressions:
        try:
            queries[expression] = ({int(card_id) for card_id in col.find_cards(expression)}, None)
        except Exception as exc:
            queries[expression] = (set(), f"Invalid search expression `{expression}`: {exc}")
    return queries


def _load_card_rows_for_sources(
    col: Collection,
    source_results: dict[_SourceKey, _SourceResult],
) -> dict[_SourceKey, dict[int, tuple[int, int, int]]]:
    union_ids: set[int] = set()
    for source_result in source_results.values():
        union_ids.update(source_result.card_ids)

    rows_by_id = _load_card_rows(col, union_ids)
    return {
        source_key: {
            card_id: rows_by_id[card_id]
            for card_id in source_result.card_ids
            if card_id in rows_by_id
        }
        for source_key, source_result in source_results.items()
    }


def _load_card_rows(
    col: Collection,
    card_ids: set[int],
) -> dict[int, tuple[int, int, int]]:
    if not card_ids:
        return {}

    rows_by_id: dict[int, tuple[int, int, int]] = {}
    chunk_size = 800
    card_id_list = sorted(card_ids)
    for start_index in range(0, len(card_id_list), chunk_size):
        chunk = card_id_list[start_index : start_index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        sql = f"SELECT id, queue, ivl, type FROM cards WHERE id IN ({placeholders})"
        for card_id, queue, ivl, card_type in col.db.all(sql, *chunk):
            rows_by_id[int(card_id)] = (int(queue), int(ivl), int(card_type))
    return rows_by_id


def _count_query_for_source(
    query: QueryConfig,
    source_card_ids: set[int],
    card_rows: dict[int, tuple[int, int, int]],
    query_cache: dict[str, tuple[set[int], str | None]],
) -> tuple[int, str | None]:
    if not source_card_ids:
        return 0, None

    if query.type == "builtin" and query.name == BUILTIN_ALL:
        return len(source_card_ids), None

    if query.type == "builtin" and query.name:
        definition = builtin_metric_definition(query.name)
        if definition and definition.matcher:
            count = 0
            for card_id in source_card_ids:
                row = card_rows.get(card_id)
                if not row:
                    continue
                queue, ivl, card_type = row
                if card_matches_builtin(query.name, queue, ivl, card_type):
                    count += 1
            return count, None

    expression = _query_search_expression(query)
    if not expression:
        return 0, "This metric could not be translated into an Anki search."
    matched_ids, error = query_cache.get(expression, (set(), None))
    if error:
        return 0, error
    return len(source_card_ids & matched_ids), None


def _count_today_query(
    query: QueryConfig,
    source_result: _TodaySourceResult,
) -> tuple[int, str | None]:
    if query.type != "builtin" or not query.name:
        return 0, "Today's Progress currently supports built-in today metrics only."

    counts = {
        BUILTIN_ALL: source_result.total_cards,
        BUILTIN_TODAY_REVIEW_COMPLETED: source_result.review_completed,
        BUILTIN_TODAY_REVIEW_TOTAL: source_result.review_total,
        BUILTIN_TODAY_NEW_COMPLETED: source_result.new_completed,
        BUILTIN_TODAY_NEW_TOTAL: source_result.new_total,
        BUILTIN_TODAY_ALL_COMPLETED: source_result.review_completed + source_result.new_completed,
        BUILTIN_TODAY_ALL_TOTAL: source_result.total_cards,
    }
    if query.name not in counts:
        return 0, f"`{query_display_label(query)}` is not supported for Today's Progress sources."
    return counts[query.name], None


def _safe_find_cards_count(col: Collection, query: str | None) -> tuple[int, str | None]:
    if not query:
        return 0, None
    try:
        return len({int(card_id) for card_id in col.find_cards(query)}), None
    except Exception as exc:
        return 0, f"Invalid search expression `{query}`: {exc}"


def _unique_source_keys(widgets: tuple[WidgetConfig, ...]) -> tuple[_SourceKey, ...]:
    ordered: list[_SourceKey] = []
    seen: set[_SourceKey] = set()
    for widget in widgets:
        source_key = _source_key(widget.source)
        if source_key not in seen:
            seen.add(source_key)
            ordered.append(source_key)
    return tuple(ordered)


def _source_key(source: SourceConfig) -> _SourceKey:
    if source.type == "tag":
        return _SourceKey(type="tag", text=(source.tag or "").strip().lower(), include_children=source.include_children)
    if source.type == "deck":
        return _SourceKey(type="deck", text=(source.deck or "").strip(), include_children=False)
    if source.type == "today":
        return _SourceKey(
            type="today",
            text=(source.deck or "").strip().casefold(),
            include_children=False,
            scope=source.scope,
        )
    return _SourceKey(type="search", text=(source.search or "").strip(), include_children=False)


def _source_browser_query(source: SourceConfig) -> str | None:
    if source.type == "today":
        return _today_source_query(source)
    return _source_browser_query_from_key(_source_key(source))


def _source_browser_query_from_key(source_key: _SourceKey) -> str | None:
    if source_key.type == "search":
        return source_key.text
    if source_key.type == "deck":
        if not source_key.text:
            return None
        return f'deck:{quoted_search_text(source_key.text)}'
    if source_key.type == "today":
        return _today_source_query_from_key(source_key)
    if not source_key.text:
        return None
    tag_queries = [f"tag:{quoted_search_text(variant)}" for variant in _tag_search_variants(source_key.text)]
    if len(tag_queries) == 1:
        return tag_queries[0]
    return "(" + " OR ".join(tag_queries) + ")"


def _query_search_expression(query: QueryConfig) -> str | None:
    if query.type == "builtin" and query.name:
        return builtin_metric_search_expression(query.name)
    if query.type == "search":
        return (query.search or "").strip() or None
    return None


def _ring_browser_query(
    widget: WidgetConfig,
    ring: RingConfig,
    source_result: _SourceResult,
) -> str | None:
    if widget.layout.ring_click_action == "none":
        return None
    if widget.layout.ring_click_action == "source":
        return _source_browser_query(widget.source)

    metric_query = _query_search_expression(ring.metric)
    if not metric_query:
        return _source_browser_query(widget.source)
    source_query = _source_browser_query(widget.source)
    if source_query:
        return f"({source_query}) AND ({metric_query})"
    return metric_query


def _today_ring_browser_query(source: SourceConfig, ring: RingConfig) -> str | None:
    if ring.metric.type != "builtin" or not ring.metric.name:
        return _today_source_query(source)
    return _today_metric_query(source, ring.metric.name) or _today_source_query(source)


def _today_source_query(source: SourceConfig) -> str | None:
    return _today_source_query_from_key(_source_key(source))


def _today_source_query_from_key(source_key: _SourceKey) -> str | None:
    scope_query = _today_scope_filter_from_key(source_key)
    return _and_query(
        scope_query,
        "((rated:1 AND is:review) OR introduced:1 OR is:new OR (is:due AND is:review))",
    )


def _today_metric_query(source: SourceConfig, metric_name: str) -> str | None:
    scope_query = _today_scope_filter(source)
    if metric_name == BUILTIN_TODAY_REVIEW_COMPLETED:
        return _and_query(scope_query, "rated:1", "is:review")
    if metric_name == BUILTIN_TODAY_REVIEW_TOTAL:
        return _and_query(scope_query, "((rated:1 AND is:review) OR (is:due AND is:review))")
    if metric_name == BUILTIN_TODAY_NEW_COMPLETED:
        return _and_query(scope_query, "introduced:1")
    if metric_name == BUILTIN_TODAY_NEW_TOTAL:
        return _and_query(scope_query, "(introduced:1 OR is:new)")
    if metric_name == BUILTIN_TODAY_ALL_COMPLETED:
        return _and_query(scope_query, "((rated:1 AND is:review) OR introduced:1)")
    if metric_name in {BUILTIN_TODAY_ALL_TOTAL, BUILTIN_ALL}:
        return _today_source_query(source)
    return None


def _today_scope_filter(source: SourceConfig) -> str | None:
    return _today_scope_filter_from_key(_source_key(source))


def _today_scope_filter_from_key(source_key: _SourceKey) -> str | None:
    if source_key.scope != "deck" or not source_key.text:
        return None
    return f"deck:{quoted_search_text(source_key.text)}"


def _today_display_label_from_key(source_key: _SourceKey) -> str:
    if source_key.scope == "deck" and source_key.text:
        return f"Today's Progress · {source_key.text}"
    return "Today's Progress · All Decks"


def _deck_name_to_id_map(col: Collection) -> dict[str, int]:
    deck_ids: dict[str, int] = {}
    for deck_name_id in col.decks.all_names_and_ids():
        name = getattr(deck_name_id, "name", "")
        deck_id = getattr(deck_name_id, "id", None)
        if isinstance(name, str) and name.strip() and deck_id is not None:
            deck_ids[name.strip().casefold()] = int(deck_id)
    return deck_ids


def _existing_decks(col: Collection) -> tuple[str, ...]:
    return tuple(_deck_name_to_id_map(col).keys())


def _and_query(*parts: str | None) -> str | None:
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return " AND ".join(f"({part})" for part in cleaned)


def _note_tags(raw: str) -> tuple[str, ...]:
    stripped = raw.strip()
    if not stripped:
        return tuple()
    return tuple(_canonicalize_tag_path(piece) for piece in stripped.split() if piece.strip())


def _tag_matches_source(
    note_tags: tuple[str, ...],
    source_text: str,
    *,
    include_children: bool,
) -> bool:
    normalized = _canonicalize_tag_path(source_text)
    if not normalized:
        return False
    prefix = f"{normalized}::"
    infix = f"::{normalized}::"
    suffix = f"::{normalized}"
    return any(
        tag == normalized
        or tag.endswith(suffix)
        or (include_children and (tag.startswith(prefix) or infix in tag))
        for tag in note_tags
    )


def _existing_tags(col: Collection) -> tuple[str, ...]:
    values: list[str] = []
    for tag in col.tags.all():
        name = getattr(tag, "name", tag)
        if isinstance(name, str) and name.strip():
            normalized = _canonicalize_tag_path(name)
            if normalized:
                values.append(normalized)
    return tuple(values)


def _deck_exists(existing_decks: tuple[str, ...], source_text: str) -> bool:
    normalized = source_text.strip().casefold()
    return bool(normalized) and normalized in existing_decks


def _tag_exists(existing_tags: tuple[str, ...], source_text: str, *, include_children: bool) -> bool:
    normalized = _canonicalize_tag_path(source_text)
    if not normalized:
        return False
    prefix = f"{normalized}::"
    infix = f"::{normalized}::"
    suffix = f"::{normalized}"
    return any(
        tag == normalized
        or tag.endswith(suffix)
        or (include_children and (tag.startswith(prefix) or infix in tag))
        for tag in existing_tags
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tag_like_patterns(tag: str, *, include_children: bool) -> tuple[str, ...]:
    patterns: list[str] = []
    for variant in _tag_search_variants(tag):
        escaped = _escape_like(variant.strip())
        if not escaped:
            continue
        patterns.extend([f"% {escaped} %", f"%::{escaped} %"])
        if include_children:
            patterns.extend([f"% {escaped}::%", f"%::{escaped}::%"])
    return tuple(dict.fromkeys(patterns))


def _canonicalize_tag_path(value: str) -> str:
    segments = []
    for segment in value.split("::"):
        normalized = segment.strip().lstrip("#").lower()
        if normalized:
            segments.append(normalized)
    return "::".join(segments)


def _tag_search_variants(value: str) -> tuple[str, ...]:
    raw_segments = [segment.strip().lower() for segment in value.split("::") if segment.strip()]
    raw = "::".join(raw_segments)
    canonical = _canonicalize_tag_path(value)
    variants = [variant for variant in (raw, canonical) if variant]
    return tuple(dict.fromkeys(variants))
