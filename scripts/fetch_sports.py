#!/usr/bin/env python3
"""네이버 스포츠 → 클린 데이터 수집기 (GitHub Actions에서 5분마다 실행).

만드는 파일 (모두 같은 저장소 = 같은 오리진이라 앱에서 CORS 문제 없음)
  data/today.json      오늘 경기 (전 종목, 상태·스코어·엠블럼)
  data/standings.json  리그별 팀 순위
  data/news.json       주요 소식 (제목 + 규칙 기반 3줄 요약 + 원문 링크만)

지키는 선
  * 기사 본문은 요약을 만든 뒤 저장하지 않는다 (전문·댓글·광고 저장 금지)
  * 어린이에게 부적절한 기사는 제목 단계에서 버린다
  * 외부 AI API 없이 규칙만으로 요약한다 (비용 0원)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

API = "https://api-gw.sports.naver.com"
NEWS_HOST = "https://sports.news.naver.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

GAMES_FIELDS = ",".join(
    [
        "basic",
        "superCategoryId",
        "categoryName",
        "upperCategoryId",
        "upperCategoryName",
        "stadium",
        "statusNum",
        "gameOnAir",
        "hasVideo",
        "title",
        "broadChannel",
        "league",
        "leagueName",
        "postponed",
    ]
)

# ---------------------------------------------------------------- HTTP


def http_get(url: str, timeout: int = 20, retries: int = 2) -> bytes:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept-Language": "ko-KR,ko;q=0.9",
                    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
                    "Referer": "https://sports.naver.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except Exception as exc:  # noqa: BLE001 - 네트워크는 어떤 이유로도 실패할 수 있다
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET 실패 {url}: {last}")


def get_json(url: str) -> dict:
    raw = http_get(url)
    return json.loads(raw.decode("utf-8", "replace"))


def get_text(url: str) -> str:
    return http_get(url).decode("utf-8", "replace")


def write_json(name: str, obj) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(f"  → {name} ({os.path.getsize(path) / 1024:.1f} KB)")


def read_json(name: str, default=None):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------- 종목 분류

# 앱의 종목 필터 칩: 전체 · 야구 · 해외야구 · 축구 · 해외축구 · 농구 · 배구 · 골프 · 일반
FOREIGN_FOOTBALL = {
    "epl", "laliga", "bundesliga", "seriea", "ligue1", "spl", "eredivisie",
    "mls", "jleague", "saudiarabia", "facup", "ucl", "uel", "uecl",
    "u17worldcup", "wfootballetc", "clubworldcup", "copalibertadores",
}

SPORT_BY_UPPER = {
    "kbaseball": "야구",
    "wbaseball": "해외야구",
    "kfootball": "축구",
    "wfootball": "해외축구",
    "kbasketball": "농구",
    "wbasketball": "농구",
    "kvolleyball": "배구",
    "wvolleyball": "배구",
    "golf": "골프",
    "tennis": "일반",
    "badminton": "일반",
    "others": "일반",
    "general": "일반",
}

SPORT_ORDER = ["야구", "해외야구", "축구", "해외축구", "농구", "배구", "골프", "일반"]

LEAGUE_NAMES = {
    "kbo": "KBO리그",
    "kbaseballetc": "국내야구",
    "mlb": "MLB",
    "npb": "일본프로야구",
    "wbaseballetc": "해외야구",
    "kleague": "K리그1",
    "kleague2": "K리그2",
    "wkleague": "WK리그",
    "kfootballetc": "국내축구",
    "epl": "프리미어리그",
    "laliga": "라리가",
    "bundesliga": "분데스리가",
    "seriea": "세리에A",
    "ligue1": "리그1",
    "mls": "MLS",
    "jleague": "J1리그",
    "ucl": "챔피언스리그",
    "u17worldcup": "U-17 월드컵",
    "kbl": "KBL",
    "wkbl": "WKBL",
    "nba": "NBA",
    "basketballetc": "농구",
    "kovo": "V리그 남자부",
    "wkovo": "V리그 여자부",
    "volleyballetc": "배구",
    "uvolleyball": "대학배구",
    "kpga": "KPGA",
    "klpga": "KLPGA",
    "pga": "PGA",
    "lpga": "LPGA",
    "wta": "WTA 테니스",
    "atp": "ATP 테니스",
    "wbadminton": "배드민턴",
    "baduk": "바둑",
    "etc": "일반",
}

# 경기 카드로 만들지 않는 '방송·이벤트' 항목 (아이 화면을 깔끔하게)
JUNK_TITLE = re.compile(
    r"(라이브|오프너|티켓|중계|토크|특집|예고|하이라이트|다시보기|풀영상|"
    r"초대석|유튜브|쇼츠|LIVE|TV\b)"
)
JUNK_TEXT = re.compile(r"(라이브|오프너|티켓|중대공지)")


def sport_of(game: dict) -> str:
    cid = (game.get("categoryId") or "").lower()
    upper = (game.get("upperCategoryId") or "").lower()
    if cid in FOREIGN_FOOTBALL:
        return "해외축구"
    if upper == "kfootball" and cid in FOREIGN_FOOTBALL:
        return "해외축구"
    return SPORT_BY_UPPER.get(upper, "일반")


def is_junk(game: dict) -> bool:
    home = (game.get("homeTeamName") or "").strip()
    away = (game.get("awayTeamName") or "").strip()
    title = (game.get("title") or "").strip()
    if home and away:
        return False
    if title and JUNK_TITLE.search(title):
        return True
    if not title and not home:
        return True
    return False


TIME_RE = re.compile(r"T(\d{2}):(\d{2})")


def game_time(game: dict) -> str:
    dt = game.get("gameDateTime") or ""
    m = TIME_RE.search(dt)
    return f"{m.group(1)}:{m.group(2)}" if m else ""


def to_state(game: dict) -> str:
    num = game.get("statusNum")
    if game.get("cancel"):
        return "cancel"
    if game.get("suspended"):
        return "cancel"
    if num == 2:
        return "live"
    if num == 4:
        return "done"
    return "upcoming"


SPORT_EMOJI = {
    "야구": "⚾",
    "해외야구": "⚾",
    "축구": "⚽",
    "해외축구": "⚽",
    "농구": "🏀",
    "배구": "🏐",
    "골프": "⛳",
    "일반": "🏅",
}


def compact_game(game: dict, date_str: str) -> dict:
    sport = sport_of(game)
    cid = game.get("categoryId") or ""
    state = to_state(game)
    home = {
        "name": (game.get("homeTeamName") or "").strip(),
        "code": game.get("homeTeamCode") or "",
        "emblem": game.get("homeTeamEmblemUrl") or "",
        "score": game.get("homeTeamScore"),
    }
    away = {
        "name": (game.get("awayTeamName") or "").strip(),
        "code": game.get("awayTeamCode") or "",
        "emblem": game.get("awayTeamEmblemUrl") or "",
        "score": game.get("awayTeamScore"),
    }
    title = (game.get("title") or "").strip()
    if not home["name"] and not away["name"]:
        # 테니스·바둑처럼 '제목'으로만 표시되는 경기
        label = title or (game.get("categoryName") or "")
        home["name"] = label
        away["name"] = ""
    status_info = (game.get("statusInfo") or "").strip()
    if state == "done" and status_info in ("", "경기종료"):
        status_info = ""
    return {
        "id": game.get("gameId") or "",
        "sport": sport,
        "emoji": SPORT_EMOJI.get(sport, "🏅"),
        "league": cid,
        "leagueName": game.get("leagueName")
        or LEAGUE_NAMES.get(cid)
        or (game.get("categoryName") or ""),
        "time": game_time(game),
        "date": date_str,
        "state": state,
        "status": status_info,
        "home": home,
        "away": away,
        "winner": game.get("winner") or "DRAW",
        "stadium": (game.get("stadium") or "").strip(),
        "channel": game.get("broadChannel") or "",
        "onAir": bool(game.get("gameOnAir")),
    }


def sort_key(game: dict):
    order = {"live": 0, "upcoming": 1, "done": 2, "cancel": 3}
    return (order.get(game["state"], 4), game["time"], game["sport"])


def fetch_games(date_str: str) -> list[dict]:
    url = f"{API}/schedule/today-games?date={date_str}&fields={GAMES_FIELDS}"
    payload = get_json(url)
    games = ((payload.get("result") or {}).get("games")) or []
    out = []
    for game in games:
        if is_junk(game):
            continue
        out.append(compact_game(game, date_str))
    out.sort(key=sort_key)
    return out


def build_today(now: datetime) -> list[dict]:
    today = now.strftime("%Y-%m-%d")
    games = fetch_games(today)
    print(f"  오늘({today}) 경기 {len(games)}건")

    done_today = [g for g in games if g["state"] == "done"]
    if len(done_today) < 4:
        # 아침에는 오늘 끝난 경기가 거의 없다 → 어제 결과 몇 개를 채워 준다
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            old = [
                g
                for g in fetch_games(yesterday)
                if g["state"] == "done"
            ]
            old.sort(key=lambda g: (g["time"], g["sport"]), reverse=True)
            for g in old[:8]:
                g["yesterday"] = True
            games.extend(old[:8])
            print(f"  어제({yesterday}) 결과 {min(len(old), 8)}건 보충")
        except Exception as exc:  # noqa: BLE001
            print(f"  어제 결과 보충 실패(무시): {exc}")

    games.sort(key=sort_key)
    counts = {}
    for g in games:
        counts[g["sport"]] = counts.get(g["sport"], 0) + 1

    write_json(
        "today.json",
        {
            "updated": now.isoformat(timespec="seconds"),
            "date": today,
            "total": len(games),
            "counts": counts,
            "sports": SPORT_ORDER,
            "games": games,
        },
    )
    return games


# ---------------------------------------------------------------- 순위

STANDING_LEAGUES = [
    ("kbo", "야구", "KBO리그"),
    ("mlb", "해외야구", "MLB"),
    ("npb", "해외야구", "일본프로야구"),
    ("kleague", "축구", "K리그1"),
    ("kleague2", "축구", "K리그2"),
    ("epl", "해외축구", "프리미어리그"),
    ("laliga", "해외축구", "라리가"),
    ("bundesliga", "해외축구", "분데스리가"),
    ("seriea", "해외축구", "세리에A"),
    ("mls", "해외축구", "MLS"),
    ("kbl", "농구", "KBL"),
    ("wkbl", "농구", "WKBL"),
    ("nba", "농구", "NBA"),
    ("kovo", "배구", "V리그 남자부"),
    ("wkovo", "배구", "V리그 여자부"),
]


def first_not_none(row: dict, *keys):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def parse_standing_row(row: dict) -> dict | None:
    rank = first_not_none(row, "rank", "ranking")
    name = first_not_none(row, "teamName", "teamShortName", "name")
    if rank is None or not name:
        return None
    wins = first_not_none(row, "wins", "winGameCount", "win")
    draws = first_not_none(row, "draws", "drawnGameCount", "draw")
    losses = first_not_none(row, "losses", "loseGameCount", "lose")
    games = first_not_none(row, "matchesPlayed", "gameCount", "games")
    rate = first_not_none(row, "wra", "winRate", "winPercentage")
    points = first_not_none(row, "points", "gainPoint", "seasonPoints")
    emblem = first_not_none(row, "teamEmblemUrl", "teamImageUrl", "emblem") or ""
    return {
        "rank": rank,
        "team": name,
        "emblem": emblem,
        "games": games,
        "w": wins,
        "d": draws,
        "l": losses,
        "rate": rate,
        "points": points,
        "last5": first_not_none(row, "lastFiveGames", "recentFiveGames") or "",
        "group": row.get("group") or "",
    }


def build_standings(now: datetime) -> None:
    leagues = []
    years = [now.year, now.year - 1]
    for code, sport, label in STANDING_LEAGUES:
        rows = []
        season = None
        for year in years:
            url = (
                f"{API}/statistics/categories/{code}/seasons/{year}/teams"
                "?gameType=REGULAR_SEASON"
            )
            try:
                payload = get_json(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  {code} {year} 실패: {exc}")
                continue
            raw = ((payload.get("result") or {}).get("seasonTeamStats")) or []
            parsed = [r for r in (parse_standing_row(x) for x in raw) if r]
            if parsed:
                rows, season = parsed, str(year)
                break
        if not rows:
            print(f"  {code}: 순위 없음(건너뜀)")
            continue
        rows.sort(key=lambda r: (r["group"] or "", r["rank"]))
        metric = "pts" if all(r["points"] is not None for r in rows[:3]) else "pct"
        leagues.append(
            {
                "id": code,
                "sport": sport,
                "name": label,
                "season": season,
                "metric": metric,
                "teamCount": len(rows),
                "rows": rows,
            }
        )
        print(f"  {code} {season}: {len(rows)}팀 ({metric})")

    order = {s: i for i, s in enumerate(SPORT_ORDER)}
    leagues.sort(key=lambda l: (order.get(l["sport"], 9), l["name"]))
    write_json(
        "standings.json",
        {
            "updated": now.isoformat(timespec="seconds"),
            "sports": SPORT_ORDER,
            "leagues": leagues,
        },
    )


# ---------------------------------------------------------------- 뉴스

SECTIONS = [
    ("kbaseball", "야구"),
    ("wbaseball", "해외야구"),
    ("kfootball", "축구"),
    ("wfootball", "해외축구"),
    ("basketball", "농구"),
    ("volleyball", "배구"),
    ("golf", "골프"),
    ("general", "일반"),
]

# 아이 화면에 올리지 않는 주제 (사건·사고·연예·정치·도박 등)
BANNED = [
    "성폭력", "성추행", "성매매", "음란", "AV배우", "성인물", "몰카",
    "도박", "마약", "대마", "음주운전", "음주", "만취", "폭행", "폭력", "구타",
    "사망", "숨진", "시신", "살해", "살인", "자살", "투신", "자해", "부검", "변사",
    "사고사", "참사", "화재", "붕괴", "실종",
    "구속", "기소", "재판", "법원", "검찰", "경찰", "소송", "고소", "고발", "징역",
    "횡령", "뇌물", "비리", "유착", "탈세", "논란", "막말", "욕설", "갑질",
    "이혼", "불륜", "스캔들", "열애", "결별", "루머", "사생활",
    "정치", "대통령", "국회", "의원", "선거", "장관", "청문회",
    "별세", "부고", "빈소",
    "사퇴", "경질", "해체", "파산",
]

SOURCE_BONUS = {
    "연합뉴스": 3.0,
    "뉴시스": 2.5,
    "뉴스1": 2.5,
    "SBS": 2.0,
    "KBS": 2.0,
    "MBC": 2.0,
    "YTN": 2.0,
    "MBN": 1.5,
    "JTBC": 1.5,
    "OBS": 1.5,
}

DROP_PAT = [
    r"^\[?[가-힣A-Za-z·\s]{0,12}(기자|특파원)\]?\s*$",
    r"^\[?[A-Za-z가-힣\s]{2,15}=\s*[가-힣]{2,4}\s*기자\]?",
    r"^Copyright",
    r"^[▲▶☞※◇◆■●]",
    r"^사진\s*=|^자료\s*=|^제공\s*=",
    r"^\[사진\]|^\[영상\]|^\[그래픽\]|^\[포토\]",
    r"구독|알림 설정|로그인|댓글",
    r"야구해외야구축구해외축구농구배구",
]
# 본문 뒤에 붙는 사진 출처·저작권 문구는 줄을 버리지 말고 잘라 낸다
CREDIT = re.compile(
    r"(사진\s*=\s*ⓒ?[^\s]*|ⓒ\s*[^\s]*|\[사진[^\]]*\]|무단 전재[^.]*|재배포 금지[^.]*|Copyright[^\s]*)"
)
NAV_NOISE = ("본문의 검색 링크는 AI 자동 인식", "네이버 스포츠에서 보기")


def is_safe(text: str) -> bool:
    if not text:
        return False
    flat = text.replace(" ", "")
    return not any(word in flat for word in BANNED)


def fetch_article_list(section: str, date_str: str) -> list[dict]:
    base = (
        f"{API}/news/articles/{section}"
        f"?sort=latest&page=1&pageSize=30&isPhoto=N"
    )
    for url in (f"{base}&date={date_str}", base):
        try:
            payload = get_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"    {section} 목록 실패: {exc}")
            continue
        items = ((payload.get("result") or {}).get("newsList")) or []
        if items:
            return items
    return []


def get_body_html(page: str) -> str:
    m = re.search(r'class="[^"]*(?:comp_article_content|_article_content)[^"]*"[^>]*>', page)
    seg = page[m.end(): m.end() + 30000] if m else page
    seg = re.sub(r"<script[\s\S]*?</script>", " ", seg)
    seg = re.sub(r"<style[\s\S]*?</style>", " ", seg)
    seg = re.sub(r"<br\s*/?>|</p>|</div>", "\n", seg)
    seg = re.sub(r"<[^>]+>", "", seg)
    return html.unescape(seg)


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        line = CREDIT.sub(" ", line)
        # [매체=홍길동 기자] / [이데일리 스타in 주영로 기자] 같은 머리말 제거
        m = re.match(r"^\[([^\]]{1,40})\]\s*", line)
        if m and any(k in m.group(1) for k in ("기자", "특파원", "=", "통신", "뉴스")):
            line = line[m.end():]
        line = re.sub(r"^[가-힣]{2,4}\s*기자\s*=\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 15:
            continue
        if any(noise in line for noise in NAV_NOISE):
            continue
        if any(re.search(pat, line) for pat in DROP_PAT):
            continue
        out.append(line)
    return out


OPEN_Q = "“‘\"'「『"
CLOSE_Q = "”’\"'」』"


def split_sentences(lines: list[str]) -> list[str]:
    """줄 → 문장. 따옴표 안에서는 자르지 않는다(인용문이 중간에서 끊기지 않게)."""
    sents, buf = [], ""
    depth, opener = 0, ""
    for line in lines:
        for ch in line:
            if depth == 0 and ch in "“‘「『":
                depth, opener = 1, ch
            elif depth == 1 and ch in "”’」』":
                depth, opener = 0, ""
            elif depth == 0 and ch in "\"'":
                depth, opener = 1, ch
            elif depth == 1 and ch == opener:
                depth, opener = 0, ""
            buf += ch
            if ch in ".!?" and depth == 0:
                # 소수점(0.589)·약어는 문장 끝이 아니다
                if ch == "." and not re.search(r"[다요]\.[\s]?$", buf + " "):
                    continue
                sents.append(buf.strip())
                buf = ""
        if buf.strip():
            sents.append(buf.strip())
            buf = ""
    if buf.strip():
        sents.append(buf.strip())

    seen, uniq = set(), []
    for s in sents:
        s = s.strip(" ,·")
        if not (12 <= len(s) <= 260):
            continue
        key = s[:24]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq


def title_words(title: str) -> set[str]:
    stop = {"그리고", "하지만", "위해", "대한", "있는", "이번", "기자", "오늘", "지난"}
    return {
        w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", title) if w not in stop
    }


def clip(sentence: str, limit: int = 105) -> str:
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit]
    pos = max(cut.rfind(" "), cut.rfind(","), cut.rfind("·"), cut.rfind("다"))
    if pos < limit * 0.5:
        pos = limit - 1
    return cut[:pos].rstrip(" ,·") + "…"


def summarize(title: str, lines: list[str], n: int = 3) -> list[str]:
    sents = split_sentences(lines)
    if not sents:
        return []
    head = sents[0]
    words = title_words(title)
    scored = []
    for idx, s in enumerate(sents[1:], start=1):
        overlap = sum(1 for w in words if w in s)
        score = overlap * 2.0 + (0.6 if idx == 1 else 0) - (idx * 0.05)
        if len(s) > 200:
            score -= 1.0
        scored.append((score, idx, s))
    picked = [head]
    for _, _, s in sorted(scored, reverse=True)[: n - 1]:
        picked.append(s)
    # 원문 순서 유지 (head가 항상 첫 문장)
    ordered = [head] + [s for _, _, s in sorted(scored, reverse=True)[: n - 1]]
    out, seen = [], set()
    for s in ordered:
        if len(out) >= n:
            break
        key = s[:20]
        if key in seen:
            continue
        seen.add(key)
        out.append(clip(s))
    return out


def fallback_summary(sub_content: str) -> list[str]:
    text = re.sub(r"^\[[^\]]{1,25}\]\s*", "", sub_content or "").strip()
    sents = split_sentences([text]) if text else []
    return [clip(s) for s in sents[:3]]


UA_IMG_HOSTS = ("imgnews.pstatic.net",)


def build_news(now: datetime, cache: dict) -> None:
    date_str = now.strftime("%Y%m%d")
    sections_out = []
    used_ids = set()
    total_body = 0
    new_cache = {}

    for section, label in SECTIONS:
        raw = fetch_article_list(section, date_str)
        if not raw:
            print(f"  {label}({section}): 기사 없음")
            sections_out.append({"id": section, "label": label, "items": []})
            continue

        candidates = []
        for item in raw:
            title = html.unescape(item.get("title") or "").strip()
            sub = html.unescape(item.get("subContent") or "").strip()
            source = (item.get("sourceName") or "").strip()
            oid, aid = item.get("oid"), item.get("aid")
            if not title or not oid or not aid:
                continue
            if not is_safe(title) or not is_safe(sub):
                continue
            uid = f"{oid}_{aid}"
            if uid in used_ids:
                continue
            score = SOURCE_BONUS.get(source.split()[0] if source else "", 0.0)
            score += 0.5 if len(title) <= 40 else 0.0
            candidates.append((score, uid, title, sub, source, item))
        candidates.sort(key=lambda x: (-x[0], x[2]))

        items, seen_titles = [], set()
        for _score, uid, title, sub, source, item in candidates:
            if len(items) >= 4:
                break
            key = title.replace(" ", "")[:12]
            if key in seen_titles:
                continue
            cached = cache.get(uid)
            if cached and cached.get("summary"):
                summary = cached["summary"]
            else:
                if total_body >= 22:
                    continue
                link = f"{NEWS_HOST}/article/{item.get('oid')}/{item.get('aid')}"
                try:
                    page = get_text(link)
                    total_body += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"    본문 실패 {uid}: {exc}")
                    page = ""
                if page:
                    lines = clean_lines(get_body_html(page))
                    summary = summarize(title, lines)
                else:
                    summary = []
                if not summary:
                    summary = fallback_summary(sub)
                if not summary:
                    continue
                if not is_safe(" ".join(summary)):
                    continue
            seen_titles.add(key)
            used_ids.add(uid)
            dt = item.get("dateTime") or ""
            items.append(
                {
                    "id": uid,
                    "title": title,
                    "summary": summary[:3],
                    "source": source,
                    "time": dt,
                    "link": f"{NEWS_HOST}/article/{item.get('oid')}/{item.get('aid')}",
                }
            )
            new_cache[uid] = {"summary": summary[:3], "title": title}

        print(f"  {label}({section}): 후보 {len(candidates)}건 → {len(items)}건")
        sections_out.append({"id": section, "label": label, "items": items})

    # 캐시는 최근 것 위주로 400개까지
    merged = dict(new_cache)
    for uid, value in cache.items():
        if len(merged) >= 400:
            break
        merged.setdefault(uid, value)
    write_json("news_cache.json", merged)

    total = sum(len(s["items"]) for s in sections_out)
    write_json(
        "news.json",
        {
            "updated": now.isoformat(timespec="seconds"),
            "total": total,
            "note": "제목·3줄 요약·원문 링크만 담습니다. 기사 전문과 댓글은 저장하지 않습니다.",
            "sections": sections_out,
        },
    )


# ---------------------------------------------------------------- main


def main() -> int:
    now = datetime.now(KST)
    print(f"[{now.isoformat(timespec='seconds')}] 네이버 스포츠 수집 시작")

    failures = []
    try:
        build_today(now)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"today: {exc}")
        print(f"!! today 실패: {exc}")

    try:
        build_standings(now)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"standings: {exc}")
        print(f"!! standings 실패: {exc}")

    try:
        cache = read_json("news_cache.json", {}) or {}
        build_news(now, cache)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"news: {exc}")
        print(f"!! news 실패: {exc}")

    if failures:
        print("실패 요약: " + " | ".join(failures))
    print("수집 끝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
