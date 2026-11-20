#!/usr/bin/env python3
"""브라우저에서 읽어 온 네이버 스포츠 응답(튜플)을 앱 데이터로 변환한다.

브라우저(Pickle 환경, 한국 IP)에서만 api-gw에 닿기 때문에, 수집 결과를
이 스크립트로 data/*.json 형태로 만든다.
사용: python3 scripts/snapshot_to_data.py today tmp/games_raw.json
      python3 scripts/snapshot_to_data.py standings tmp/st_*.json
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fetch_sports as fs  # noqa: E402

KST = timezone(timedelta(hours=9))


def game_from_tuple(t: list) -> dict:
    (gid, upper, cid, cname, league_name, dt, stadium, title,
     home, hcode, hscore, hemblem, away, acode, ascore, aemblem,
     winner, status_num, status_info, cancel, suspended, channel, onair) = t
    game = {
        "gameId": gid, "upperCategoryId": upper, "categoryId": cid,
        "categoryName": cname, "leagueName": league_name, "gameDateTime": dt,
        "stadium": stadium, "title": title,
        "homeTeamName": home, "homeTeamCode": hcode, "homeTeamScore": hscore,
        "homeTeamEmblemUrl": hemblem,
        "awayTeamName": away, "awayTeamCode": acode, "awayTeamScore": ascore,
        "awayTeamEmblemUrl": aemblem, "winner": winner,
        "statusNum": status_num, "statusInfo": status_info,
        "cancel": bool(cancel), "suspended": bool(suspended),
        "broadChannel": channel, "gameOnAir": bool(onair),
    }
    return game


def build_today(paths: list[str]) -> None:
    tuples = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            tuples += json.load(fh)
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")
    games = [fs.compact_game(game_from_tuple(t), date_str) for t in tuples]
    games = [g for g in games if not fs.is_junk(game_from_tuple_by_id(tuples, g["id"]))]
    # 팀 없는 '이벤트' 항목은 제목이 같으면 하나만 남긴다
    seen, dedup = set(), []
    for g in games:
        if g["away"]["name"]:
            dedup.append(g)
            continue
        key = (g["sport"], g["home"]["name"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(g)
    games = dedup
    games.sort(key=fs.sort_key)
    counts: dict[str, int] = {}
    for g in games:
        counts[g["sport"]] = counts.get(g["sport"], 0) + 1
    fs.write_json("today.json", {
        "updated": now.isoformat(timespec="seconds"),
        "date": date_str,
        "total": len(games),
        "counts": counts,
        "sports": fs.SPORT_ORDER,
        "games": games,
    })
    print("sports:", counts)


def game_from_tuple_by_id(tuples: list, gid: str) -> dict:
    for t in tuples:
        if t[0] == gid:
            return game_from_tuple(t)
    return {"title": "", "homeTeamName": "", "awayTeamName": ""}


def build_standings(paths: list[str]) -> None:
    """각 파일 = {code, sport, name, season, rows:[...]} (브라우저에서 정리해 온 형태)"""
    leagues = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            item = json.load(fh)
        rows = [r for r in (fs.parse_standing_row(x) for x in item["rows"]) if r]
        if not rows:
            print("skip", item.get("code"))
            continue
        rows.sort(key=lambda r: (r["group"] or "", r["rank"]))
        metric = "pts" if all(r["points"] is not None for r in rows[:3]) else "pct"
        leagues.append({
            "id": item["code"], "sport": item["sport"], "name": item["name"],
            "season": item.get("season") or "", "metric": metric,
            "teamCount": len(rows), "rows": rows,
        })
        print("standings", item["code"], len(rows), metric)
    order = {s: i for i, s in enumerate(fs.SPORT_ORDER)}
    leagues.sort(key=lambda l: (order.get(l["sport"], 9), l["name"]))
    fs.write_json("standings.json", {
        "updated": datetime.now(KST).isoformat(timespec="seconds"),
        "sports": fs.SPORT_ORDER,
        "leagues": leagues,
    })


def build_news(payload_path: str) -> None:
    """payload = [{id, label, items:[{title, sub, source, time, link}]}]"""
    with open(payload_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    sections, total = [], 0
    for sec in payload:
        items = []
        for it in sec["items"]:
            title = (it.get("title") or "").strip()
            sub = (it.get("sub") or "").strip()
            if not title or not fs.is_safe(title) or not fs.is_safe(sub):
                continue
            summary = fs.polish_summary(fs.fallback_summary(sub))
            if not summary or not fs.is_safe(" ".join(summary)):
                continue
            items.append({
                "id": it.get("id") or title[:16],
                "title": title,
                "summary": summary[:3],
                "source": it.get("source") or "",
                "time": it.get("time") or "",
                "link": it.get("link") or "",
            })
        total += len(items)
        sections.append({"id": sec["id"], "label": sec["label"], "items": items})
        print("news", sec["label"], len(items))
    fs.write_json("news.json", {
        "updated": datetime.now(KST).isoformat(timespec="seconds"),
        "total": total,
        "note": "제목·3줄 요약·원문 링크만 담습니다. 기사 전문과 댓글은 저장하지 않습니다.",
        "sections": sections,
    })


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "today":
        build_today(sys.argv[2:])
    elif mode == "standings":
        build_standings(sorted(glob.glob(os.path.join(ROOT, "..", "tmp", "st_*.json"))))
    elif mode == "news":
        build_news(sys.argv[2])
