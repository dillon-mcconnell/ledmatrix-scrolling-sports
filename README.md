# Scrolling Sports Scoreboard (LEDMatrix Plugin)

Vegas-style multi-league sports ticker for LEDMatrix with ESPN data, NCAA filters, soccer league support, custom league logo uploads, and compact game cards optimized for 32px-tall panels.

This README documents the current implementation in `manager.py` and `config_schema.json`.
It is written so you can recreate the same plugin behavior from scratch.

## 1) What This Plugin Does

- Pulls same-day scoreboards from ESPN for enabled leagues.
- Renders one scrolling ticker that contains league headers and game cards.
- Shows leagues in configurable order (`league_order`).
- For each league, renders game sections in this order:
  - `LIVE`
  - `UPCOMING`
  - `FINAL`
- If an enabled league has no games that day:
  - when `show_no_games_today=true`, renders league header + `NO GAMES TODAY`
  - when `show_no_games_today=false`, skips that league entirely

## 2) Supported Leagues

- NFL
- NBA
- NHL
- MLB
- EPL
- La Liga
- Bundesliga
- Serie A
- Ligue 1
- MLS
- UEFA Champions League
- NCAA Men's Basketball (`ncaam`)
- NCAA Football (`ncaaf`)

## 3) Game Card Layout (Current Behavior)

Each game card is rendered as:

`[Away Logo] @ [Home Logo] | [Away/Home Name Stack] | [State Info Stack]`

Details:

- Team logos are intentionally large (about 82% of panel height).
- Logos are side-by-side on the left with `@` between them.
- Away team text is top row, home team text is bottom row.
- For upcoming games only, ranked teams may include `#rank` prefix.
- For live and final games, abbreviations are shown without rank prefix.

State info column:

- Upcoming:
  - Top: compact start time (example `7:30P`)
  - Bottom: compact spread (example `BAMA -3.5`, `PK`, or `N/A`)
- Live:
  - Top: away score + period (`74 2ND`)
  - Bottom: home score + clock (`71 5:45`)
  - Period/clock column is aligned to a fixed score width so single-digit vs double-digit scores do not shift the right text.
  - Period-based OT is normalized (for example CBB `3RD` half becomes `OT`, football `5TH` quarter becomes `OT`).
  - Soccer remains minute-based (for example `90+4'`, `105'`, `115'`) and is not remapped to `OT`.
- Final:
  - Top: away score + `FINAL` (`77 FINAL`)
  - Bottom: home score (`73`)

## 4) League Header Behavior

- Header shows league logo + league name.
- If custom logo exists for that league, plugin uses it first.
- If custom logo fails, plugin falls back to ESPN league logo.
- If no logo loads, a bordered placeholder is drawn.
- Header text stays at configured main font size.

### Custom Logo Scaling

- `league_logo_scale` applies only to custom uploaded/overridden league logos.
- ESPN league logos always use `header_logo_size_px`.
- Custom logos are centered inside the scaled header slot.

## 5) Data and Filtering Rules

### Date Filtering

- Games are filtered to the current date in configured `timezone`.

### NCAA Filter Precedence (Exact)

1. Team filters (`ncaaf_teams`, `ncaam_teams`) take priority.
2. Else conference filters apply.
3. If conference filters exist and both:
   - `ncaa_top25_only = true`
   - `ncaa_include_top25_with_conferences = true`
   then logic is conference OR Top-25.
4. Else if only `ncaa_top25_only = true`, show Top-25 games only.
5. Else show all NCAA games for enabled NCAA leagues.

### Per-Section Sorting

- Live: ascending by start time
- Upcoming: ascending by start time
- Final: descending by start time
- Each section is truncated by `max_games_per_section`.

## 6) Loop and Scroll Mechanics

Ticker construction:

- All cards are stitched into one wide image.
- Spacing between items is `segment_spacing_px + section_spacing_px`.
- A trailing blank gap equal to display width is added.

Viewport logic:

- The renderer does not wrap content within the same frame.
- End-of-ticker tail is shown with blank space.
- Next loop begins after offset wrap.

Early-restart rule:

- Effective loop width is `ticker_width - display_width`.
- This intentionally restarts one screen early to avoid awkward repeated first content at loop boundaries.

Cycle behavior:

- `is_cycle_complete()` returns `False`.
- `supports_dynamic_duration()` returns `False`.
- Result is continuous scrolling with no cycle pause.

## 7) Vegas Mode Integration

- `get_vegas_content_type()` returns `multi`
- Default display mode is Vegas `scroll`
- Supported vegas modes:
  - `scroll`
  - `fixed_segment`

Note:

- When running in global Vegas scroll mode, global Vegas settings also influence perceived speed/spacing.

## 8) Configuration Guide

Full schema lives in `config_schema.json`.
Key settings below are the most important for operation.

### League Selection and Ordering

- `league_nfl_enabled`, `league_nba_enabled`, `league_nhl_enabled`, `league_mlb_enabled`
- `league_epl_enabled`, `league_laliga_enabled`, `league_bundesliga_enabled`, `league_seriea_enabled`, `league_ligue1_enabled`, `league_mls_enabled`, `league_ucl_enabled`
- `league_ncaam_enabled`, `league_ncaaf_enabled`
- `league_order`: array of league keys in desired display order

