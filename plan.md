# Scrolling Sports Plugin Plan and Rebuild Blueprint

This file is now the implementation blueprint for the current plugin state.
Use it as the source of truth to recreate the plugin behavior 1:1.

## 1) Final Product Definition

Plugin id: `scrolling-sports`  
Host system: LEDMatrix (ChuckBuilds)  
Display style: Vegas-style horizontal ticker (continuous scroll)  
Data source: ESPN scoreboard endpoints  
Primary goal: One ticker that can show multiple sports leagues in configurable order, with league headers and compact game cards.

## 2) Supported Leagues (Current)

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
- NCAA Men's Basketball
- NCAA Football

## 3) Core Runtime Behavior

1. On each update cycle, plugin fetches data for enabled leagues only.
2. It filters games to current date in configured timezone (`timezone`).
3. For each league it builds sections in this order:
   - `LIVE`
   - `UPCOMING`
   - `FINAL`
4. If no games survive filtering for an enabled league:
   - when `show_no_games_today=true`, render league header + `NO GAMES TODAY`
   - when `show_no_games_today=false`, skip that league in the ticker
5. League output order is controlled by `league_order`.
6. Omitted league keys in `league_order` are appended automatically in default order.
7. Ticker loops continuously (no cycle-complete pause).

## 4) Per-Game Card Layout Spec (Current)

Single card horizontal structure:

`[Away Logo] @ [Home Logo] | [Away/Home Abbr Stack] | [Info Stack]`

Logo behavior:

- Team logos are intentionally rendered very large (about 82% of display height).
- This is currently hardcoded in `manager.py` for readability.

Names column:

- Away team abbreviation on top line.
- Home team abbreviation on bottom line.
- For upcoming games only, Top-25 rank is prefixed (example `#12 DUKE`).
- For live/final games, no rank prefix (plain abbreviation).

Info column by game state:

- Upcoming:
  - Top line: start time compact format (`7:30P`)
  - Bottom line: compact spread (`BAMA -3.5`, `PK`, or `N/A`)
- Live:
  - Top line: away score + period (`74 2ND`)
  - Bottom line: home score + clock (`71 5:45`)
  - Score/period block is left-aligned with fixed score-column width to avoid shift between single/double digit scores.
  - OT normalization applies for period-based sports (for example CBB period 3 -> `OT`, football period 5 -> `OT`).
  - Soccer remains minute-based and is intentionally not remapped to `OT`.
- Final:
  - Top line: away score + `FINAL` (`77 FINAL`)
  - Bottom line: home score (`73`)

## 5) League Header and Logo Rules

Header card:

- League logo on left, league label text on right.
- Header text stays at configured main font size.
- League header vertical position includes a +2 pixel baseline adjustment for visual centering.

Logo source priority:

1. `league_logo_overrides[league_key]` (custom upload/path/url)
2. ESPN league logo from payload
3. Fallback outlined placeholder if none loads

Custom logo scaling:

- `league_logo_scale` applies only to custom overrides.
- ESPN logos ignore `league_logo_scale` and use `header_logo_size_px`.
- Custom logo is centered inside scaled slot to avoid drift.

## 6) NCAA Filtering Logic (Exact Precedence)

For each NCAA game:

1. Team filters win:
   - `ncaaf_teams` / `ncaam_teams`
2. Else if conference filters exist:
   - Match by conference id or conference name
   - If `ncaa_top25_only=true` and `ncaa_include_top25_with_conferences=true`:
     - Include `(conference match) OR (Top-25 game)`
   - Otherwise conference-only
3. Else if `ncaa_top25_only=true`:
   - Top-25 games only
4. Else:
   - Include all NCAA games

Reference values and examples:

- `NCAA_INPUT_REFERENCE.md`

## 7) Sorting and Section Ordering

Within each league:

