# NCAA Input Reference

This file documents what values to enter for NCAA conference and team filters.

## Team Filters (`ncaaf_teams`, `ncaam_teams`)

Enter ESPN-style team abbreviations, for example:

- `UGA`
- `BAMA`
- `OSU`
- `UNC`
- `DUKE`

Notes:

- Values are case-insensitive in config, but uppercase is recommended.
- You can enter either an array (`["UGA","BAMA"]`) or a comma-separated string (`"UGA, BAMA"`).
- Team filters take priority over conference and Top-25 filters.

How to find abbreviations:

1. Temporarily clear NCAA team/conference filters.
2. Let games render.
3. Use the abbreviations shown in the ticker itself for your desired schools.

Optional CLI method (today's games only):

```bash
curl -s "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=YYYYMMDD" \
  | jq -r '.events[].competitions[].competitors[].team.abbreviation' \
  | sort -u
```

```bash
curl -s "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates=YYYYMMDD" \
  | jq -r '.events[].competitions[].competitors[].team.abbreviation' \
  | sort -u
```

## NCAA Football Conference Values (`ncaaf_conferences`)

Use exactly one of these strings:

- `ACC`
- `AMERICAN ATHLETIC`
- `BIG 12`
- `BIG TEN`
- `C-USA`
- `INDEPENDENTS`
- `MAC`
- `MOUNTAIN WEST`
- `PAC-12`
- `SEC`
- `SUN BELT`
- `FCS INDEPENDENTS`
- `ASUN-WAC`
- `BIG SKY`
- `BIG SOUTH-OVC`
- `CAA`
- `FCS (IA) INDEPENDENTS`
- `IVY`
- `MEAC`
- `MISSOURI VALLEY`
- `NORTHEAST`
- `PATRIOT`
- `PIONEER`
- `SOCON`
- `SOUTHLAND`
- `SWAC`
- `UAC`

## NCAA Men's Basketball Conference Values (`ncaam_conferences`)

Use exactly one of these strings:

- `ACC`
- `AMERICA EAST`
- `AMERICAN ATHLETIC`
- `ATLANTIC 10`
- `ATLANTIC SUN`
- `BIG 12`
- `BIG EAST`
- `BIG SKY`
- `BIG SOUTH`
- `BIG TEN`
- `BIG WEST`
- `C-USA`
- `CAA`
- `HORIZON LEAGUE`
- `IVY`
- `MAAC`
- `MAC`
- `MEAC`
- `MISSOURI VALLEY`
- `MOUNTAIN WEST`
- `NORTHEAST`
- `OHIO VALLEY`
- `PATRIOT`
- `SEC`
- `SOCON`
- `SOUTHLAND`
- `SUMMIT LEAGUE`
- `SUN BELT`
- `SWAC`
- `WAC`
- `WEST COAST`

## Combined Conference + Top-25 Behavior

To include all conference games and Top-25 games outside those conferences:

```json
{
  "ncaa_top25_only": true,
  "ncaa_include_top25_with_conferences": true
}
```

If `ncaa_include_top25_with_conferences` is `false`, conference filters remain conference-only.
