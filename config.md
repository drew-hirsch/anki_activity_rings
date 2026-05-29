## Activity Rings Config Reference

The add-on supports both the visual editor and direct JSON editing.

Top level:

```json
{
  "global": { ... },
  "widgets": [ ... ]
}
```

## `global`

`show_on_screens`

- list of screens
- supported values: `deckBrowser`, `overview`

`panel_margin`

- outer horizontal margin for the widget area

`panel_spacing`

- spacing between cards in the wrapping grid

`match_widget_sizes`

- if `true`, cards share a common width and minimum height across the dashboard
- enabled by default

`cache_ttl_seconds`

- how long a snapshot may be reused before refreshing

`hide_when_no_widgets`

- if `true`, the dashboard area stays hidden when `widgets` is empty
- if `false`, the dashboard shows a small configuration call-to-action

`dashboard_position`

- `top`
- `bottom`

`theme`

- `auto`
- `light`
- `dark`

`palette`

- `soft`
- `vibrant`
- `colorblind`

`default_card_style`

- currently `native`

`debug_timing`

- if `true`, logs timing information for stats collection

## `widgets`

Each widget represents one source and one or more rings.

### Widget keys

`id`

- stable identifier

`title`

- user-facing title

`source`

- object describing what card set this widget measures

`layout`

- object describing card layout, legend visibility, ring sizing, and click behavior

`style`

- object describing colors, opacity, border, shadow, and glow

`rings`

- list of ring definitions

## `source`

### Tag source

```json
{
  "type": "tag",
  "tag": "#AK_Step1_v12::FirstAid",
  "include_children": true
}
```

`tag` may also be an empty string as a saved placeholder. In that case the widget renders empty rings, shows `Tag Empty`, and clicking the dashboard card opens the standalone tag picker.

### Deck source

```json
{
  "type": "deck",
  "deck": "Step 1::Pharm"
}
```

`deck` may also be an empty string as a saved placeholder. In that case the widget renders empty rings, shows `Deck Empty`, and clicking the dashboard card opens the combined tag/deck picker.

### Search source

```json
{
  "type": "search",
  "search": "deck:\"Step 1\" -is:suspended"
}
```

### Today's progress source

```json
{
  "type": "today",
  "scope": "all"
}
```

Or one deck:

```json
{
  "type": "today",
  "scope": "deck",
  "deck": "Step 1::Pharm"
}
```

## `layout`

`mode`

- `compact`
- `wide`

`title_position`

- `above`
- `inside`
- `center`
- `hidden`

`show_source_subtitle`

- show or hide the raw tag/search subtitle

`show_total_cards`

- show the total number of cards in the source
- for `today` sources, this means today's total new + review cards

`show_legend`

- show the metric rows

`show_counts`

- show `numerator / denominator`

`show_percentages`

- show the percentage value

`ring_size`

- ring canvas size in pixels

`ring_thickness`

- thickness of each ring in pixels

`ring_gap`

- gap between rings in pixels

`card_min_width`

- minimum card width in the wrapping dashboard

`card_max_width`

- maximum card width in the wrapping dashboard

`card_aspect_ratio`

- preferred compact-card proportion

`card_padding`

- card inner padding

`center_label_mode`

- `none`
- `card_count`
- `primary_percent`
- `primary_metric`
- `title`

`primary_ring_id`

- optional ring id used for center label and primary click behavior

`center_label_text`

- optional text shown under the center value instead of the default ring label or `cards`

`center_value_font_size`

- font size in pixels for the large center value inside the ring

`center_value_auto_fit`

- if `true`, auto-fits the center percent/number with a small margin so it stays inside the ring comfortably
- when enabled in the visual editor, the manual size box is disabled

`center_caption_font_size`

- font size in pixels for the smaller center text under the value

`center_caption_auto_fit`

- if `true`, auto-fits the smaller center text with a small margin so it does not crowd the ring
- when enabled in the visual editor, the manual size box is disabled

`click_action`

- card click behavior
- `none`
- `source`
- `numerator`

`ring_click_action`

- ring click behavior
- `none`
- `source`
- `numerator`

## `style`

`background_color`

- any valid Qt color string or `auto`

`card_opacity`

- float from `0.0` to `1.0`

`border_color`

- any valid Qt color string or `auto`

`shadow_enabled`

- boolean

`track_color`

- any valid Qt color string or `auto`

`use_glow`

- boolean

## `rings`

Each ring has:

`id`

- stable ring identifier

`enabled`

- boolean

`label`

- user-facing legend label

`metric`

- numerator rule

`denominator`

- denominator rule

`color`

- active ring color, or `auto`

`track_color`

- track color override, or `auto`

## `metric` / `denominator` query objects

### Built-in query

```json
{
  "type": "builtin",
  "name": "mature"
}
```

### Custom search query

```json
{
  "type": "search",
  "search": "is:due"
}
```

## Built-in metric names

- `all`
- `mature`
- `young`
- `unsuspended`
- `suspended`
- `buried`
- `new`
- `non_new`
- `learning`
- `review`
- `due`
- `leech`
- `reviewed`

## Recommended default semantics

These are the add-on defaults:

- `Mature / Unsuspended`
- `Young/Learning / Unsuspended`
- `Unsuspended / All`

That gives a clearer meaning than treating every ring as “completion.”

## Example

```json
{
  "global": {
    "show_on_screens": ["deckBrowser", "overview"],
    "panel_margin": 18,
    "panel_spacing": 16,
    "cache_ttl_seconds": 30,
    "hide_when_no_widgets": false,
    "dashboard_position": "top",
    "theme": "auto",
    "palette": "soft",
    "default_card_style": "native",
    "debug_timing": false
  },
  "widgets": [
    {
      "id": "first_aid",
      "title": "First Aid",
      "source": {
        "type": "tag",
        "tag": "#AK_Step1_v12::FirstAid",
        "include_children": true
      },
      "layout": {
        "mode": "compact",
        "title_position": "inside",
        "show_source_subtitle": false,
        "show_total_cards": true,
        "show_legend": true,
        "show_counts": true,
        "show_percentages": true,
        "ring_size": 204,
        "ring_thickness": 18,
        "ring_gap": 8,
        "card_min_width": 290,
        "card_max_width": 390,
        "card_aspect_ratio": 1.08,
        "card_padding": 18,
        "center_label_mode": "primary_percent",
        "primary_ring_id": "mature",
        "center_label_text": "",
        "center_value_font_size": 30,
        "center_value_auto_fit": true,
        "center_caption_font_size": 11,
        "center_caption_auto_fit": true,
        "click_action": "source",
        "ring_click_action": "numerator"
      },
      "style": {
        "background_color": "auto",
        "card_opacity": 0.92,
        "border_color": "auto",
        "shadow_enabled": true,
        "track_color": "auto",
        "use_glow": false
      },
      "rings": [
        {
          "id": "mature",
          "enabled": true,
          "label": "Mature",
          "metric": { "type": "builtin", "name": "mature" },
          "denominator": { "type": "builtin", "name": "unsuspended" },
          "color": "auto",
          "track_color": "auto"
        },
        {
          "id": "young",
          "enabled": true,
          "label": "Young/Learning",
          "metric": { "type": "builtin", "name": "young" },
          "denominator": { "type": "builtin", "name": "unsuspended" },
          "color": "auto",
          "track_color": "auto"
        },
        {
          "id": "active",
          "enabled": true,
          "label": "Unsuspended",
          "metric": { "type": "builtin", "name": "unsuspended" },
          "denominator": { "type": "builtin", "name": "all" },
          "color": "auto",
          "track_color": "auto"
        }
      ]
    }
  ]
}
```
