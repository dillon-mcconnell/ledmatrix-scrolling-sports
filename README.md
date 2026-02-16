# Scrolling Sports Scoreboard (LEDMatrix Plugin)

Vegas-style scrolling sports plugin for LEDMatrix with configurable leagues, NCAA filters, logos, scores, start times, and betting spread text.

## Features

- Supported leagues:
  - NFL
  - NBA
  - NHL
  - MLB
  - English Premier League (EPL)
  - Spanish La Liga
  - German Bundesliga
  - Italian Serie A
  - French Ligue 1
  - MLS
  - UEFA Champions League
  - NCAA Men's Basketball
  - NCAA Football
- For NCAA leagues:
  - Filter by conferences
  - Filter by specific team abbreviations
  - Optional Top-25-only mode
  - Optional conference OR Top-25 combined mode
- Shows only games for the current date (using configured timezone).
- If an enabled league has no games that day, it still appears with `NO GAMES TODAY`.
- Per-league sequence:
  - League header/logo
  - Upcoming games
  - Live games
  - Final games
- Web UI configurable:
  - Included leagues
  - Font family/size/path
  - Text colors
  - Scroll speed
  - Layout spacing/positions
- Vegas mode ready:
  - `get_vegas_content_type()` returns `multi`
  - `get_vegas_display_mode()` defaults to `scroll`

## Files

- `manifest.json`
- `config_schema.json`
- `manager.py`

## Install Into LEDMatrix

1. Keep this repository outside your LEDMatrix repo (recommended).
2. Link it into LEDMatrix's plugin directory.

If your LEDMatrix `plugin_system.plugins_directory` is `plugin-repos` (default in `config/config.template.json`):

```bash
cd /path/to/LEDMatrix
ln -s /path/to/scrolling-sports plugin-repos/scrolling-sports
```

Or copy it directly:

```bash
cp -R /path/to/scrolling-sports /path/to/LEDMatrix/plugin-repos/scrolling-sports
```

3. Add plugin config in LEDMatrix `config/config.json`:

```json
{
  "scrolling-sports": {
    "enabled": true,
    "display_duration": 20,
    "timezone": "America/New_York",
    "league_nfl_enabled": true,
    "league_nba_enabled": true,
    "league_nhl_enabled": true,
    "league_mlb_enabled": true,
    "league_epl_enabled": false,
    "league_laliga_enabled": false,
    "league_bundesliga_enabled": false,
    "league_seriea_enabled": false,
    "league_ligue1_enabled": false,
    "league_mls_enabled": false,
    "league_ucl_enabled": false,
    "league_order": ["nfl", "nba", "epl", "ncaam", "ncaaf"],
    "league_ncaam_enabled": true,
    "league_ncaaf_enabled": true,
    "ncaa_top25_only": false,
    "ncaa_include_top25_with_conferences": false,
    "ncaaf_conferences": ["SEC", "BIG TEN"],
    "ncaam_conferences": ["SEC", "ACC"],
    "ncaaf_teams": [],
    "ncaam_teams": [],
    "scroll_speed_px": 1
  }
}
```

4. Restart LEDMatrix service.

## NCAA Filter Behavior

Filter precedence:

1. Team filters (`ncaaf_teams` / `ncaam_teams`) always win.
2. If team filters are empty and conference filters are set:
   - default: conference-only matching
   - if `ncaa_top25_only=true` and `ncaa_include_top25_with_conferences=true`:
     - include games that match conference OR include a Top-25 team
3. If teams/conferences are empty and `ncaa_top25_only=true`: Top-25 only.
4. If all filters are empty: include all games for the enabled NCAA leagues.

## NCAA Input Reference

Use this file for exact conference values and team-entry guidance:

- `NCAA_INPUT_REFERENCE.md`

## Notes

- Data source: ESPN scoreboard endpoints.
- Spread data depends on what ESPN provides for a game. If unavailable, the plugin displays `Spread N/A`.
- Logos are cached under `cache/` in this plugin directory.
