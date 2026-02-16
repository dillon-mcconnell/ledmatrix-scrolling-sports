"""
Scrolling Sports Scoreboard plugin for LEDMatrix.

Features:
- Multi-league ticker (NFL, NBA, NHL, MLB, NCAA MBB, NCAA football)
- Current-date-only game filtering
- Per-league include/exclude controls
- NCAA filters (teams, conferences, Top-25 mode)
- Team + league logos, game time/spread/scores
- Vegas mode integration via get_vegas_content()
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode


ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
DEFAULT_MODE_NAME = "scrolling_sports_vegas"


@dataclass(frozen=True)
class LeagueDefinition:
    key: str
    name: str
    sport_path: str
    league_path: str
    enabled_key: str
    is_ncaa: bool = False
    ncaa_kind: Optional[str] = None  # "football" or "basketball"
    default_group: str = ""


@dataclass
class GameEntry:
    event_id: str
    league_key: str
    state: str  # upcoming | live | final
    start_local: datetime
    short_status: str
    away_abbr: str
    home_abbr: str
    away_score: str
    home_score: str
    live_period_label: str
    live_clock: str
    away_rank: Optional[int]
    home_rank: Optional[int]
    away_conf: Optional[int]
    home_conf: Optional[int]
    away_conf_name: Optional[str]
    home_conf_name: Optional[str]
    away_logo_url: Optional[str]
    home_logo_url: Optional[str]
    spread_text: str


LEAGUES: Sequence[LeagueDefinition] = (
    LeagueDefinition("nfl", "NFL", "football", "nfl", "league_nfl_enabled"),
    LeagueDefinition("nba", "NBA", "basketball", "nba", "league_nba_enabled"),
    LeagueDefinition("nhl", "NHL", "hockey", "nhl", "league_nhl_enabled"),
    LeagueDefinition("mlb", "MLB", "baseball", "mlb", "league_mlb_enabled"),
    LeagueDefinition(
        "ncaam",
        "NCAA MBB",
        "basketball",
        "mens-college-basketball",
        "league_ncaam_enabled",
        is_ncaa=True,
        ncaa_kind="basketball",
        default_group="50",
    ),
    LeagueDefinition(
        "ncaaf",
        "NCAA FB",
        "football",
        "college-football",
        "league_ncaaf_enabled",
        is_ncaa=True,
        ncaa_kind="football",
        default_group="80",
    ),
)


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().upper().split())


NCAA_CONFERENCES: Dict[str, Dict[str, int]] = {
    "football": {
        _normalize_name("ACC"): 1,
        _normalize_name("AMERICAN ATHLETIC"): 151,
        _normalize_name("BIG 12"): 4,
        _normalize_name("BIG TEN"): 5,
        _normalize_name("C-USA"): 12,
        _normalize_name("INDEPENDENTS"): 18,
        _normalize_name("MAC"): 15,
        _normalize_name("MOUNTAIN WEST"): 17,
        _normalize_name("PAC-12"): 9,
        _normalize_name("SEC"): 8,
        _normalize_name("SUN BELT"): 37,
        _normalize_name("FCS INDEPENDENTS"): 40,
        _normalize_name("ASUN-WAC"): 48,
        _normalize_name("BIG SKY"): 20,
        _normalize_name("BIG SOUTH-OVC"): 73,
        _normalize_name("CAA"): 68,
        _normalize_name("FCS (IA) INDEPENDENTS"): 40,
        _normalize_name("IVY"): 22,
        _normalize_name("MEAC"): 16,
        _normalize_name("MISSOURI VALLEY"): 21,
        _normalize_name("NORTHEAST"): 24,
        _normalize_name("PATRIOT"): 25,
        _normalize_name("PIONEER"): 81,
        _normalize_name("SOCON"): 27,
        _normalize_name("SOUTHLAND"): 26,
        _normalize_name("SWAC"): 28,
        _normalize_name("UAC"): 98,
    },
    "basketball": {
        _normalize_name("ACC"): 2,
        _normalize_name("AMERICA EAST"): 1,
        _normalize_name("AMERICAN ATHLETIC"): 62,
        _normalize_name("ATLANTIC 10"): 3,
        _normalize_name("ATLANTIC SUN"): 17,
        _normalize_name("BIG 12"): 8,
        _normalize_name("BIG EAST"): 4,
        _normalize_name("BIG SKY"): 5,
        _normalize_name("BIG SOUTH"): 6,
        _normalize_name("BIG TEN"): 7,
        _normalize_name("BIG WEST"): 9,
        _normalize_name("C-USA"): 12,
        _normalize_name("CAA"): 10,
        _normalize_name("HORIZON LEAGUE"): 45,
        _normalize_name("IVY"): 13,
        _normalize_name("MAAC"): 14,
        _normalize_name("MAC"): 15,
        _normalize_name("MEAC"): 16,
        _normalize_name("MISSOURI VALLEY"): 18,
        _normalize_name("MOUNTAIN WEST"): 19,
        _normalize_name("NORTHEAST"): 20,
        _normalize_name("OHIO VALLEY"): 23,
        _normalize_name("PATRIOT"): 24,
        _normalize_name("SEC"): 23,
        _normalize_name("SOCON"): 26,
        _normalize_name("SOUTHLAND"): 27,
        _normalize_name("SUMMIT LEAGUE"): 25,
        _normalize_name("SUN BELT"): 37,
        _normalize_name("SWAC"): 28,
        _normalize_name("WAC"): 29,
        _normalize_name("WEST COAST"): 30,
    },
}


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ScrollingSportsPlugin(BasePlugin):
    modes = [DEFAULT_MODE_NAME]

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager: Any,
        cache_manager: Any,
        plugin_manager: Any,
    ) -> None:
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.display_width = int(getattr(display_manager, "width", 128))
        self.display_height = int(getattr(display_manager, "height", 32))

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LEDMatrix-ScrollingSports/0.1"})

        self.plugin_root = Path(__file__).resolve().parent
        self.cache_dir = self.plugin_root / "cache"
        self.team_logo_cache = self.cache_dir / "team_logos"
        self.league_logo_cache = self.cache_dir / "league_logos"
        self._ensure_cache_dirs()

        self._font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.load_default()
        self._body_font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.load_default()
        self._font_signature = ""

        self.enable_scrolling = bool(self.config.get("enable_scrolling", True))
        self._ticker_image: Optional[Image.Image] = None
        self._vegas_items: List[Image.Image] = []
        self._games_by_league: Dict[str, Dict[str, List[GameEntry]]] = {}
        self._league_logo_urls: Dict[str, Optional[str]] = {}
        self._live_games_count = 0
        self._scroll_offset = 0
        self._cycle_complete = False
        self._last_frame_ts = 0.0

        self._refresh_font()
        self.update()

    # ------------------------------------------------------------------
    # BasePlugin API
    # ------------------------------------------------------------------
    def update(self) -> None:
        self.enable_scrolling = bool(self.config.get("enable_scrolling", True))
        self._refresh_font()
        prior_ticker = self._ticker_image
        prior_offset = self._scroll_offset

        tz = self._get_timezone()
        today = datetime.now(tz).date()
        max_games = max(1, int(self.config.get("max_games_per_section", 8)))

        new_items: List[Image.Image] = []
        games_by_league: Dict[str, Dict[str, List[GameEntry]]] = {}
        league_logo_urls: Dict[str, Optional[str]] = {}
        live_count = 0

        for league in LEAGUES:
            if not bool(self.config.get(league.enabled_key, True)):
                continue

            payload = self._fetch_league_payload(league, today, tz)
            if not payload:
                continue

            events = payload.get("events", [])
            if not isinstance(events, list) or not events:
                continue

            parsed_games: List[GameEntry] = []
            for event in events:
                game = self._parse_event(event, league, tz)
                if not game:
                    continue
                if game.start_local.date() != today:
                    continue
                if not self._passes_ncaa_filters(game, league):
                    continue
                parsed_games.append(game)

            if not parsed_games:
                continue

            upcoming = sorted(
                (g for g in parsed_games if g.state == "upcoming"),
                key=lambda g: g.start_local,
            )[:max_games]
            live = sorted(
                (g for g in parsed_games if g.state == "live"),
                key=lambda g: g.start_local,
            )[:max_games]
            final = sorted(
                (g for g in parsed_games if g.state == "final"),
                key=lambda g: g.start_local,
                reverse=True,
            )[:max_games]

            if not (upcoming or live or final):
                continue

            live_count += len(live)
            games_by_league[league.key] = {"upcoming": upcoming, "live": live, "final": final}

            league_logo_url = self._extract_league_logo_url(payload)
            league_logo_urls[league.key] = league_logo_url

            league_items = self._build_league_items(
                league=league,
                upcoming=upcoming,
                live=live,
                final=final,
                league_logo_url=league_logo_url,
            )
            new_items.extend(league_items)

        # Keep current ticker if refresh failed transiently to avoid visible jumps/freezes.
        if not new_items and self._vegas_items:
            self.logger.debug("No fresh items returned; preserving previous ticker content")
            return

        self._games_by_league = games_by_league
        self._league_logo_urls = league_logo_urls
        self._live_games_count = live_count
        self._vegas_items = new_items
        self._ticker_image = self._compose_ticker_image(new_items)

        # Preserve scroll position proportionally across content refreshes.
        if self._ticker_image and prior_ticker and prior_ticker.width > 0:
            ratio = float(prior_offset % prior_ticker.width) / float(prior_ticker.width)
            mapped = int(ratio * self._ticker_image.width)
            self._scroll_offset = max(0, min(self._ticker_image.width - 1, mapped))
        else:
            self._scroll_offset = 0

        self._cycle_complete = False

    def display(self, force_clear: bool = False, display_mode: Optional[str] = None) -> bool:
        _ = display_mode

        if not self._ticker_image:
            self._render_empty_message(force_clear)
            return False

        now = time.time()
        min_delay = max(0.004, _safe_float(self.config.get("scroll_frame_delay", 0.02), 0.02))
        if now - self._last_frame_ts < min_delay:
            return True

        if force_clear:
            self.display_manager.clear()

        frame = self._render_viewport_from_ticker()
        self.display_manager.image = frame
        self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
        self.display_manager.update_display()

        scroll_step = max(1, int(self.config.get("scroll_speed_px", 1)))
        width = max(1, self._ticker_image.width)
        self._scroll_offset = (self._scroll_offset + scroll_step) % width

        self._last_frame_ts = now
        return True

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        if not self._vegas_items:
            return None
        return [img.copy() for img in self._vegas_items]

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_display_mode(self) -> VegasDisplayMode:
        configured = self.config.get("vegas_mode")
        if configured:
            return super().get_vegas_display_mode()
        return VegasDisplayMode.SCROLL

    def get_supported_vegas_modes(self) -> List[VegasDisplayMode]:
        return [VegasDisplayMode.SCROLL, VegasDisplayMode.FIXED_SEGMENT]

    def has_live_content(self) -> bool:
        return self._live_games_count > 0

    def get_live_modes(self) -> List[str]:
        return list(self.modes)

    def reset_cycle_state(self) -> None:
        self._cycle_complete = False
        self._scroll_offset = 0

    def is_cycle_complete(self) -> bool:
        # Keep this plugin continuously scrolling without cycle-based pauses.
        return False

    def supports_dynamic_duration(self) -> bool:
        # Explicitly disable dynamic-duration cycle handling to keep ticker smooth.
        return False

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self._refresh_font()
        self.update()

    def cleanup(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
        super().cleanup()

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update(
            {
                "live_games": self._live_games_count,
                "enabled_leagues": [
                    league.key for league in LEAGUES if bool(self.config.get(league.enabled_key, True))
                ],
                "league_game_counts": {
                    league_key: {
                        section: len(items)
                        for section, items in sections.items()
                    }
                    for league_key, sections in self._games_by_league.items()
                },
            }
        )
        return info

    # ------------------------------------------------------------------
    # Data fetch + parsing
    # ------------------------------------------------------------------
    def _fetch_league_payload(
        self,
        league: LeagueDefinition,
        target_date: datetime.date,
        tz: ZoneInfo,
    ) -> Optional[Dict[str, Any]]:
        date_token = target_date.strftime("%Y%m%d")
        params: Dict[str, Any] = {"dates": date_token, "limit": 500, "tz": str(tz)}

        if league.is_ncaa and league.ncaa_kind:
            self._apply_ncaa_query_filters(league, params)

        cache_key = self._build_cache_key(league.key, date_token, params)
        cache_ttl = max(30, int(self.config.get("update_interval", 120)))
        cached = self.cache_manager.get(cache_key, max_age=cache_ttl)
        if isinstance(cached, dict):
            return cached

        url = f"{ESPN_BASE}/{league.sport_path}/{league.league_path}/scoreboard"

        try:
            response = self.session.get(url, params=params, timeout=12)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                self.cache_manager.set(cache_key, payload)
                return payload
        except Exception as exc:
            self.logger.warning("Failed fetching %s scoreboard: %s", league.key, exc)

        stale = self.cache_manager.get(cache_key, max_age=86400)
        if isinstance(stale, dict):
            return stale
        return None

    def _apply_ncaa_query_filters(self, league: LeagueDefinition, params: Dict[str, Any]) -> None:
        if not league.ncaa_kind:
            return

        teams = set(
            self._normalize_team_filters(
                self._get_list_config("ncaaf_teams" if league.ncaa_kind == "football" else "ncaam_teams")
            )
        )
        conference_ids = self._selected_conference_ids(league.ncaa_kind)
        top25_only = bool(self.config.get("ncaa_top25_only", False))

        if teams:
            if league.default_group:
                params["groups"] = league.default_group
        elif conference_ids:
            if league.default_group:
                params["groups"] = league.default_group
        elif top25_only:
            params.pop("groups", None)
        elif league.default_group:
            params["groups"] = league.default_group

    def _parse_event(
        self,
        event: Dict[str, Any],
        league: LeagueDefinition,
        tz: ZoneInfo,
    ) -> Optional[GameEntry]:
        if not isinstance(event, dict):
            return None

        competitions = event.get("competitions", [])
        if not isinstance(competitions, list) or not competitions:
            return None
        competition = competitions[0] if isinstance(competitions[0], dict) else {}

        competitors = competition.get("competitors", [])
        if not isinstance(competitors, list) or len(competitors) < 2:
            return None

        away = self._find_competitor(competitors, "away")
        home = self._find_competitor(competitors, "home")
        if not away or not home:
            return None

        event_date = self._parse_event_datetime(event.get("date"))
        if not event_date:
            return None
        local_date = event_date.astimezone(tz)

        status_type = (((event.get("status") or {}).get("type") or {}) if isinstance(event.get("status"), dict) else {})
        state_value = str(status_type.get("state", "")).lower()
        if state_value == "in":
            state = "live"
        elif state_value == "post":
            state = "final"
        else:
            state = "upcoming"

        short_status = str(
            status_type.get("shortDetail")
            or status_type.get("detail")
            or status_type.get("description")
            or ""
        ).strip()
        if not short_status:
            short_status = "LIVE" if state == "live" else ("FINAL" if state == "final" else "UPCOMING")

        spread = self._extract_spread(event, competition)

        away_abbr = self._team_abbreviation(away)
        home_abbr = self._team_abbreviation(home)
        away_score = str(away.get("score", "0"))
        home_score = str(home.get("score", "0"))
        live_period_label, live_clock = self._extract_live_period_and_clock(event, status_type)

        return GameEntry(
            event_id=str(event.get("id", "")),
            league_key=league.key,
            state=state,
            start_local=local_date,
            short_status=short_status,
            away_abbr=away_abbr,
            home_abbr=home_abbr,
            away_score=away_score,
            home_score=home_score,
            live_period_label=live_period_label,
            live_clock=live_clock,
            away_rank=self._extract_rank(away),
            home_rank=self._extract_rank(home),
            away_conf=self._extract_conference_id(away),
            home_conf=self._extract_conference_id(home),
            away_conf_name=self._extract_conference_name(away),
            home_conf_name=self._extract_conference_name(home),
            away_logo_url=self._extract_team_logo_url(away),
            home_logo_url=self._extract_team_logo_url(home),
            spread_text=spread,
        )

    def _passes_ncaa_filters(self, game: GameEntry, league: LeagueDefinition) -> bool:
        if not league.is_ncaa or not league.ncaa_kind:
            return True

        team_key = "ncaaf_teams" if league.ncaa_kind == "football" else "ncaam_teams"
        teams = set(self._normalize_team_filters(self._get_list_config(team_key)))
        if teams:
            return game.away_abbr.upper() in teams or game.home_abbr.upper() in teams

        conference_key = "ncaaf_conferences" if league.ncaa_kind == "football" else "ncaam_conferences"
        selected_conference_names = {_normalize_name(name) for name in self._get_list_config(conference_key)}
        conference_ids = self._selected_conference_ids(league.ncaa_kind)
        if conference_ids or selected_conference_names:
            id_match = (game.away_conf in conference_ids) or (game.home_conf in conference_ids)
            away_name = _normalize_name(game.away_conf_name) if game.away_conf_name else ""
            home_name = _normalize_name(game.home_conf_name) if game.home_conf_name else ""
            name_match = (away_name in selected_conference_names) or (home_name in selected_conference_names)
            return id_match or name_match

        top25_only = bool(self.config.get("ncaa_top25_only", False))
        if top25_only:
            return (
                (game.away_rank is not None and game.away_rank <= 25)
                or (game.home_rank is not None and game.home_rank <= 25)
            )

        return True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _build_league_items(
        self,
        league: LeagueDefinition,
        upcoming: List[GameEntry],
        live: List[GameEntry],
        final: List[GameEntry],
        league_logo_url: Optional[str],
    ) -> List[Image.Image]:
        items: List[Image.Image] = []

        items.append(self._render_league_header(league.name, league_logo_url))

        show_labels = bool(self.config.get("show_section_labels", True))

        if live:
            if show_labels:
                items.append(self._render_section_label("LIVE"))
            items.extend(self._render_game_card(game, "live") for game in live)

        if upcoming:
            if show_labels:
                items.append(self._render_section_label("UPCOMING"))
            items.extend(self._render_game_card(game, "upcoming") for game in upcoming)

        if final:
            if show_labels:
                items.append(self._render_section_label("FINAL"))
            items.extend(self._render_game_card(game, "final") for game in final)

        return items

    def _render_league_header(self, label: str, logo_url: Optional[str]) -> Image.Image:
        header_logo_size = max(10, int(self.config.get("header_logo_size_px", 16)))
        card_padding = max(0, int(self.config.get("card_padding_px", 4)))
        logo_gap = max(0, int(self.config.get("logo_gap_px", 3)))
        color = self._get_color("header_color", (255, 255, 255))

        text = f"{label}"
        text_w, text_h = self._measure_text(text)
        width = (card_padding * 2) + header_logo_size + logo_gap + text_w

        image = Image.new("RGB", (max(1, width), self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        logo = self._load_logo(logo_url, header_logo_size, self.league_logo_cache)
        logo_y = (self.display_height - header_logo_size) // 2
        if logo:
            image.paste(logo, (card_padding, logo_y), logo)
        else:
            draw.rectangle(
                [card_padding, logo_y, card_padding + header_logo_size - 1, logo_y + header_logo_size - 1],
                outline=color,
            )

        text_y = min(max(0, (self.display_height - text_h) // 2 + 2), max(0, self.display_height - text_h))
        draw.text((card_padding + header_logo_size + logo_gap, text_y), text, font=self._font, fill=color)
        return image

    def _render_section_label(self, label: str) -> Image.Image:
        card_padding = max(0, int(self.config.get("card_padding_px", 4)))
        color = self._get_color("header_color", (255, 255, 255))
        text_w, text_h = self._measure_text(label)
        width = max(1, text_w + (card_padding * 2))
        image = Image.new("RGB", (width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        y = min(max(0, (self.display_height - text_h) // 2 + 2), max(0, self.display_height - text_h))
        draw.text((card_padding, y), label, font=self._font, fill=color)
        return image

    def _render_game_card(self, game: GameEntry, state: str) -> Image.Image:
        # Manual override per request: render game logos very large on the panel.
        # For a 32px-tall matrix this targets ~26px logos (about 80% height).
        logo_size = max(18, min(self.display_height - 2, int(round(self.display_height * 0.82))))
        card_padding = max(0, int(self.config.get("card_padding_px", 4)))
        logo_gap = max(0, int(self.config.get("logo_gap_px", 3)))
        column_gap = max(2, logo_gap + 1)
        body_font = self._body_font

        away_logo = self._load_logo(game.away_logo_url, logo_size, self.team_logo_cache)
        home_logo = self._load_logo(game.home_logo_url, logo_size, self.team_logo_cache)

        if state in {"live", "final"}:
            away_name = game.away_abbr
            home_name = game.home_abbr
        else:
            away_name = self._decorate_team(game.away_abbr, game.away_rank)
            home_name = self._decorate_team(game.home_abbr, game.home_rank)
        team_color = self._get_color("text_color", (255, 255, 255))

        info_top, info_bottom, info_top_color, info_bottom_color = self._get_compact_info_lines(game, state)

        names_width = max(
            self._measure_text(away_name, font=body_font)[0],
            self._measure_text(home_name, font=body_font)[0],
        )
        info_width = max(
            self._measure_text(info_top, font=body_font)[0],
            self._measure_text(info_bottom, font=body_font)[0],
        )

        at_symbol = "@"
        at_width, at_height = self._measure_text(at_symbol, font=body_font)
        logo_cluster_width = logo_size + logo_gap + at_width + logo_gap + logo_size

        width = (
            (card_padding * 2)
            + logo_cluster_width
            + column_gap
            + names_width
            + column_gap
            + info_width
        )
        image = Image.new("RGB", (max(1, width), self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        logo_y = (self.display_height - logo_size) // 2
        away_logo_x = card_padding
        at_x = away_logo_x + logo_size + logo_gap
        home_logo_x = at_x + at_width + logo_gap

        if away_logo:
            image.paste(away_logo, (away_logo_x, logo_y), away_logo)
        else:
            self._draw_logo_fallback(draw, away_logo_x, logo_y, logo_size, game.away_abbr)

        if home_logo:
            image.paste(home_logo, (home_logo_x, logo_y), home_logo)
        else:
            self._draw_logo_fallback(draw, home_logo_x, logo_y, logo_size, game.home_abbr)

        at_y = max(0, (self.display_height - at_height) // 2)
        draw.text((at_x, at_y), at_symbol, font=body_font, fill=self._get_color("header_color", (255, 255, 255)))

        # Keep body text compact and vertically centered.
        line_h = max(
            self._measure_text("ABC", font=body_font)[1],
            self._measure_text("123", font=body_font)[1],
        )
        line_gap = max(1, line_h // 4)
        text_block_h = (line_h * 2) + line_gap
        line1_y = max(0, (self.display_height - text_block_h) // 2)
        line2_y = line1_y + line_h + line_gap

        names_x = card_padding + logo_cluster_width + column_gap
        info_x = names_x + names_width + column_gap

        away_name = self._fit_text_to_width(away_name, names_width, font=body_font)
        home_name = self._fit_text_to_width(home_name, names_width, font=body_font)
        info_top = self._fit_text_to_width(info_top, info_width, font=body_font)
        info_bottom = self._fit_text_to_width(info_bottom, info_width, font=body_font)

        draw.text((names_x, line1_y), away_name, font=body_font, fill=team_color)
        draw.text((names_x, line2_y), home_name, font=body_font, fill=team_color)

        draw.text((info_x, line1_y), info_top, font=body_font, fill=info_top_color)
        draw.text((info_x, line2_y), info_bottom, font=body_font, fill=info_bottom_color)

        return image

    def _compose_ticker_image(self, items: Sequence[Image.Image]) -> Optional[Image.Image]:
        if not items:
            return None

        segment_spacing = max(0, int(self.config.get("segment_spacing_px", 12)))
        section_spacing = max(0, int(self.config.get("section_spacing_px", 20)))
        spacing = segment_spacing + section_spacing
        # Small trailing gap before loop restart (not a full-screen pause).
        loop_gap = self.display_width

        total_width = 0
        for i, item in enumerate(items):
            total_width += item.width
            if i < len(items) - 1:
                total_width += spacing
        total_width += loop_gap

        ticker = Image.new("RGB", (max(self.display_width, total_width), self.display_height), (0, 0, 0))
        x = 0
        for i, item in enumerate(items):
            ticker.paste(item, (x, 0))
            x += item.width
            if i < len(items) - 1:
                x += spacing
        return ticker

    def _render_viewport_from_ticker(self) -> Image.Image:
        assert self._ticker_image is not None
        ticker = self._ticker_image

        if ticker.width <= self.display_width:
            frame = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))
            frame.paste(ticker, (0, 0))
            return frame

        left = int(self._scroll_offset) % ticker.width
        right = left + self.display_width
        frame = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))

        if right <= ticker.width:
            crop = ticker.crop((left, 0, right, self.display_height))
            frame.paste(crop, (0, 0))
            return frame

        first = ticker.crop((left, 0, ticker.width, self.display_height))
        frame.paste(first, (0, 0))
        remainder = right - ticker.width
        second = ticker.crop((0, 0, remainder, self.display_height))
        frame.paste(second, (first.width, 0))
        return frame

    def _render_empty_message(self, force_clear: bool) -> None:
        if force_clear:
            self.display_manager.clear()
        message = "NO GAMES TODAY"
        image = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        w, h = self._measure_text(message)
        x = max(0, (self.display_width - w) // 2)
        y = max(0, (self.display_height - h) // 2)
        draw.text((x, y), message, font=self._font, fill=self._get_color("text_color", (255, 255, 255)))
        self.display_manager.image = image
        self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
        self.display_manager.update_display()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_timezone(self) -> ZoneInfo:
        tz_name = str(self.config.get("timezone", "America/New_York"))
        try:
            return ZoneInfo(tz_name)
        except Exception:
            self.logger.warning("Invalid timezone '%s', falling back to UTC", tz_name)
            return ZoneInfo("UTC")

    def _build_cache_key(self, league_key: str, date_token: str, params: Dict[str, Any]) -> str:
        payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
        return f"{self.plugin_id}_{league_key}_{date_token}_{digest}"

    def _find_competitor(self, competitors: Sequence[Dict[str, Any]], side: str) -> Optional[Dict[str, Any]]:
        for comp in competitors:
            if str(comp.get("homeAway", "")).lower() == side:
                return comp
        return competitors[0] if competitors else None

    def _parse_event_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _extract_live_period_and_clock(
        self,
        event: Dict[str, Any],
        status_type: Dict[str, Any],
    ) -> Tuple[str, str]:
        status_obj = event.get("status") if isinstance(event.get("status"), dict) else {}

        short_detail = str(
            status_type.get("shortDetail")
            or status_type.get("detail")
            or status_type.get("description")
            or ""
        ).upper().strip()

        period_label = ""
        period_value = _safe_int(status_obj.get("period"))
        if period_value is not None and period_value > 0:
            period_label = self._ordinal_label(period_value)

        # Fallback: parse explicit period token from short detail (e.g. "2ND", "3RD").
        if not period_label:
            period_match = re.search(r"\b(\d{1,2})(ST|ND|RD|TH)\b", short_detail)
            if period_match:
                period_label = f"{period_match.group(1)}{period_match.group(2)}"

        # Normalize common non-numeric states for readability.
        if not period_label:
            if "HALFTIME" in short_detail:
                period_label = "HALF"
            elif "OT" in short_detail:
                period_label = "OT"
            elif "LIVE" in short_detail:
                period_label = "LIVE"

        clock = str(status_obj.get("displayClock") or "").strip()
        # Fallback: parse clock from short detail when displayClock is absent.
        if not clock:
            clock_match = re.search(r"\b(\d{1,2}:\d{2}(?:\.\d)?)\b", short_detail)
            if clock_match:
                clock = clock_match.group(1)

        # Avoid noisy zero clocks.
        if clock in {"0:00", "00:00", "0:00.0", "00:00.0"}:
            clock = ""

        return period_label, clock

    def _ordinal_label(self, value: int) -> str:
        if 10 <= (value % 100) <= 20:
            suffix = "TH"
        else:
            suffix = {1: "ST", 2: "ND", 3: "RD"}.get(value % 10, "TH")
        return f"{value}{suffix}"

    def _extract_spread(self, event: Dict[str, Any], competition: Dict[str, Any]) -> str:
        sources: List[Any] = []
        sources.append(competition.get("odds"))
        sources.append(event.get("odds"))
        for source in sources:
            if not isinstance(source, list) or not source:
                continue
            odds = source[0]
            if not isinstance(odds, dict):
                continue
            details = odds.get("details")
            if details:
                return f"Spread {str(details)}"
            spread = odds.get("spread")
            if spread is not None:
                try:
                    spread_value = float(spread)
                    return f"Spread {spread_value:+.1f}"
                except (TypeError, ValueError):
                    return f"Spread {spread}"
        return "Spread N/A"

    def _extract_rank(self, competitor: Dict[str, Any]) -> Optional[int]:
        curated = competitor.get("curatedRank")
        if isinstance(curated, dict):
            rank = _safe_int(curated.get("current"))
            if rank and rank > 0:
                return rank
        rank = _safe_int(competitor.get("rank"))
        if rank and rank > 0:
            return rank
        return None

    def _extract_conference_id(self, competitor: Dict[str, Any]) -> Optional[int]:
        team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}

        for candidate in (team.get("conferenceId"), competitor.get("conferenceId")):
            conf = _safe_int(candidate)
            if conf is not None:
                return conf

        groups = team.get("groups")
        if isinstance(groups, list) and groups:
            first_group = groups[0] if isinstance(groups[0], dict) else {}
            conf = _safe_int(first_group.get("id"))
            if conf is not None:
                return conf
        return None

    def _extract_conference_name(self, competitor: Dict[str, Any]) -> Optional[str]:
        team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}

        conference = team.get("conference")
        if isinstance(conference, dict):
            for key in ("shortName", "abbreviation", "name", "displayName"):
                value = conference.get(key)
                if value:
                    return str(value)

        groups = team.get("groups")
        if isinstance(groups, list) and groups:
            first_group = groups[0] if isinstance(groups[0], dict) else {}
            for key in ("shortName", "abbreviation", "name", "displayName"):
                value = first_group.get(key)
                if value:
                    return str(value)
        return None

    def _extract_team_logo_url(self, competitor: Dict[str, Any]) -> Optional[str]:
        team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
        logos = team.get("logos")
        if isinstance(logos, list) and logos:
            first = logos[0] if isinstance(logos[0], dict) else {}
            href = first.get("href")
            if href:
                return str(href)
        logo = team.get("logo")
        if logo:
            return str(logo)
        return None

    def _extract_league_logo_url(self, payload: Dict[str, Any]) -> Optional[str]:
        leagues = payload.get("leagues")
        if not isinstance(leagues, list) or not leagues:
            return None
        first_league = leagues[0] if isinstance(leagues[0], dict) else {}
        logos = first_league.get("logos")
        if isinstance(logos, list) and logos:
            first = logos[0] if isinstance(logos[0], dict) else {}
            href = first.get("href")
            if href:
                return str(href)
        return None

    def _team_abbreviation(self, competitor: Dict[str, Any]) -> str:
        team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
        for key in ("abbreviation", "shortDisplayName", "displayName", "name"):
            value = team.get(key)
            if value:
                return str(value).upper()
        return "TEAM"

    def _decorate_team(self, abbr: str, rank: Optional[int]) -> str:
        if rank and rank <= 25:
            return f"#{rank} {abbr}"
        return abbr

    def _format_upcoming_line(self, game: GameEntry) -> str:
        local_time = game.start_local
        hour = local_time.strftime("%I").lstrip("0") or "12"
        minute = local_time.strftime("%M")
        ampm = local_time.strftime("%p")
        time_text = f"{hour}:{minute}{ampm}"
        spread = game.spread_text
        return f"{time_text} {spread}"

    def _get_compact_info_lines(
        self,
        game: GameEntry,
        state: str,
    ) -> Tuple[str, str, Tuple[int, int, int], Tuple[int, int, int]]:
        if state == "upcoming":
            return (
                self._format_time_compact(game.start_local),
                self._format_spread_compact(game),
                self._get_color("upcoming_color", (255, 215, 0)),
                self._get_color("spread_color", (120, 200, 255)),
            )
        if state == "live":
            top = f"{game.away_score}"
            if game.live_period_label:
                top = f"{top} {game.live_period_label}"

            bottom = f"{game.home_score}"
            if game.live_clock:
                bottom = f"{bottom} {game.live_clock}"

            return (
                top,
                bottom,
                self._get_color("live_color", (0, 255, 120)),
                self._get_color("live_color", (0, 255, 120)),
            )
        return (
            f"{game.away_score}",
            f"{game.home_score}",
            self._get_color("final_color", (180, 180, 180)),
            self._get_color("final_color", (180, 180, 180)),
        )

    def _format_time_compact(self, dt: datetime) -> str:
        hour = dt.strftime("%I").lstrip("0") or "12"
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p")
        return f"{hour}:{minute}{ampm[:1]}"

    def _format_spread_compact(self, game: GameEntry) -> str:
        spread_text = str(game.spread_text or "").strip()
        if not spread_text:
            return "N/A"

        # Normalize strings like "Spread MIA -1.5" -> "MIA -1.5".
        if spread_text.lower().startswith("spread"):
            spread_text = spread_text[6:].strip()

        upper_spread = spread_text.upper()
        if not spread_text or upper_spread in {"N/A", "NONE"}:
            return "N/A"
        if "PICK" in upper_spread or upper_spread == "PK":
            return "PK"

        line_match = re.search(r"([+-]?\d+(?:\.\d+)?)", spread_text)
        if not line_match:
            return self._fit_text_to_width(upper_spread, 40, font=self._body_font)

        line_value = line_match.group(1)
        if not line_value.startswith(("+", "-")):
            line_value = f"+{line_value}"

        favored_text = spread_text[: line_match.start()].strip()
        favored_abbr = self._spread_favored_abbr(favored_text, game)
        if favored_abbr:
            return f"{favored_abbr} {line_value}"
        return line_value

    def _spread_favored_abbr(self, favored_text: str, game: GameEntry) -> str:
        if not favored_text:
            return ""

        normalized = re.sub(r"[^A-Za-z0-9 ]", " ", favored_text).upper()
        normalized = " ".join(normalized.split())
        if not normalized:
            return ""

        away = game.away_abbr.upper()
        home = game.home_abbr.upper()
        if away and away in normalized:
            return away
        if home and home in normalized:
            return home

        tokens = [
            token for token in normalized.split()
            if token and token not in {"THE", "OF", "UNIVERSITY", "STATE"}
        ]
        if not tokens:
            return ""

        if len(tokens) == 1:
            return tokens[0][:3]
        return "".join(token[0] for token in tokens[:3])[:3]

    def _compact_status(self, status: str) -> str:
        text = str(status or "").upper().strip()
        if not text:
            return "LIVE"
        text = text.replace("FINAL", "FNL")
        return text

    def _selected_conference_ids(self, kind: str) -> set[int]:
        key = "ncaaf_conferences" if kind == "football" else "ncaam_conferences"
        selected = self._get_list_config(key)
        lookup = NCAA_CONFERENCES.get(kind, {})

        ids: set[int] = set()
        for entry in selected:
            normalized = _normalize_name(str(entry))
            conf_id = lookup.get(normalized)
            if conf_id is not None:
                ids.add(conf_id)
        return ids

    def _normalize_team_filters(self, teams: Iterable[str]) -> List[str]:
        out: List[str] = []
        for team in teams:
            cleaned = str(team).strip().upper()
            if cleaned:
                out.append(cleaned)
        return out

    def _get_list_config(self, key: str) -> List[str]:
        value = self.config.get(key, [])
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def _refresh_font(self) -> None:
        family = str(self.config.get("font_family", "press_start_2p"))
        size = max(5, int(self.config.get("font_size", 8)))
        path = str(self.config.get("font_path", "")).strip()
        signature = f"{family}|{size}|{path}"
        if signature == self._font_signature:
            return

        # Keep header/league text at configured size, but force game-card body text smaller.
        self._font = self._load_font(family=family, size=size, explicit_path=path)
        body_size = max(4, size - 2)
        self._body_font = self._load_font(family=family, size=body_size, explicit_path=path)
        self._font_signature = signature

    def _load_font(
        self,
        family: str,
        size: int,
        explicit_path: str,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidate_paths: List[Path] = []

        if explicit_path:
            p = Path(explicit_path)
            if p.is_absolute():
                candidate_paths.append(p)
            else:
                candidate_paths.append(self.plugin_root / p)
                candidate_paths.append(Path.cwd() / p)

        if family == "pixel4x6":
            candidate_paths.append(Path.cwd() / "assets" / "fonts" / "4x6-font.ttf")
            candidate_paths.append(self.plugin_root / "assets" / "fonts" / "4x6-font.ttf")
        elif family == "press_start_2p":
            candidate_paths.append(Path.cwd() / "assets" / "fonts" / "PressStart2P-Regular.ttf")
            candidate_paths.append(self.plugin_root / "assets" / "fonts" / "PressStart2P-Regular.ttf")

        for path in candidate_paths:
            try:
                if path.exists():
                    return ImageFont.truetype(str(path), size)
            except Exception:
                continue

        if family == "pil_default":
            return ImageFont.load_default()

        fallback = getattr(self.display_manager, "small_font", None)
        if fallback:
            return fallback
        return ImageFont.load_default()

    def _measure_text(
        self,
        text: str,
        font: Optional[ImageFont.FreeTypeFont | ImageFont.ImageFont] = None,
    ) -> Tuple[int, int]:
        probe = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(probe)
        use_font = font or self._font
        try:
            bbox = draw.textbbox((0, 0), text, font=use_font)
            return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])
        except Exception:
            return (len(text) * 6, 8)

    def _fit_text_to_width(
        self,
        text: str,
        max_width: int,
        font: Optional[ImageFont.FreeTypeFont | ImageFont.ImageFont] = None,
    ) -> str:
        if max_width <= 0:
            return ""
        candidate = text
        w, _ = self._measure_text(candidate, font=font)
        if w <= max_width:
            return candidate
        ellipsis = "..."
        for cut in range(len(text), 0, -1):
            candidate = text[:cut].rstrip() + ellipsis
            w, _ = self._measure_text(candidate, font=font)
            if w <= max_width:
                return candidate
        return ellipsis

    def _get_color(self, key: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        raw = self.config.get(key, default)
        if isinstance(raw, (list, tuple)) and len(raw) >= 3:
            out = []
            for i in range(3):
                try:
                    out.append(max(0, min(255, int(raw[i]))))
                except (TypeError, ValueError):
                    out.append(default[i])
            return (out[0], out[1], out[2])
        if isinstance(raw, str):
            parts = [part.strip() for part in raw.split(",")]
            if len(parts) >= 3:
                try:
                    return (
                        max(0, min(255, int(parts[0]))),
                        max(0, min(255, int(parts[1]))),
                        max(0, min(255, int(parts[2]))),
                    )
                except (TypeError, ValueError):
                    return default
        return default

    def _ensure_cache_dirs(self) -> None:
        for directory in (self.cache_dir, self.team_logo_cache, self.league_logo_cache):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def _load_logo(self, url: Optional[str], size: int, cache_dir: Path) -> Optional[Image.Image]:
        if not url:
            return None
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".png"
        cache_path = cache_dir / key

        if cache_path.exists():
            try:
                with Image.open(cache_path) as image:
                    return self._prepare_logo_image(image, size)
            except Exception:
                pass

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as image:
                prepared = self._prepare_logo_image(image, size)
                if prepared:
                    try:
                        prepared.save(cache_path, format="PNG")
                    except Exception:
                        pass
                return prepared
        except Exception:
            return None

    def _prepare_logo_image(self, image: Image.Image, size: int) -> Optional[Image.Image]:
        try:
            source = image.convert("RGBA")
            # Trim transparent whitespace so logos use their full allotted size.
            alpha = source.getchannel("A")
            bbox = alpha.getbbox()
            if bbox:
                source = source.crop(bbox)
            source.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            x = (size - source.width) // 2
            y = (size - source.height) // 2
            canvas.paste(source, (x, y), source)
            return canvas
        except Exception:
            return None

    def _draw_logo_fallback(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        size: int,
        team_abbr: str,
    ) -> None:
        border = self._get_color("header_color", (255, 255, 255))
        draw.rectangle([x, y, x + size - 1, y + size - 1], outline=border)
        short = team_abbr[:2].upper()
        text_w, text_h = self._measure_text(short, font=self._body_font)
        tx = x + max(0, (size - text_w) // 2)
        ty = y + max(0, (size - text_h) // 2)
        draw.text((tx, ty), short, font=self._body_font, fill=border)

