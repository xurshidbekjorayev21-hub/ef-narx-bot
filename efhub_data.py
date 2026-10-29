import json
import re
import urllib.request


def get_player(player_id):
    url = f"https://efhub.com/players/{player_id}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        html = response.read().decode("utf-8", "ignore")

    # Sahifadagi React ma'lumotlari ichidan futbolchi obyektini topamiz.
    html_unescaped = html.replace(r'\"', '"')

    def extract(pattern, source=html_unescaped):
        match = re.search(pattern, source, re.S)
        return match.group(1) if match else None

    name = extract(r'"player":\{.*?"name":"([^"]+)"')
    stats_raw = extract(r'"baseStats":(\{[^{}]+\})')
    skills_raw = extract(r'"playerSkills":(\[[^\]]*\])')
    overall = extract(r'"overallRating":(\d+)')
    position = extract(r'"position":"([A-Z]+)"')
    level = extract(r'"initialLevelCap":(\d+)')

    # Birinchi tarjima yozuvini emas, karta ma'lumotidagi haqiqiy uslubni olamiz.
    style_match = re.search(
        r'\\"playingStyle\\":\\"([^"\\]+)\\",\\"overallRating\\":(\d+)',
        html
    )
    style = style_match.group(1) if style_match else None

    try:
        stats = json.loads(stats_raw) if stats_raw else {}
    except json.JSONDecodeError:
        stats = {}

    try:
        skills = json.loads(skills_raw) if skills_raw else []
    except json.JSONDecodeError:
        skills = []

    return {
        "id": str(player_id),
        "name": name,
        "overall": int(overall) if overall else None,
        "position": position,
        "level_cap": int(level) if level else None,
        "playing_style": style,
        "stats": stats,
        "skills": skills,
    }

if __name__ == "__main__":
    import sys
    player_id = sys.argv[1] if len(sys.argv) > 1 else "106794093418757"
    try:
        print(json.dumps(get_player(player_id), ensure_ascii=False, indent=2))
    except Exception as exc:
        print("XATO:", exc)







def search_players(name):
    """eFHUB indeksidan ismga eng mos futbolchi kartalarini qidiradi."""
    name = " ".join(name.strip().split())
    if len(name) < 2:
        return []

    index_url = (
        "https://efhub.com/search/player-index.json"
        "?v=dpl_5QkJPjGeYzEX75EgrJLSnNnF4gus"
    )
    req = urllib.request.Request(
        index_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://efhub.com/",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            index = json.loads(response.read().decode("utf-8", "ignore"))
    except Exception as exc:
        print(f"eFHUB indeksini yuklash xatosi: {exc}")
        return []

    query = name.casefold()

    def norm(value):
        return " ".join(str(value or "").casefold().split())

    ranked = []
    for item in index:
        english = norm(item.get("e", ""))
        japanese = norm(item.get("j", ""))
        chinese = norm(item.get("c", ""))

        if query == english:
            score = 0
        elif english.startswith(query):
            score = 1
        elif query in english:
            score = 2
        elif query == japanese or query == chinese:
            score = 0
        elif query in japanese or query in chinese:
            score = 3
        else:
            continue

        ranked.append((score, item))

    ranked.sort(key=lambda pair: (pair[0], -int(pair[1].get("o") or 0)))

    results = []
    seen = set()

    # Faqat eng mos bir nechta natijani tekshiramiz.
    for _, item in ranked[:25]:
        player_id = str(item.get("i", ""))
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)

        try:
            player = get_player(player_id)
            if not player.get("name"):
                player["name"] = item.get("e")

            player["index_overall"] = item.get("o")
            player["matched_name"] = item.get("e")
            player["name_match_exact"] = (
                norm(player.get("name")) == query
                or norm(item.get("e")) == query
            )
            results.append(player)
        except Exception as exc:
            print(f"eFHUB karta yuklanmadi ({player_id}): {exc}")

    return results

