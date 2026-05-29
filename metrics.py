from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from anki.consts import (
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_DAY_LEARN_RELEARN,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)

AggregateMatcher = Callable[[int, int, int], bool]

BUILTIN_ALL = "all"
BUILTIN_MATURE = "mature"
BUILTIN_YOUNG = "young"
BUILTIN_UNSUSPENDED = "unsuspended"
BUILTIN_SUSPENDED = "suspended"
BUILTIN_BURIED = "buried"
BUILTIN_NEW = "new"
BUILTIN_NON_NEW = "non_new"
BUILTIN_LEARNING = "learning"
BUILTIN_REVIEW = "review"
BUILTIN_DUE = "due"
BUILTIN_LEECH = "leech"
BUILTIN_REVIEWED = "reviewed"
BUILTIN_TODAY_REVIEW_COMPLETED = "today_review_completed"
BUILTIN_TODAY_REVIEW_TOTAL = "today_review_total"
BUILTIN_TODAY_NEW_COMPLETED = "today_new_completed"
BUILTIN_TODAY_NEW_TOTAL = "today_new_total"
BUILTIN_TODAY_ALL_COMPLETED = "today_all_completed"
BUILTIN_TODAY_ALL_TOTAL = "today_all_total"


def _always_true(_queue: int, _ivl: int, _card_type: int) -> bool:
    return True


def _is_young(queue: int, ivl: int, _card_type: int) -> bool:
    return queue in {QUEUE_TYPE_LRN, QUEUE_TYPE_DAY_LEARN_RELEARN} or (
        queue == QUEUE_TYPE_REV and ivl < 21
    )


def _is_mature(queue: int, ivl: int, _card_type: int) -> bool:
    return queue == QUEUE_TYPE_REV and ivl >= 21


def _is_unsuspended(queue: int, _ivl: int, _card_type: int) -> bool:
    return queue != QUEUE_TYPE_SUSPENDED


def _is_suspended(queue: int, _ivl: int, _card_type: int) -> bool:
    return queue == QUEUE_TYPE_SUSPENDED


def _is_buried(queue: int, _ivl: int, _card_type: int) -> bool:
    return queue in {QUEUE_TYPE_SIBLING_BURIED, QUEUE_TYPE_MANUALLY_BURIED}


def _is_new(_queue: int, _ivl: int, card_type: int) -> bool:
    return card_type == CARD_TYPE_NEW


def _is_non_new(_queue: int, _ivl: int, card_type: int) -> bool:
    return card_type != CARD_TYPE_NEW


def _is_learning(queue: int, _ivl: int, _card_type: int) -> bool:
    return queue in {QUEUE_TYPE_LRN, QUEUE_TYPE_DAY_LEARN_RELEARN}


def _is_review(_queue: int, _ivl: int, card_type: int) -> bool:
    return card_type == CARD_TYPE_REV


@dataclass(frozen=True)
class BuiltinMetricDefinition:
    key: str
    label: str
    description: str
    matcher: AggregateMatcher | None = None
    search_expression: str | None = None
    default_color_by_palette: dict[str, str] | None = None


