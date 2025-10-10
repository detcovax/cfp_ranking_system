import requests, json, time, traceback
from tqdm import tqdm

base_url = r"https://api.collegefootballdata.com"
access_token = "MOFfmt9jd9x5LakTyGcrT3tK1Wfxxdb/zmKB23nz2MI7AZdsNKGNcu5b2VjERc2L"
call_count = 0

def api_call(endpoint:str, params:dict[str:any]=None):
    global call_count
    retry_counter = 0
    while True:
        retry_counter += 1
        call_count += 1
        try:
            response = requests.get(
                fr"{base_url}/{endpoint}",
                headers={
                    "accept": "application/json",
                    "Authorization": f"Bearer {access_token}"
                },
                params=params
            )
            if response.status_code != 200:
                raise Exception(f"API call failed with status code {response.status_code}")
            try:
                return response.json()
            except:
                print(fr"{base_url}/{endpoint}")
                print(f"({repsonse.status_code}) {response.content}")
                exit()
        except Exception as e:
            if response.status_code == 429:
                print(f"({repsonse.status_code}) {response.content}")
                raise e
            elif retry_counter > 4:
                print(f"API call failed after {retry_counter} retries. Error: {e}")
                raise e
            elif retry_counter == 4:
                print(f"Pausing for 10 seconds before retrying API call...")
                time.sleep(10)
            continue

try:
    print("fetching data...")
    teams = api_call("teams")
    # roster = api_call("roster", {"year": 2025})
    games = api_call("games", {"year": 2025})
    rankings = api_call("rankings", {"year": 2025})
    # ratings = {
    #     "sp": api_call("ratings/sp", {"year": 2025}),
    #     # "srs": api_call("ratings/srs", {"year": 2025}),
    #     "elo": api_call("ratings/elo", {"year": 2025}),
    #     "fpi": api_call("ratings/fpi", {"year": 2025})
    # }
    for i, team in tqdm(enumerate(teams), desc="organizing data", total=len(teams)):
        teams[i]["games"] = [game for game in games if (game["homeTeam"]==team["school"] or game["awayTeam"]==team["school"])]
        teams[i]["rankings"] = [ranking for ranking in rankings if any(rank["school"] == team["school"] for poll in ranking["polls"] for rank in poll["ranks"])]
        # teams[i]["ratings"] = {k: [_ for _ in v if _["team"]==team["school"]] for k, v in ratings.items()}

    print("fetching stats...")
    stats = api_call("stats/season", {"year": 2025})
    stats_advanced = api_call("stats/season/advanced", {"year": 2025})
    for stat in tqdm(stats, desc="organizing stats", total=len(stats)):
        season = stat["season"]
        team = stat["team"]
        conference = stat["conference"]
        statName = stat["statName"]
        statValue = stat["statValue"]
        statCategory = "defense" if "Opponent" in statName else "offense"
        advanded_stat = next((s for s in stats_advanced if s["season"]==season and s["team"]==team and s["conference"]==conference), None)
        if advanded_stat:
            advanded_stat[statCategory][statName] = statValue
        else:
            stats_advanced.append({"season": season, "team": team, "conference": conference, statCategory: {statName: statValue}})
    
    for stat in tqdm(stats_advanced, desc="combining stats & data", total=len(stats_advanced)):
        team = stat["team"]
        conference = stat["conference"]
        team = next((t for t in teams if t["school"]==team and t["conference"]==conference), None)
        if team:
            team["stats"] = stat
        else:
            team.append({"team": team, "conference": conference, stats: stat})

    print("writing to file...")
    data_file = 'new_data.json'
    with open(data_file, 'w', encoding="utf-8") as json_file:
        json.dump(teams, json_file, indent=4)

except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

finally:
    print(f"API calls made this time: {call_count}")
    print(f'API Info: {api_call("info")}')