If `league_order` omits keys, omitted leagues are appended automatically in default order.

### NCAA Controls

- `ncaa_top25_only`
- `ncaa_include_top25_with_conferences`
- `ncaaf_conferences`, `ncaam_conferences`
- `ncaaf_teams`, `ncaam_teams`

For valid conference strings and team-entry guidance, see:

- `NCAA_INPUT_REFERENCE.md`

### Visual and Typography

- `font_family` (`press_start_2p`, `pixel4x6`, `pil_default`)
- `font_size`
- `font_path` (optional override)
- `text_color`, `upcoming_color`, `live_color`, `final_color`, `spread_color`, `header_color`

Important:

- Header/label text uses the configured font size.
- Game card body text uses a smaller derived size (`font_size - 2`, minimum 4) for compact readability.

### Spacing and Layout

- `segment_spacing_px`
- `section_spacing_px`
- `card_padding_px`
- `logo_gap_px`
- `header_logo_size_px`
- `league_logo_scale` (custom league logos only)

Note:

- `logo_size_px` exists in schema but team logo rendering is currently hardcoded to a large dynamic size in `manager.py` for this layout.

### Refresh and Scroll

- `update_interval` (scoreboard API cache TTL minimum is 30s)
- `enable_scrolling`
- `scroll_speed_px`
- `scroll_frame_delay`
- `max_games_per_section`
- `show_section_labels`
- `show_no_games_today`

## 9) Custom League Logos

`league_logo_overrides` supports three input shapes:

- String path (local file path)
- String URL (`http/https`)
- Web UI upload array shape (objects containing `path`)

Path resolution order for local files:

1. Relative to plugin directory (`scrolling-sports/`)
2. Relative to LEDMatrix working directory

If override cannot be loaded, ESPN logo fallback is used automatically.

Recommended logo assets:

- PNG preferred
- Transparent background preferred
- Square-ish aspect recommended
- 64x64 minimum, 128x128+ recommended

## 10) Installation in LEDMatrix

1. Place plugin repo where LEDMatrix can access it.
2. Ensure LEDMatrix plugin system points to your plugins directory (`plugin-repos` by default).
3. Clone/symlink/copy this repo as `scrolling-sports`.
4. Enable plugin in LEDMatrix config under `scrolling-sports`.
5. Restart LEDMatrix services.

Linux symlink example:

```bash
cd /path/to/LEDMatrix
ln -s /path/to/scrolling-sports plugin-repos/scrolling-sports
```

## 11) Example Config Block

```json
{
  "scrolling-sports": {
    "enabled": true,
    "timezone": "America/Chicago",
    "update_interval": 120,
    "show_section_labels": false,
    "show_no_games_today": true,
    "max_games_per_section": 8,
    "font_family": "press_start_2p",
    "font_size": 10,
    "text_color": [255, 255, 255],
    "upcoming_color": [255, 255, 0],
    "live_color": [0, 255, 0],
    "final_color": [180, 180, 180],
    "spread_color": [173, 173, 173],
    "header_color": [255, 255, 255],
    "segment_spacing_px": 12,
    "section_spacing_px": 20,
    "card_padding_px": 4,
    "logo_gap_px": 8,
    "header_logo_size_px": 16,
    "league_logo_scale": 1.25,
    "league_ncaam_enabled": true,
    "league_ncaaf_enabled": false,
    "league_nba_enabled": true,
    "league_order": ["ncaam", "nba", "nfl", "epl", "ucl"],
    "ncaa_top25_only": false,
    "ncaa_include_top25_with_conferences": true,
    "ncaam_conferences": ["BIG TEN"],
    "ncaam_teams": [],
    "league_logo_overrides": {
      "ncaam": [
        {
          "path": "uploads/plugins/scrolling-sports/ncaam_custom.png"
        }
      ]
    }
  }
}
```

## 12) Files in This Repo

- `manager.py`: plugin logic (fetch, filtering, render, loop)
- `config_schema.json`: web UI schema and defaults
- `manifest.json`: plugin metadata and compatibility
- `NCAA_INPUT_REFERENCE.md`: valid NCAA inputs and examples
- `plan.md`: implementation blueprint / reconstruction notes

## 13) Data Source and Caching

- ESPN endpoint base: `https://site.api.espn.com/apis/site/v2/sports`
- Scoreboard payloads cached via LEDMatrix `cache_manager`
- Logo images cached in:
  - `cache/team_logos/`
  - `cache/league_logos/`

## 14) Rebuild Notes

If you need to recreate this plugin exactly:

1. Keep endpoint mappings and league definitions identical.
2. Keep section order `LIVE -> UPCOMING -> FINAL`.
3. Keep NCAA filter precedence unchanged.
4. Keep no-games behavior per enabled league.
5. Keep current loop math (`ticker_width - display_width`) and non-wrapping frame crop behavior.
6. Keep custom-logo-only scaling behavior for `league_logo_scale`.
