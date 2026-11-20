#!/usr/bin/env python3
"""LUKA 스포츠 데이터 수집기 — ESPN 공개 API 기반 (네이버 대체).

네이버 스포츠 API는 해외 데이터센터 IP를 막아 GitHub Actions에서 쓸 수 없었다.
ESPN 공개 API는 Actions에서도 열리고, 브라우저에는 CORS(`access-control-allow-origin: *`)를
열어 주므로 앱이 실시간으로 직접 호출할 수도 있다.

만드는 파일
  data/today.json      오늘(±하루) 경기 — 상태·스코어·로고
  data/standings.json  리그별 순위
  data/news.json       주요 소식 (한국어 제목·3줄 요약·원문 링크)
  data/teams-ko.json   팀 약어 → 한국어 이름 (앱이 직접 호출할 때도 사용)

원칙
  * 기사 전문은 저장하지 않는다. 제목·요약·링크만.
  * 어린이에게 부적절한 기사는 버린다.
  * 영어는 한국어로 옮긴다(팀 사전 + MyMemory 번역, 실패하면 영어 그대로).
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://site.api.espn.com/apis/v2/sports"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

SPORT_ORDER = ["야구", "해외야구", "축구", "해외축구", "국제 대회", "농구", "미식축구", "배구", "일반"]
SPORT_EMOJI = {"야구": "⚾", "해외야구": "⚾", "축구": "⚽", "해외축구": "⚽", "국제 대회": "🌍",
               "농구": "🏀", "미식축구": "🏈", "배구": "🏐", "일반": "🏅"}

LEAGUES = [
    {"espn": "baseball/mlb", "sport": "야구", "name": "MLB", "season": "2026"},
    {"espn": "basketball/nba", "sport": "농구", "name": "NBA", "season": "2026"},
    {"espn": "football/nfl", "sport": "미식축구", "name": "NFL", "season": "2026"},
    {"espn": "soccer/eng.1", "sport": "해외축구", "name": "프리미어리그", "season": "2026"},
    {"espn": "soccer/esp.1", "sport": "해외축구", "name": "라리가", "season": "2026"},
    {"espn": "soccer/ger.1", "sport": "해외축구", "name": "분데스리가", "season": "2026"},
    {"espn": "soccer/ita.1", "sport": "해외축구", "name": "세리에A", "season": "2026"},
    {"espn": "soccer/tur.1", "sport": "해외축구", "name": "튀르키예 쉬페르리그", "season": "2026"},
    {"espn": "soccer/uefa.champions", "sport": "해외축구", "name": "챔피언스리그", "season": "2026"},
    # ── 국제 대회 (나라 대 나라) ──
    # ESPN에서 soccer/afc.cup 은 'AFC 챔피언스리그2'(클럽 대회)라서, 아시안컵은 afc.asian.cup 을 쓴다.
    {"espn": "soccer/fifa.world", "sport": "국제 대회", "name": "월드컵", "season": "2026", "intl": True},
    {"espn": "soccer/fifa.worldq.afc", "sport": "국제 대회", "name": "월드컵 아시아 예선", "season": "2026", "intl": True},
    {"espn": "soccer/afc.asian.cup", "sport": "국제 대회", "name": "아시안컵", "season": "2026", "intl": True},
    {"espn": "soccer/uefa.nations", "sport": "국제 대회", "name": "네이션스리그", "season": "2026", "intl": True},
    {"espn": "soccer/uefa.euro", "sport": "국제 대회", "name": "유로", "season": "2026", "intl": True},
    {"espn": "soccer/caf.nations", "sport": "국제 대회", "name": "아프리카 네이션스컵", "season": "2026", "intl": True},
    {"espn": "soccer/conmebol.america", "sport": "국제 대회", "name": "코파 아메리카", "season": "2026", "intl": True},
    {"espn": "soccer/fifa.friendly", "sport": "국제 대회", "name": "국가대표 평가전", "season": "2026", "intl": True},
]
INTL_KEYS = {l["espn"] for l in LEAGUES if l.get("intl")}

TEAMS_KO = {
    # NBA
    "ATL": "애틀랜타", "BOS": "보스턴", "BKN": "브루클린", "CHA": "샬럿", "CHI": "시카고",
    "CLE": "클리블랜드", "DAL": "댈러스", "DEN": "덴버", "DET": "디트로이트",
    "GS": "골든스테이트", "HOU": "휴스턴", "IND": "인디애나", "LAC": "LA클리퍼스",
    "LAL": "LA레이커스", "MEM": "멤피스", "MIA": "마이애미", "MIL": "밀워키",
    "MIN": "미네소타", "NO": "뉴올리언스", "NOP": "뉴올리언스", "NY": "뉴욕", "NYK": "뉴욕",
    "OKC": "오클라호마", "ORL": "올랜도", "PHI": "필라델피아", "PHX": "피닉스",
    "POR": "포틀랜드", "SAC": "새크라멘토", "SA": "샌안토니오", "SAS": "샌안토니오",
    "TOR": "토론토", "UTA": "유타", "WAS": "워싱턴", "WSH": "워싱턴",
    # MLB
    "ARI": "애리조나", "BAL": "볼티모어", "CHC": "시카고컵스", "CWS": "시카고화이트삭스",
    "CHW": "시카고화이트삭스", "CIN": "신시내티", "COL": "콜로라도", "KC": "캔자스시티",
    "KCR": "캔자스시티", "LAA": "LA에인절스", "LAD": "LA다저스", "MIA": "마이애미",
    "MIL": "밀워키", "MIN": "미네소타", "NYM": "뉴욕메츠", "NYY": "뉴욕양키스",
    "ATH": "애슬레틱스", "OAK": "애슬레틱스", "PHI": "필라델피아", "PIT": "피츠버그",
    "SD": "샌디에이고", "SDP": "샌디에이고", "SF": "샌프란시스코", "SFG": "샌프란시스코",
    "SEA": "시애틀", "STL": "세인트루이스", "TB": "탬파베이", "TBR": "탬파베이",
    "TEX": "텍사스", "TOR": "토론토", "WSH": "워싱턴",
    # 프리미어리그
    "ARS": "아스널", "AVL": "애스턴빌라", "BOU": "본머스", "BRE": "브렌트퍼드",
    "BHA": "브라이턴", "CHE": "첼시", "CRY": "크리스털팰리스", "EVE": "에버턴",
    "FUL": "풀럼", "IPS": "입스위치", "LEI": "레스터", "LIV": "리버풀",
    "MCI": "맨시티", "MUN": "맨유", "NEW": "뉴캐슬",
    "NFO": "노팅엄", "SOU": "사우샘프턴", "TOT": "토트넘", "WHU": "웨스트햄",
    "WOL": "울버햄프턴", "BUR": "번리", "SHU": "셰필드", "LUT": "루턴",
    # 라리가
    "RMA": "레알마드리드", "BAR": "바르셀로나", "ATM": "아틀레티코", "SEV": "세비야",
    "ATH": "아틀레틱", "RSO": "레알소시에다드", "VIL": "비야레알", "BET": "베티스",
    "VAL": "발렌시아", "GIR": "지로나", "CEL": "셀타", "OSA": "오사수나",
    "RAY": "라요", "MLL": "마요르카", "GET": "헤타페", "ALV": "알라베스",
    # 세리에A
    "JUV": "유벤투스", "INT": "인터밀란", "ACM": "AC밀란", "NAP": "나폴리",
    "ROM": "로마", "LAZ": "라치오", "ATA": "아탈란타", "FIO": "피오렌티나",
    "BOL": "볼로냐", "UDI": "우디네세", "GEN": "제노아",
    # 분데스리가
    "BAY": "바이에른", "BVB": "도르트문트", "LEV": "레버쿠젠", "RBL": "라이프치히",
    "SGE": "프랑크푸르트", "VFB": "슈투트가르트", "WOB": "볼프스부르크",
    "BMG": "묀헨글라트바흐", "SCF": "프라이부르크", "M05": "마인츠",
}

# NFL 32팀 — 약어가 NBA·MLB와 겹쳐서(CHI·DEN·LAC·SF) 리그별 사전으로 따로 쓴다
NFL_TEAMS_KO = {
    "BUF": "버팔로", "MIA": "마이애미", "NE": "뉴잉글랜드", "NYJ": "뉴욕제츠",
    "BAL": "볼티모어", "CIN": "신시내티", "CLE": "클리블랜드", "PIT": "피츠버그",
    "HOU": "휴스턴", "IND": "인디애나폴리스", "JAX": "잭슨빌", "TEN": "테네시",
    "DEN": "덴버", "KC": "캔자스시티", "LV": "라스베이거스", "LAC": "LA차저스",
    "DAL": "댈러스", "NYG": "뉴욕자이언츠", "PHI": "필라델피아", "WAS": "워싱턴",
    "CHI": "시카고", "DET": "디트로이트", "GB": "그린베이", "MIN": "미네소타",
    "ATL": "애틀랜타", "CAR": "캐롤라이나", "NO": "뉴올리언스", "TB": "탬파베이",
    "ARI": "애리조나", "LAR": "LA램스", "SF": "샌프란시스코", "SEA": "시애틀",
}

# 튀르키예 쉬페르리그 18팀 (GEN은 세리에A 제노아와 겹침)
TUR_TEAMS_KO = {
    "GAL": "갈라타사라이", "FEN": "페네르바체", "BES": "베식타스", "TRAB": "트라브존스포르",
    "IBFK": "바샥셰히르", "KAS": "카슴파샤", "KOC": "코자엘리스포르", "AMED": "아메드스포르",
    "COR": "초룸", "GOZ": "괴즈테페", "CAY": "차이쿠르리제스포르", "ERZ": "에르주룸",
    "ALA": "알라냐스포르", "GEN": "겐츨레르비를리이", "KNY": "코니아스포르", "GAZ": "가즈안테프",
    "SAM": "삼순스포르", "EYU": "아이윕스포르",
}

# 국가대표 — CHI(칠레)·DEN(덴마크)·COL(콜롬비아)처럼 클럽 약어와 겹치는 게 많아 리그별 사전으로 쓴다
INT_TEAMS_KO = {
    "KOR": "대한민국", "PRK": "북한", "JPN": "일본", "CHN": "중국", "AUS": "호주",
    "IRN": "이란", "IRQ": "이라크", "KSA": "사우디아라비아", "QAT": "카타르", "UAE": "아랍에미리트",
    "UZB": "우즈베키스탄", "JOR": "요르단", "SYR": "시리아", "LIB": "레바논", "KUW": "쿠웨이트",
    "BHR": "바레인", "PLE": "팔레스타인", "YEM": "예멘", "OMA": "오만", "THA": "태국",
    "VIE": "베트남", "IDN": "인도네시아", "MAS": "말레이시아", "SIN": "싱가포르", "IND": "인도",
    "KGZ": "키르기스스탄", "KAZ": "카자흐스탄", "TAJ": "타지키스탄", "TKM": "투르크메니스탄", "HKG": "홍콩",
    "BRA": "브라질", "ARG": "아르헨티나", "URU": "우루과이", "COL": "콜롬비아", "ECU": "에콰도르",
    "PER": "페루", "CHI": "칠레", "PAR": "파라과이", "BOL": "볼리비아", "VEN": "베네수엘라",
    "MEX": "멕시코", "USA": "미국", "CAN": "캐나다", "CRC": "코스타리카", "HON": "온두라스",
    "PAN": "파나마", "JAM": "자메이카", "DOM": "도미니카공화국", "HAI": "아이티", "SLV": "엘살바도르",
    "GER": "독일", "FRA": "프랑스", "ESP": "스페인", "ENG": "잉글랜드", "ITA": "이탈리아",
    "POR": "포르투갈", "NED": "네덜란드", "BEL": "벨기에", "CRO": "크로아티아", "SUI": "스위스",
    "DEN": "덴마크", "SWE": "스웨덴", "NOR": "노르웨이", "FIN": "핀란드", "ISL": "아이슬란드",
    "POL": "폴란드", "CZE": "체코", "SVK": "슬로바키아", "SVN": "슬로베니아", "HUN": "헝가리",
    "AUT": "오스트리아", "GRE": "그리스", "TUR": "튀르키예", "SRB": "세르비아", "ROU": "루마니아",
    "BUL": "불가리아", "UKR": "우크라이나", "RUS": "러시아", "SCO": "스코틀랜드", "WAL": "웨일스",
    "NIR": "북아일랜드", "IRL": "아일랜드", "ALB": "알바니아", "MKD": "북마케도니아", "BIH": "보스니아",
    "GEO": "조지아", "ISR": "이스라엘", "AZE": "아제르바이잔", "ARM": "아르메니아", "EST": "에스토니아",
    "LVA": "라트비아", "LTU": "리투아니아", "BLR": "벨라루스", "MDA": "몰도바", "LUX": "룩셈부르크",
    "AND": "안도라", "GIB": "지브롤터", "LIE": "리히텐슈타인", "MLT": "몰타", "FRO": "페로제도",
    "KOS": "코소보", "CYP": "키프로스", "MNE": "몬테네그로",
    "MAR": "모로코", "SEN": "세네갈", "NGA": "나이지리아", "EGY": "이집트", "ALG": "알제리",
    "TUN": "튀니지", "CMR": "카메룬", "GHA": "가나", "CIV": "코트디부아르", "MLI": "말리",
    "BFA": "부르키나파소", "RSA": "남아프리카공화국", "COD": "콩고민주공화국", "ZAM": "잠비아", "ANG": "앙골라",
    "ETH": "에티오피아", "KEN": "케냐", "UGA": "우간다", "TAN": "탄자니아", "MOZ": "모잠비크",
    "GAB": "가봉", "GUI": "기니", "GAM": "감비아", "BEN": "베냉", "TOG": "토고",
    "NIG": "니제르", "CPV": "카보베르데", "EQG": "적도기니", "SUD": "수단", "LBY": "리비아",
    "NZL": "뉴질랜드", "TAH": "타히티", "FIJ": "피지", "SOL": "솔로몬제도", "VAN": "바누아투",
    "COK": "쿡제도", "PNG": "파푸아뉴기니", "NCL": "뉴칼레도니아",
}

STATE_KO = {"pre": "예정", "in": "진행 중", "post": "종료"}
GROUP_KO = {
    "American League": "아메리칸리그", "National League": "내셔널리그",
    "Eastern Conference": "동부", "Western Conference": "서부",
    "Eastern": "동부", "Western": "서부",
    "AFC": "AFC", "NFC": "NFC",
    "American Football Conference": "AFC", "National Football Conference": "NFC",
}
DIRTY: set[str] = set()

# 아이 화면에 올리지 않는 주제
BANNED = [
    "sex", "porn", "nude", "rape", "murder", "killed", "dead", "death", "suicide",
    "drug", "cocaine", "arrest", "arrested", "jail", "prison", "lawsuit", "court",
    "gambling", "betting", "scandal", "affair", "divorce", "dating", "rumor",
    "politics", "president", "election", "war", "shooting", "crash", "disaster",
    "성폭력", "성추행", "음란", "도박", "마약", "사망", "숨진", "살해", "자살",
    "구속", "기소", "재판", "소송", "논란", "스캔들", "이혼", "열애", "정치", "대통령",
]


def budget_ok(start, limit=420):
    return (time.time() - start) < limit


def http_get(url: str, timeout: int = 15, retries: int = 1) -> bytes:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(1.0)
    raise RuntimeError(f"{type(last).__name__}: {last} @ {url[:80]}")


def get_json(url: str) -> dict:
    return json.loads(http_get(url).decode("utf-8", "replace"))


def write_json(name: str, obj) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(f"  → {name} ({os.path.getsize(path) / 1024:.1f} KB)", flush=True)


def read_json(name: str, default=None):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


# 약어가 리그마다 겹치는 경우(예: MIL = 밀워키 벅스 / AC밀란) 리그별로 먼저 본다
KO_BY_LEAGUE = {
    "soccer/ita.1": {"MIL": "AC밀란", "TOR": "토리노", "ROM": "로마", "INT": "인터밀란",
                     "JUV": "유벤투스", "NAP": "나폴리", "LAZ": "라치오", "ATA": "아탈란타",
                     "FIO": "피오렌티나", "BOL": "볼로냐", "UDI": "우디네세", "GEN": "제노아"},
    "soccer/uefa.champions": {"MIL": "AC밀란", "TOR": "토리노", "ROM": "로마", "INT": "인터밀란",
                              "JUV": "유벤투스", "NAP": "나폴리", "LAZ": "라치오", "ATA": "아탈란타"},
    "football/nfl": NFL_TEAMS_KO,
    "soccer/tur.1": TUR_TEAMS_KO,
}
for _intl in INTL_KEYS:
    KO_BY_LEAGUE[_intl] = INT_TEAMS_KO


def team_ko(team: dict, league_key: str = "") -> str:
    abbr = (team.get("abbreviation") or "").upper()
    override = (KO_BY_LEAGUE.get(league_key) or {}).get(abbr)
    if override:
        return override
    if abbr and abbr in TEAMS_KO:
        return TEAMS_KO[abbr]
    name = team.get("shortDisplayName") or team.get("name") or team.get("displayName") or ""
    if not name:
        return ""
    # 모르는 팀은 한 번만 번역해서 사전에 저장한다 (다음 실행부터는 바로 사용)
    ko = translate(name)
    if ko and ko != name and abbr:
        TEAMS_KO[abbr] = ko
        DIRTY.add(abbr)
    return ko


def logo_of(team: dict) -> str:
    logos = team.get("logos") or []
    if logos:
        return logos[0].get("href") or ""
    if team.get("logo"):
        return team["logo"]
    return ""


def status_ko(comp: dict, sport: str) -> tuple[str, str]:
    st = comp.get("status") or {}
    stype = (st.get("type") or {})
    state = stype.get("state") or "pre"
    period = st.get("period") or 0
    clock = (st.get("displayClock") or "").strip()
    detail = stype.get("shortDetail") or stype.get("detail") or ""
    if state == "pre":
        return "upcoming", ""
    if state == "post":
        return "done", "종료"
    # 진행 중
    if sport == "농구":
        label = f"{period}쿼터" if period else "진행 중"
    elif sport == "야구":
        label = f"{period}회" if period else "진행 중"
    elif sport in ("해외축구", "축구", "국제 대회"):
        label = "후반" if period >= 2 else "전반"
        if clock:
            label += f" {clock}"
    elif sport == "미식축구":
        words = f"{stype.get('description') or ''} {detail}".lower()
        if "half" in words:
            label = "하프타임"
        elif period and period > 4:
            label = "연장"
        elif period:
            label = f"{period}쿼터" + (f" {clock}" if clock else "")
        else:
            label = "진행 중"
    else:
        label = "진행 중"
    return "live", label


def to_game(event: dict, league: dict) -> dict | None:
    comps = event.get("competitions") or []
    if not comps:
        # 골프처럼 대회 하나가 이벤트인 경우
        name = event.get("name") or event.get("shortName") or ""
        if not name:
            return None
        st = event.get("status") or {}
        state = ((st.get("type") or {}).get("state")) or "pre"
        return {
            "id": event.get("id") or name,
            "sport": league["sport"], "emoji": SPORT_EMOJI[league["sport"]],
            "league": league["espn"], "leagueName": league["name"],
            "time": "", "date": "", "state": {"pre": "upcoming", "in": "live", "post": "done"}.get(state, "upcoming"),
            "status": "", "home": {"name": name, "code": "", "emblem": "", "score": None},
            "away": {"name": "", "code": "", "emblem": "", "score": None},
            "winner": "DRAW", "stadium": "", "channel": "", "onAir": False,
        }
    comp = comps[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    state, status_text = status_ko(comp, league["sport"])
    dt_raw = event.get("date") or comp.get("date") or ""
    time_text = ""
    date_text = ""
    if dt_raw:
        try:
            dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00")).astimezone(KST)
            time_text = dt.strftime("%H:%M")
            date_text = dt.strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            pass
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    home_score = home.get("score")
    away_score = away.get("score")
    try:
        home_score = int(float(home_score)) if home_score not in (None, "") else None
        away_score = int(float(away_score)) if away_score not in (None, "") else None
    except Exception:  # noqa: BLE001
        pass
    venue = ((comp.get("venue") or {}).get("fullName")) or ""
    return {
        "id": str(event.get("id") or comp.get("id") or ""),
        "sport": league["sport"], "emoji": SPORT_EMOJI[league["sport"]],
        "league": league["espn"], "leagueName": league["name"],
        "time": time_text, "date": date_text, "state": state, "status": status_text,
        "home": {"name": team_ko(home_team, league["espn"]), "code": home_team.get("abbreviation") or "",
                 "emblem": logo_of(home_team), "score": home_score},
        "away": {"name": team_ko(away_team, league["espn"]), "code": away_team.get("abbreviation") or "",
                 "emblem": logo_of(away_team), "score": away_score},
        "winner": "HOME" if home.get("winner") else ("AWAY" if away.get("winner") else "DRAW"),
        "stadium": venue, "channel": "", "onAir": state == "live",
    }


def fetch_scoreboard(league: dict, date_str: str) -> list[dict]:
    url = f"{SITE}/{league['espn']}/scoreboard?dates={date_str}&limit=50"
    payload = get_json(url)
    out = []
    for ev in payload.get("events") or []:
        game = to_game(ev, league)
        if game:
            out.append(game)
    return out


def build_today(now: datetime) -> None:
    games, seen = [], set()
    # 0=오늘, -1=어제(끝난 경기), 1=내일(이따 있을 경기) — 금요일 밤에 주말 경기를 미리 보여 준다
    for offset in (0, -1, 1):
        date_str = (now + timedelta(days=offset)).strftime("%Y%m%d")
        for league in LEAGUES:
            try:
                for game in fetch_scoreboard(league, date_str):
                    if offset == -1 and game["state"] != "done":
                        continue
                    if offset == 1 and game["state"] != "upcoming":
                        continue
                    key = game["id"] or f"{game['home']['name']}-{game['away']['name']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    if offset == -1:
                        game["yesterday"] = True
                    elif offset == 1:
                        game["tomorrow"] = True
                    games.append(game)
            except Exception as exc:  # noqa: BLE001
                print(f"  {league['name']} {date_str} 실패: {exc}", flush=True)

    order = {"live": 0, "upcoming": 1, "done": 2, "cancel": 3}
    games.sort(key=lambda g: (order.get(g["state"], 4), g.get("date") or "", g.get("time") or ""))
    counts = {}
    for g in games:
        counts[g["sport"]] = counts.get(g["sport"], 0) + 1
    if not games:
        print("  경기 0건 — today.json 은 그대로 둡니다", flush=True)
        return
    write_json("today.json", {
        "updated": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "total": len(games),
        "counts": counts,
        "sports": SPORT_ORDER,
        "source": "ESPN",
        "games": games,
    })
    print(f"  경기 {len(games)}건 {counts}", flush=True)


def stat_value(entry: dict, *names):
    for s in entry.get("stats") or []:
        if s.get("name") in names:
            return s.get("displayValue") or s.get("value")
    return None


def build_standings(now: datetime) -> None:
    leagues = []
    for league in LEAGUES:
        if league.get("intl"):
            # 국제 대회는 조별리그 표가 대회마다 달라서 순위는 넣지 않는다(경기·소식만)
            continue
        url = f"{CORE}/{league['espn']}/standings?season={league['season']}"
        try:
            payload = get_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {league['name']} 순위 실패: {exc}", flush=True)
            continue
        groups = payload.get("children") or []
        rows = []
        for group in groups:
            group_name = (group.get("name") or "").replace("2026-27 ", "").replace("2026 ", "")
            entries = ((group.get("standings") or {}).get("entries")) or []
            for entry in entries:
                team = entry.get("team") or {}
                rank = stat_value(entry, "rank") or entry.get("rank")
                if rank is None:
                    rank = len(rows) + 1
                points = stat_value(entry, "points")
                win_pct = stat_value(entry, "winPercent") or stat_value(entry, "percentage")
                wins = stat_value(entry, "wins")
                draws = stat_value(entry, "ties")
                losses = stat_value(entry, "losses")
                played = stat_value(entry, "gamesPlayed")
                if played in (None, ""):
                    try:
                        played = str(int(float(str(wins or 0))) + int(float(str(draws or 0))) + int(float(str(losses or 0))))
                    except Exception:  # noqa: BLE001
                        played = None
                rows.append({
                    "rank": int(float(rank)) if str(rank).replace(".", "").isdigit() else len(rows) + 1,
                    "team": team_ko(team, league["espn"]),
                    "emblem": logo_of(team),
                    "games": played,
                    "w": wins,
                    "d": draws,
                    "l": losses,
                    "rate": win_pct,
                    "points": points if points not in ("", None) else None,
                    "last5": "",
                    "group": GROUP_KO.get(group_name, group_name) if len(groups) > 1 else "",
                })
        if not rows:
            print(f"  {league['name']} 순위 없음", flush=True)
            continue
        soccer = league["espn"].startswith("soccer")
        metric = "pts" if soccer and all(r["points"] not in (None, "") for r in rows[:3]) else "pct"
        for r in rows:
            if metric == "pct":
                r["points"] = None
        # ESPN이 주는 rank는 그룹·리그 기준이 뒤섞여 있어, 성적순으로 직접 매긴다
        def perf(r):
            if metric == "pts":
                return (-float(str(r["points"] or 0).replace("+", "")), -float(str(r["w"] or 0)))
            rate = r.get("rate")
            try:
                rate = float(str(rate))
            except Exception:  # noqa: BLE001
                w = float(str(r["w"] or 0)); l = float(str(r["l"] or 0))
                rate = w / (w + l) if (w + l) else 0.0
            return (-rate, -float(str(r["w"] or 0)))
        buckets: dict[str, list] = {}
        for r in rows:
            buckets.setdefault(r["group"] or "", []).append(r)
        ordered = []
        for key in buckets:
            group_rows = sorted(buckets[key], key=perf)
            for i, r in enumerate(group_rows, start=1):
                r["rank"] = i
            ordered.extend(group_rows)
        rows = ordered
        # 승률 문자열 정리
        for r in rows:
            if metric == "pct" and isinstance(r["rate"], str) and r["rate"].startswith("."):
                r["rate"] = "0" + r["rate"]
        leagues.append({
            "id": league["espn"].split("/")[-1], "sport": league["sport"], "name": league["name"],
            "season": str(league["season"]), "metric": metric, "teamCount": len(rows), "rows": rows,
        })
        print(f"  {league['name']}: {len(rows)}팀 ({metric})", flush=True)

    if not leagues:
        print("  순위 0개 — 그대로 둡니다", flush=True)
        return
    order = {s: i for i, s in enumerate(SPORT_ORDER)}
    leagues.sort(key=lambda l: (order.get(l["sport"], 9), l["name"]))
    write_json("standings.json", {
        "updated": now.isoformat(timespec="seconds"),
        "sports": SPORT_ORDER, "source": "ESPN", "leagues": leagues,
    })


def is_safe(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return not any(word in low for word in BANNED)


def translate(text: str) -> str:
    """MyMemory 무료 번역. 실패하면 원문을 그대로 돌려준다."""
    if not text or not re.search(r"[A-Za-z]", text):
        return text
    if len(text) > 480:
        text = text[:480]
    url = ("https://api.mymemory.translated.net/get?q="
           + urllib.parse.quote(text, safe="") + "&langpair=en|ko")
    try:
        payload = get_json(url)
        out = ((payload.get("responseData") or {}).get("translatedText")) or ""
        if out and payload.get("responseStatus") == 200 and "MYMEMORY WARNING" not in out.upper():
            return html.unescape(out)
    except Exception as exc:  # noqa: BLE001
        print(f"    번역 실패: {exc}", flush=True)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+", text.strip())
    return [p.strip(" ,") for p in parts if len(p.strip()) > 8]


def build_news(now: datetime) -> None:
    cache = read_json("news_cache.json", {}) or {}
    new_cache = {}
    sections = []
    total = 0
    for league in LEAGUES:
        if not budget_ok(START):
            break
        url = f"{SITE}/{league['espn']}/news?limit=6"
        try:
            payload = get_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {league['name']} 소식 실패: {exc}", flush=True)
            continue
        items = []
        for art in (payload.get("articles") or []):
            headline = (art.get("headline") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", art.get("description") or "").strip()
            link = ""
            links = art.get("links") or {}
            if isinstance(links, dict):
                link = ((links.get("web") or {}).get("href")) or ""
            aid = str(art.get("id") or headline[:20])
            if not headline or not is_safe(headline) or not is_safe(desc):
                continue
            key = aid
            if key in cache:
                items.append(cache[key])
                new_cache[key] = cache[key]
            else:
                ko_title = translate(headline)
                if not is_safe(ko_title):
                    continue
                ko_desc = translate(desc)
                lines = split_sentences(ko_desc)[:3]
                if not lines:
                    continue
                item = {
                    "id": key, "title": ko_title, "summary": lines,
                    "source": "ESPN", "time": art.get("published") or "",
                    "link": link or "https://www.espn.com/",
                }
                items.append(item)
                new_cache[key] = item
            if len(items) >= 3:
                break
        if items:
            sections.append({"id": league["espn"], "label": league["name"],
                             "sport": league["sport"], "intl": bool(league.get("intl")), "items": items})
            total += len(items)
            print(f"  {league['name']}: {len(items)}건", flush=True)

    if not total:
        print("  소식 0건 — 그대로 둡니다", flush=True)
        return
    for k in list(new_cache)[:400]:
        pass
    write_json("news_cache.json", dict(list(new_cache.items())[:400]))
    write_json("news.json", {
        "updated": now.isoformat(timespec="seconds"),
        "total": total,
        "note": "제목·3줄 요약·원문 링크만 담습니다. 기사 전문과 댓글은 저장하지 않습니다.",
        "source": "ESPN (한국어 번역)",
        "sections": sections,
    })


def write_ko_maps() -> None:
    """앱이 ESPN을 직접 부를 때 쓰는 리그별 한국어 이름표.

    약어가 리그끼리 겹쳐서(CHI=시카고/칠레, GEN=제노아/겐츨레르비를리이) 한 장으로는
    맞출 수 없다. 수집기가 원본을 쥐고 이 파일로 내려 준다.
    """
    write_json("ko-teams.json", {
        "updated": datetime.now(KST).isoformat(timespec="seconds"),
        "byLeague": {
            "football/nfl": NFL_TEAMS_KO,
            "soccer/tur.1": TUR_TEAMS_KO,
            "soccer/ita.1": KO_BY_LEAGUE["soccer/ita.1"],
            "soccer/uefa.champions": KO_BY_LEAGUE["soccer/uefa.champions"],
        },
        "intl": INT_TEAMS_KO,
        "intlLeagues": sorted(INTL_KEYS),
    })


START = time.time()


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    now = datetime.now(KST)
    print(f"[{now.isoformat(timespec='seconds')}] ESPN 수집 시작", flush=True)
    cached = read_json("teams-ko.json", {}) or {}
    for k, v in cached.items():
        TEAMS_KO.setdefault(k, v)
    write_json("teams-ko.json", dict(sorted(TEAMS_KO.items())))
    write_ko_maps()
    for name, fn in (("today", build_today), ("standings", build_standings), ("news", build_news)):
        try:
            fn(now)
        except Exception as exc:  # noqa: BLE001
            print(f"!! {name} 실패: {exc}", flush=True)
    if DIRTY:
        write_json("teams-ko.json", dict(sorted(TEAMS_KO.items())))
        print(f"  팀 이름 {len(DIRTY)}개 번역 추가", flush=True)
    print(f"끝 ({time.time() - START:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