_DEFINITIONS: dict[str, BuiltinMetricDefinition] = {
    BUILTIN_ALL: BuiltinMetricDefinition(
        key=BUILTIN_ALL,
        label="All Cards",
        description="All cards in the selected source.",
        matcher=_always_true,
        default_color_by_palette={
            "soft": "#8e8e93",
            "vibrant": "#8e8e93",
            "colorblind": "#8e8e93",
        },
    ),
    BUILTIN_MATURE: BuiltinMetricDefinition(
        key=BUILTIN_MATURE,
        label="Mature",
        description="Review cards with an interval of at least 21 days.",
        matcher=_is_mature,
        search_expression="prop:ivl>=21",
        default_color_by_palette={
            "soft": "#5cc07a",
            "vibrant": "#34c759",
            "colorblind": "#41b45d",
        },
    ),
    BUILTIN_YOUNG: BuiltinMetricDefinition(
        key=BUILTIN_YOUNG,
        label="Young/Learning",
        description="Learning cards plus review cards with an interval under 21 days.",
        matcher=_is_young,
        search_expression="(is:learn or (is:review prop:ivl<21))",
        default_color_by_palette={
            "soft": "#63a9ff",
            "vibrant": "#0a84ff",
            "colorblind": "#e3a641",
        },
    ),
    BUILTIN_UNSUSPENDED: BuiltinMetricDefinition(
        key=BUILTIN_UNSUSPENDED,
        label="Unsuspended",
        description="Cards that are not suspended.",
        matcher=_is_unsuspended,
        search_expression="-is:suspended",
        default_color_by_palette={
            "soft": "#8e72ff",
            "vibrant": "#bf5af2",
            "colorblind": "#7a6cf1",
        },
    ),
    BUILTIN_SUSPENDED: BuiltinMetricDefinition(
        key=BUILTIN_SUSPENDED,
        label="Suspended",
        description="Cards currently suspended.",
        matcher=_is_suspended,
        search_expression="is:suspended",
        default_color_by_palette={
            "soft": "#8f98a5",
            "vibrant": "#ff453a",
            "colorblind": "#7d8793",
        },
    ),
    BUILTIN_BURIED: BuiltinMetricDefinition(
        key=BUILTIN_BURIED,
        label="Buried",
        description="Cards currently buried by the user or scheduler.",
        matcher=_is_buried,
        search_expression="is:buried",
        default_color_by_palette={
            "soft": "#d6a659",
            "vibrant": "#ff9f0a",
            "colorblind": "#b98a2f",
        },
    ),
    BUILTIN_NEW: BuiltinMetricDefinition(
        key=BUILTIN_NEW,
        label="New",
        description="Cards whose type is still new.",
        matcher=_is_new,
        search_expression="is:new",
        default_color_by_palette={
            "soft": "#5fcbf3",
            "vibrant": "#64d2ff",
            "colorblind": "#47a8d6",
        },
    ),
    BUILTIN_NON_NEW: BuiltinMetricDefinition(
        key=BUILTIN_NON_NEW,
        label="Non-New",
        description="Cards that are no longer new.",
        matcher=_is_non_new,
        search_expression="-is:new",
        default_color_by_palette={
            "soft": "#74b58e",
            "vibrant": "#30d158",
            "colorblind": "#5c9c73",
        },
    ),
    BUILTIN_LEARNING: BuiltinMetricDefinition(
        key=BUILTIN_LEARNING,
        label="Learning",
        description="Cards currently in learning or day-learning queues.",
        matcher=_is_learning,
        search_expression="is:learn",
        default_color_by_palette={
            "soft": "#74b2ff",
            "vibrant": "#5ac8fa",
            "colorblind": "#4a92d8",
        },
    ),
    BUILTIN_REVIEW: BuiltinMetricDefinition(
        key=BUILTIN_REVIEW,
        label="Review",
        description="Cards whose type is review.",
        matcher=_is_review,
        search_expression="is:review",
        default_color_by_palette={
            "soft": "#76c99a",
            "vibrant": "#32d74b",
            "colorblind": "#5cae7e",
        },
    ),
    BUILTIN_DUE: BuiltinMetricDefinition(
        key=BUILTIN_DUE,
        label="Due Today",
        description="Cards matching Anki's built-in due search.",
        search_expression="is:due",
        default_color_by_palette={
            "soft": "#f2b36d",
            "vibrant": "#ffd60a",
            "colorblind": "#cc9f2f",
        },
    ),
    BUILTIN_LEECH: BuiltinMetricDefinition(
        key=BUILTIN_LEECH,
        label="Leech",
        description="Cards whose note has the standard leech tag.",
        search_expression='tag:"leech"',
        default_color_by_palette={
            "soft": "#d78282",
            "vibrant": "#ff6961",
            "colorblind": "#ba6a6a",
        },
    ),
    BUILTIN_REVIEWED: BuiltinMetricDefinition(
        key=BUILTIN_REVIEWED,
        label="Reviewed At Least Once",
        description="Cards that have at least one review log entry.",
        search_expression="rated:1",
        default_color_by_palette={
            "soft": "#7abda3",
            "vibrant": "#40c8ae",
            "colorblind": "#5aa38a",
        },
    ),
    BUILTIN_TODAY_REVIEW_COMPLETED: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_REVIEW_COMPLETED,
        label="Review Done Today",
        description="Review cards completed today within the selected all-decks or one-deck scope.",
        default_color_by_palette={
            "soft": "#7f86ff",
            "vibrant": "#5e5ce6",
            "colorblind": "#567bd9",
        },
    ),
    BUILTIN_TODAY_REVIEW_TOTAL: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_REVIEW_TOTAL,
        label="Today's Review Total",
        description="The total number of review cards scheduled for today in the selected scope.",
        default_color_by_palette={
            "soft": "#7f86ff",
            "vibrant": "#5e5ce6",
            "colorblind": "#567bd9",
        },
    ),
    BUILTIN_TODAY_NEW_COMPLETED: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_NEW_COMPLETED,
        label="New Done Today",
        description="New cards introduced today within the selected all-decks or one-deck scope.",
        default_color_by_palette={
            "soft": "#58cda1",
            "vibrant": "#30d158",
            "colorblind": "#4aa974",
        },
    ),
    BUILTIN_TODAY_NEW_TOTAL: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_NEW_TOTAL,
        label="Today's New Total",
        description="The total number of new cards available today in the selected scope.",
        default_color_by_palette={
            "soft": "#58cda1",
            "vibrant": "#30d158",
            "colorblind": "#4aa974",
        },
    ),
    BUILTIN_TODAY_ALL_COMPLETED: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_ALL_COMPLETED,
        label="All Done Today",
        description="All review and new cards completed today within the selected scope.",
        default_color_by_palette={
            "soft": "#66b8ff",
            "vibrant": "#0a84ff",
            "colorblind": "#4a92d8",
        },
    ),
    BUILTIN_TODAY_ALL_TOTAL: BuiltinMetricDefinition(
        key=BUILTIN_TODAY_ALL_TOTAL,
        label="Today's Total",
        description="The total number of review and new cards scheduled for today in the selected scope.",
        default_color_by_palette={
            "soft": "#66b8ff",
            "vibrant": "#0a84ff",
            "colorblind": "#4a92d8",
        },
    ),
}


