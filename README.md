# Scrolling Sports Scoreboard (LEDMatrix Plugin)

Vegas-style scrolling sports plugin for LEDMatrix with configurable leagues, NCAA filters, logos, scores, start times, and betting spread text.

## Features

- Supported leagues:
  - NFL
  - NBA
  - NHL
  - MLB
  - NCAA Men's Basketball
  - NCAA Football
- For NCAA leagues:
  - Filter by conferences
  - Filter by specific team abbreviations
  - Optional Top-25-only mode
- Shows only games for the current date (using configured timezone).
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
    "league_ncaam_enabled": true,
    "league_ncaaf_enabled": true,
    "ncaa_top25_only": false,
    "ncaaf_conferences": ["SEC", "BIG TEN"],
    "ncaam_conferences": ["SEC", "ACC"],
    "ncaaf_teams": [],
    "ncaam_teams": [],
    "scroll_speed_px": 1
  }
}
```

4. Restart LEDMatrix service.

## Notes

- Data source: ESPN scoreboard endpoints.
- Spread data depends on what ESPN provides for a game. If unavailable, the plugin displays `Spread N/A`.
- Logos are cached under `cache/` in this plugin directory.
