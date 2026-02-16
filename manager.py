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

        self._games_by_league = games_by_league
        self._league_logo_urls = league_logo_urls
        self._live_games_count = live_count
        self._vegas_items = new_items
        self._ticker_image = self._compose_ticker_image(new_items)
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
        previous = self._scroll_offset
        width = max(1, self._ticker_image.width)
        self._scroll_offset = (self._scroll_offset + scroll_step) % width
        if self._scroll_offset < previous:
            self._cycle_complete = True

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
        return self._cycle_complete

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

        if upcoming:
            if show_labels:
                items.append(self._render_section_label("UPCOMING"))
            items.extend(self._render_game_card(game, "upcoming") for game in upcoming)

        if live:
            if show_labels:
                items.append(self._render_section_label("LIVE"))
            items.extend(self._render_game_card(game, "live") for game in live)

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

        text_y = max(0, (self.display_height - text_h) // 2)
        draw.text((card_padding + header_logo_size + logo_gap, text_y), text, font=self._font, fill=color)
        return image

    def _render_section_label(self, label: str) -> Image.Image:
        card_padding = max(0, int(self.config.get("card_padding_px", 4)))
        color = self._get_color("header_color", (255, 255, 255))
        text_w, text_h = self._measure_text(label)
        width = max(1, text_w + (card_padding * 2))
        image = Image.new("RGB", (width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        y = max(0, (self.display_height - text_h) // 2)
        draw.text((card_padding, y), label, font=self._font, fill=color)
        return image

    def _render_game_card(self, game: GameEntry, state: str) -> Image.Image:
        logo_size = max(8, int(self.config.get("logo_size_px", 14)))
        card_padding = max(0, int(self.config.get("card_padding_px", 4)))
        logo_gap = max(0, int(self.config.get("logo_gap_px", 3)))
        line1_y = int(self.config.get("line1_y", 3))
        line2_y = int(self.config.get("line2_y", 17))

        away_logo = self._load_logo(game.away_logo_url, logo_size, self.team_logo_cache)
        home_logo = self._load_logo(game.home_logo_url, logo_size, self.team_logo_cache)

        away_name = self._decorate_team(game.away_abbr, game.away_rank)
        home_name = self._decorate_team(game.home_abbr, game.home_rank)

        if state == "upcoming":
            line1 = f"{away_name} @ {home_name}"
            line2 = self._format_upcoming_line(game)
            line1_color = self._get_color("text_color", (255, 255, 255))
            line2_color = self._get_color("upcoming_color", (255, 215, 0))
        elif state == "live":
            line1 = f"{away_name} {game.away_score} - {game.home_score} {home_name}"
            line2 = game.short_status.upper()
            line1_color = self._get_color("text_color", (255, 255, 255))
            line2_color = self._get_color("live_color", (0, 255, 120))
        else:
            line1 = f"{away_name} {game.away_score} - {game.home_score} {home_name}"
            line2 = "FINAL"
            line1_color = self._get_color("text_color", (255, 255, 255))
            line2_color = self._get_color("final_color", (180, 180, 180))

        line1_w, _ = self._measure_text(line1)
        line2_w, _ = self._measure_text(line2)

        center_w = max(line1_w, line2_w)
        width = (card_padding * 2) + (logo_size * 2) + (logo_gap * 2) + center_w
        image = Image.new("RGB", (max(1, width), self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(image)

        logo_y = (self.display_height - logo_size) // 2
        left_logo_x = card_padding
        right_logo_x = width - card_padding - logo_size

        if away_logo:
            image.paste(away_logo, (left_logo_x, logo_y), away_logo)
        else:
            self._draw_logo_fallback(draw, left_logo_x, logo_y, logo_size, game.away_abbr)

        if home_logo:
            image.paste(home_logo, (right_logo_x, logo_y), home_logo)
        else:
            self._draw_logo_fallback(draw, right_logo_x, logo_y, logo_size, game.home_abbr)

        center_x = left_logo_x + logo_size + logo_gap
        max_center_width = max(1, right_logo_x - logo_gap - center_x)
        line1_clipped = self._fit_text_to_width(line1, max_center_width)
        line2_clipped = self._fit_text_to_width(line2, max_center_width)

        draw.text((center_x, line1_y), line1_clipped, font=self._font, fill=line1_color)
        draw.text((center_x, line2_y), line2_clipped, font=self._font, fill=line2_color)

        if state == "upcoming" and "SPREAD" in line2_clipped.upper():
            spread_color = self._get_color("spread_color", (120, 200, 255))
            draw.text((center_x, line2_y), line2_clipped, font=self._font, fill=spread_color)

        return image

    def _compose_ticker_image(self, items: Sequence[Image.Image]) -> Optional[Image.Image]:
        if not items:
            return None

        segment_spacing = max(0, int(self.config.get("segment_spacing_px", 12)))
        section_spacing = max(0, int(self.config.get("section_spacing_px", 20)))
        spacing = segment_spacing + section_spacing

        total_width = 0
        for i, item in enumerate(items):
            total_width += item.width
            if i < len(items) - 1:
                total_width += spacing
        total_width += self.display_width

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

        self._font = self._load_font(family=family, size=size, explicit_path=path)
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

    def _measure_text(self, text: str) -> Tuple[int, int]:
        probe = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(probe)
        try:
            bbox = draw.textbbox((0, 0), text, font=self._font)
            return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])
        except Exception:
            return (len(text) * 6, 8)

    def _fit_text_to_width(self, text: str, max_width: int) -> str:
        if max_width <= 0:
            return ""
        candidate = text
        w, _ = self._measure_text(candidate)
        if w <= max_width:
            return candidate
        ellipsis = "..."
        for cut in range(len(text), 0, -1):
            candidate = text[:cut].rstrip() + ellipsis
            w, _ = self._measure_text(candidate)
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
        text_w, text_h = self._measure_text(short)
        tx = x + max(0, (size - text_w) // 2)
        ty = y + max(0, (size - text_h) // 2)
        draw.text((tx, ty), short, font=self._font, fill=border)