- Live games: sorted by `start_local` ascending
- Upcoming games: sorted by `start_local` ascending
- Final games: sorted by `start_local` descending
- Truncation: `max_games_per_section`
- Section order in render output: `LIVE`, then `UPCOMING`, then `FINAL`

## 8) Loop and Scroll Mechanics (Current)

Ticker composition:

- All rendered items are stitched into one wide strip.
- Inter-item spacing = `segment_spacing_px + section_spacing_px`.
- A trailing blank gap is added equal to display width.

Viewport render:

- Plugin crops from `scroll_offset` for current frame.
- It does **not** wrap within the same frame when reaching the right edge.
- Tail is shown with blank space; next frame cycle resumes from offset wrap.

Loop width rule:

- Effective loop width is `ticker_width - display_width` (early restart by one screen).
- Purpose is to avoid re-showing beginning content before true cycle restart.

Cycle handling:

- `is_cycle_complete()` always returns `False`.
- `supports_dynamic_duration()` returns `False`.
- This keeps scrolling continuous and avoids cycle pause semantics.

## 9) Vegas Integration

- `get_vegas_content_type()` returns `multi`
- Default `get_vegas_display_mode()` is `scroll`
- Supported Vegas modes:
  - `scroll`
  - `fixed_segment`

Notes:

- Plugin can render through its own `display()` path, but in Vegas mode global Vegas settings also affect perceived scroll behavior.

## 10) Config Surface (High-Value Keys)

Behavior/data:

- `timezone`
- `update_interval`
- `max_games_per_section`
- `show_section_labels`
- `show_no_games_today`
- `league_order`
- `league_*_enabled`
- `ncaa_top25_only`
- `ncaa_include_top25_with_conferences`
- `ncaaf_conferences`, `ncaam_conferences`
- `ncaaf_teams`, `ncaam_teams`

Visual/layout:

- `font_family`, `font_size`, `font_path`
- `text_color`, `upcoming_color`, `live_color`, `final_color`, `spread_color`, `header_color`
- `segment_spacing_px`, `section_spacing_px`, `card_padding_px`, `logo_gap_px`
- `header_logo_size_px`
- `league_logo_scale` (custom league logos only)

Config keys retained but currently not driving team logo size:

- `logo_size_px` (team logo size is currently hardcoded in renderer for large logos)

Upload config:

- `league_logo_overrides` uses file-upload widgets (array shape), plus supports direct string path/URL.

## 11) Files Required for Rebuild

- `manifest.json`
- `config_schema.json`
- `manager.py`
- `README.md`
- `NCAA_INPUT_REFERENCE.md`
- Optional local logo files:
  - `epl.png`, `ligue1.png`, `ncaaf.png`, `ncaam.png`, `uefa.png`

## 12) Rebuild Checklist (1:1 Replica)

1. Create plugin repo with same file names and manifest metadata.
2. Register config schema exactly as current fields and defaults.
3. Implement league definitions and ESPN endpoint mapping exactly.
4. Implement date filtering in configured timezone.
5. Implement NCAA filter precedence exactly as section 6.
6. Implement section order `LIVE -> UPCOMING -> FINAL`.
7. Implement no-games rendering per enabled league.
8. Implement card layout and text formatting exactly as section 4.
9. Implement custom league logo override parsing and fallback chain.
10. Implement ticker loop logic:
    - trailing blank gap
    - no same-frame wrap
    - early restart at `ticker_width - display_width`
11. Implement vegas hooks and continuous-cycle behavior.
12. Validate on 32x256 (64x4 chain) matrix and confirm smooth restart.

## 13) Source Inspiration Repos

- https://github.com/ChuckBuilds/ledmatrix-basketball-scoreboard
- https://github.com/ChuckBuilds/ledmatrix-football-scoreboard
- https://github.com/ChuckBuilds/ledmatrix-soccer-scoreboard
- https://github.com/ChuckBuilds/ledmatrix-baseball-scoreboard
- https://github.com/ChuckBuilds/ledmatrix-hockey-scoreboard