def builtin_metric_definitions() -> dict[str, BuiltinMetricDefinition]:
    return dict(_DEFINITIONS)


def builtin_metric_definition(metric_key: str) -> BuiltinMetricDefinition | None:
    return _DEFINITIONS.get(metric_key)


def builtin_metric_names() -> tuple[str, ...]:
    return tuple(_DEFINITIONS.keys())


def builtin_metric_label(metric_key: str) -> str:
    definition = builtin_metric_definition(metric_key)
    if definition:
        return definition.label
    return metric_key.replace("_", " ").title()


def builtin_metric_description(metric_key: str) -> str:
    definition = builtin_metric_definition(metric_key)
    if definition:
        return definition.description
    return builtin_metric_label(metric_key)


def is_builtin_metric_supported(metric_key: str) -> bool:
    return metric_key in _DEFINITIONS


def card_matches_builtin(metric_key: str, queue: int, ivl: int, card_type: int) -> bool:
    definition = builtin_metric_definition(metric_key)
    return bool(definition and definition.matcher and definition.matcher(queue, ivl, card_type))


def builtin_metric_search_expression(metric_key: str) -> str | None:
    definition = builtin_metric_definition(metric_key)
    if not definition:
        return None
    return definition.search_expression


def default_palette_color(metric_key: str, palette: str) -> str:
    definition = builtin_metric_definition(metric_key)
    if definition and definition.default_color_by_palette:
        return definition.default_color_by_palette.get(
            palette,
            definition.default_color_by_palette.get("soft", "#8e8e93"),
        )
    return "#8e8e93"


def escape_search_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def quoted_search_text(value: str) -> str:
    return '"' + escape_search_text(value) + '"'
