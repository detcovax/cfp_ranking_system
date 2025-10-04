import json, math, copy
CLEAR_LINE = "\x1b[2K" # Clear the current line
CURSOR_UP = "\033[1A"  # Move cursor up one line

data_file = 'new_data.json'

with open(data_file, 'r') as json_file:
    teams = json.load(json_file)

teams = [team for team in teams if len(team["games"]) > 0]

def get_sp(team):
    try:
        return team["ratings"]["sp"][0]["rating"]
    except (IndexError, KeyError, TypeError):
        return 1  # default value
# def get_srs(team):
#     try:
#         return team["ratings"]["srs"] ??
#     except (IndexError, KeyError, TypeError):
#         return 0  # default value
def get_elo(team):
    try:
        return team["ratings"]["elo"][0]["elo"]
    except (IndexError, KeyError, TypeError):
        return 1000  # default value
def get_normalized_elo(team):
    try:
        return get_elo(team)/1000
    except (IndexError, KeyError, TypeError):
        return 1  # default value
def get_fpi(team):
    try:
        return team["ratings"]["fpi"][0]["fpi"]
    except (IndexError, KeyError, TypeError):
        return 1  # default value

def get_offensive_rating(team):
    try:
        sp = team["ratings"]["sp"][0]["offense"]["rating"]
        fpi = team["ratings"]["fpi"][0]["efficiencies"]["offense"]
        return (sp + fpi) / 2 / 7
    except (IndexError, KeyError, TypeError):
        return 0  # default value
def get_defensive_rating(team):
    try:
        sp = team["ratings"]["sp"][0]["defense"]["rating"]
        fpi = team["ratings"]["fpi"][0]["efficiencies"]["defense"]
        return (-sp + fpi) / 7
    except (IndexError, KeyError, TypeError):
        return 0  # default value
def get_specialTeams_rating(team):
    try:
        sp = team["ratings"]["sp"][0]["specialTeams"]["rating"]
        fpi = team["ratings"]["fpi"][0]["efficiencies"]["specialTeams"]
        return ((sp*7) + fpi) / 7 / 2
    except (IndexError, KeyError, TypeError):
        return 0  # default value
def get_efficiency_rating(team):
    try:
        o = get_offensive_rating(team)
        d = get_defensive_rating(team)
        s = get_specialTeams_rating(team)
        return (o + d + s)
    except (IndexError, KeyError, TypeError):
        return 1  # default value)

def get_power_rating(team):
    try:
        return (((get_fpi(team)+get_sp(team))*get_normalized_elo(team)) + get_efficiency_rating(team)) / 7
    except (IndexError, KeyError, TypeError):
        return 0  # default value

# def get_offensive_scoring(team):
#     games_played = 0
#     points = 0
#     try:
#         for game in team["games"]:
#             try:
#                 if team["school"] == game["awayTeam"]:
#                     points += game["awayPoints"]
#                 else:
#                     points += game["homePoints"]
#                 games_played += 1
#             except:
#                 continue
#         return points / games_played
#     except (ZeroDivisionError):
#         return -1  # default value
#     except (IndexError, KeyError, TypeError):
#         return 0  # default value
# def get_defensive_scoring(team):
#     games_played = 0
#     points = 0
#     try:
#         for game in team["games"]:
#             try:
#                 if team["school"] == game["awayTeam"]:
#                     points += game["homePoints"]
#                 else:
#                     points += game["awayPoints"]
#                 games_played += 1
#             except:
#                 continue
#         return points / games_played
#     except (ZeroDivisionError):
#         return -1  # default value
#     except (IndexError, KeyError, TypeError):
#         return 0  # default value
# def get_net_scoring(team):
#     return get_offensive_scoring(team) - get_defensive_scoring(team)

# scoring_power_weight = 0.0

dave_offense = sorted(teams, key=get_offensive_rating, reverse=True)
for i, team in enumerate(dave_offense, start=1):
    team["dave_offense"] = round(get_offensive_rating(team), ndigits=2)

dave_defense = sorted(teams, key=get_defensive_rating, reverse=True)
for i, team in enumerate(dave_defense, start=1):
    team["dave_defense"] = round(get_defensive_rating(team), ndigits=2)

dave_specialTeams = sorted(teams, key=get_specialTeams_rating, reverse=True)
for i, team in enumerate(dave_specialTeams, start=1):
    team["dave_specialTeams"] = round(get_specialTeams_rating(team), ndigits=2)

dave_power = sorted(teams, key=get_power_rating, reverse=True)
for i, team in enumerate(dave_power, start=1):
    team["power_rating"] = round(get_power_rating(team), ndigits=3)
    team["dave_power"] = i
    # if i <= 10:
    #     print(f"#{i} {team['abbreviation']}", end="\n" if i < 10 else "\n")

# Base multiplier by classification (FBS vs others)
classification_weights = {
    "fbs": 1.0,   # baseline
    "fcs": 0.5,   # less value for win, more penalty for loss
    "ii": 0.25,
    "iii": 0.1,
}

# Conference strength weights (relative difficulty within FBS)
conference_weights = {
    "SEC": 1.25,
    "Big Ten": 1.25,
    "Big 12": 1.2,
    "ACC": 1.2,
    "Pac-12": 1.0,   # adjust for "Power 5" perception
    "American Athletic": 1.0,
    "Mountain West": 1.0,
    "Sun Belt": 1.0,
    "Conference USA": 1.0,
    "Mid-American": 1.0,
}

other_weights = {
    "Notre Dame": conference_weights["ACC"]
}

def rate_teams(team_list:list[dict]) -> list[dict]:
    team_list = sorted(team_list, key=lambda t: t.get("winCredits", t["power_rating"]), reverse=True)
    return_list = []
    for i, team in enumerate(team_list, start=1):
        return_list_team = team.copy()
        return_list_team["power_rank"] = i
        return_list.append(return_list_team)
    for i, team in enumerate(return_list):
        record = [0, 0]
        total_margin = 0
        total_credits = 0
        for j, game in enumerate(team["games"]):
            try:
                margin = game["homePoints"] - game["awayPoints"]
                if team["school"] == game["awayTeam"]:
                    margin = -margin
                    opponent_name = game["homeTeam"]
                else:
                    opponent_name = game["awayTeam"]
                opponent = next((t for t in return_list if t["school"] == opponent_name), None)
                if margin > 0:
                    record[0] += 1
                    win = True
                else:
                    record[1] += 1
                    win = False
                power_scale = classification_weights.get(opponent["classification"], 0.1) * conference_weights.get(opponent["conference"], 1.0) * other_weights.get(opponent_name, 1.0)
                power_rating_multiplier = (10 ** ((len(return_list)+1 - opponent["power_rank"]) / len(return_list))) / 10
                if win:
                    power_scale *= power_rating_multiplier
                else:
                    power_scale =  1 / power_scale
                    power_scale /= power_rating_multiplier
                win_credits = math.asinh(margin) * power_scale
                total_margin += margin
                total_credits += win_credits
                team["games"][j]["dave_info"] = {"winCredits": win_credits, "power_scale": power_scale, "power_rating_multiplier": power_rating_multiplier}
            except TypeError:
                pass
        team["record"] = record
        team["margin"] = total_margin
        team["winCredits"] = total_credits
    return return_list

teams_by_record = sorted(
        rate_teams(dave_power),
        key=lambda team: (
                -team["record"][1],
                team["record"][0],
                team["margin"],
            ),
        reverse=True
    )

n = 1
it_count = 10
ratings = teams_by_record
while n <= it_count:
    print_line = f"Rating Teams: {it_count - n}s"
    print(print_line + (" " * len(print_line)), end="\r")
    old_ratings = copy.deepcopy(ratings)
    new_ratings = rate_teams(ratings)
    # Check if any team's winCredits has changed after the first iteration
    if n > 1:
        win_credits_changed = any(
            old_team["winCredits"] != new_team["winCredits"]
            for old_team, new_team in zip(old_ratings, new_ratings)
        )
    else:
        win_credits_changed = True
    ratings = new_ratings
    if not win_credits_changed:
        break
    n += 1
print(CLEAR_LINE, end="")

teams_to_rank = [team for team in ratings if team['record'][0]+team['record'][1]>0]

dave_rank = sorted(
        teams_to_rank,
        key=lambda team: (
                team["winCredits"]
            ),
        reverse=True
    )
for i, team in enumerate(dave_rank, start=1):
    team["dave_rank"] = i

final_rankings = sorted(
    dave_rank,
    key=lambda team: (
        (0.4 * team["dave_power"]) + (0.6 * team["dave_rank"])
    ),
    reverse=False
)

# Rankings to file
with open("rankings.txt", 'w', encoding="utf-8") as file:
    file.write("2025 DAVE Rankings\n")

    file.write("\n\nDAVE OFFENSE:\n")
    # print(f"Offensive Power Ratings: ", end="")
    for i, team in enumerate(dave_offense[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        rating_text = f"(Offensive Rating: {team['dave_offense']})"
        line = f"{rank_text} {team_text} {rating_text:<15}"
        file.write(f"{line}\n")
        # if i <= 10:
            # print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE DEFENSE:\n")
    # print(f"Defensive Power Ratings: ", end="")
    for i, team in enumerate(dave_defense[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        rating_text = f"(Defensive Rating: {team['dave_defense']})"
        line = f"{rank_text} {team_text} {rating_text:<15}"
        file.write(f"{line}\n")
        # if i <= 10:
            # print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE SPECIAL TEAMS:\n")
    # print(f"Special Teams Power Ratings: ", end="")
    for i, team in enumerate(dave_specialTeams[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        rating_text = f"(Special Teams Rating: {team['dave_specialTeams']})"
        line = f"{rank_text} {team_text} {rating_text:<15}"
        file.write(f"{line}\n")
        # if i <= 10:
        #     print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE POWER:\n")
    # print(f"Power Index: ", end="")
    for i, team in enumerate(dave_power[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        power_text = f"(Power Rating: {team['power_rating']})"
        line = f"{rank_text} {team_text} {power_text:<15}"
        file.write(f"{line}\n")
        # if i <= 10:
        #     print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE CREDIT RATINGS:\n")
    # print(f"Credit Ratings: ", end="")
    for i, team in enumerate(dave_rank[0:25], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        record_text = f"({team['record'][0]}-{team['record'][1]})"
        margin_text = f"({team['margin']:+d})"
        credits_text = f"(Credits: {round(team['winCredits'], ndigits=2)})"
        line = f"{rank_text} {team_text} {record_text:<1} {margin_text:<10} {credits_text:<15}"
        file.write(f"{line}\n")
        # if i <= 25:
        #     print(f"{i_string} {team['abbreviation']}", end=", " if i < 25 else "\n")

    file.write("\n\nFINAL RANKINGS:\n")
    # print(f"Rankings: ", end="")
    for i, team in enumerate(final_rankings, start=1):
        i_string = f"#{i}"
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        record_text = f"({team['record'][0]}-{team['record'][1]})"
        margin_text = f"({team['margin']:+d})"
        info_text = f"(Power: #{team['dave_power']}, Credits: #{team['dave_rank']})"
        line = f"{rank_text} {team_text} {record_text:<1} {margin_text:<10} {info_text:<15}"
        file.write(f"{line}\n")
        # if i <= 25:
        #     print(f"{i_string} {team['abbreviation']}", end=", " if i < 25 else "\n")


# Individual team reports
with open("reports.txt", 'w', encoding="utf-8") as file:
    for i, team in enumerate(final_rankings, start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"
        team_string = f"{team['school']} ({team['abbreviation']})"
        team_text = f"{team_string:<15}"
        record_text = f"({team['record'][0]}-{team['record'][1]})"
        margin_text = f"({team['margin']:+d})"
        list_by_credits = [_['school'] for _ in dave_rank]
        list_by_power = [_['school'] for _ in dave_power]
        list_by_off = [_['school'] for _ in dave_offense]
        list_by_def = [_['school'] for _ in dave_defense]
        list_by_spt = [_['school'] for _ in dave_specialTeams]
        credits_text = f"    #{list_by_credits.index(team['school'])+1} Credits: {round(team['winCredits'], ndigits=3)}"
        power_text = f"    #{list_by_power.index(team['school'])+1} Power: {team['power_rating']}"
        off_text = f"    #{list_by_off.index(team['school'])+1} Offense: {team['dave_offense']}"
        def_text = f"    #{list_by_def.index(team['school'])+1} Defense: {team['dave_defense']}"
        spt_text = f"    #{list_by_spt.index(team['school'])+1} Special Teams: {team['dave_specialTeams']}"
        line = f"{rank_text} {team_text} {record_text:<1} {margin_text:<10}\n{credits_text}\n{power_text}\n{off_text}\n{def_text}\n{spt_text}"
        file.write(f"{line}")
        file.write("\n    Schedule:")
        for j, game in enumerate(team['games']):
            homeTeam, homePoints = (game['homeTeam'], game['homePoints'])
            awayTeam, awayPoints = (game['awayTeam'], game['awayPoints'])
            opponent = awayTeam if homeTeam == team['school'] else homeTeam
            teamPoints, opponentPoints = (homePoints, awayPoints) if (homeTeam == team['school']) else (awayPoints, homePoints)
            if teamPoints != None and opponentPoints != None:
                win = teamPoints > opponentPoints
                line_precursor = f"{'W' if win else 'L'}"
                line_precursor = f"{line_precursor:<5}"
                homePoints_str = f" ({homePoints})"
                awayPoints_str = f" ({awayPoints})"
            else:
                line_precursor = f"{game['week']}"
                homePoints_str = ''
                awayPoints_str = ''
            ranked_teams = [_['school'] for _ in final_rankings]
            try:
                awayRank = ranked_teams.index(awayTeam) + 1
            except:
                awayRank = None
            try:
                homeRank = ranked_teams.index(homeTeam) + 1
            except:
                homeRank = None
            try:
                credits = team["games"][j]["dave_info"]["winCredits"]
            except:
                credits = None
            away_str = f"{f'#{awayRank}' if awayRank != None else ''} {awayTeam}" + awayPoints_str
            home_str = f"{f'#{homeRank}' if awayRank != None else ''} {homeTeam}" + homePoints_str
            credit_str = f"{f'Credit: {round(credits, ndigits=3)}' if credits != None else ''}"
            line = f"\n     {line_precursor:<5} {away_str:<25} {'@':<5} {home_str:<25}     {credit_str:>10}"
            file.write(f"{line}")
        file.write(f"\n\n\n")

with open("playoff_predictor.txt", "w", encoding="utf-8") as file:
    champs = dict()
    teams = []
    for i, team in enumerate(final_rankings, start=1):
        if i <= 12:
            teams.append(team['school'])
        conf = team['conference']
        if conf not in champs.keys() and conf != 'FBS Independents':
            champs[conf] = team['school']
        if len(champs) >= 5:
            break
    champs_added_counter = 0
    for conf, team in champs.items():
        if team not in teams:
            del teams[-(champs_added_counter+1)]
            teams.append(f"(C){champs[conf]}")
            champs_added_counter += 1
    # print(f"champs_added_counter={champs_added_counter}")
    
    file.write("Byes:\n")
    file.write(f"#1 {teams[0]}")
    file.write(f"\n#2 {teams[1]}")
    file.write(f"\n#3 {teams[2]}")
    file.write(f"\n#4 {teams[3]}")
    file.write("\n")
    file.write("\nRound 1:")
    file.write(f"\n#5 {teams[4]:<10} v.   #12 {teams[11]}")
    file.write(f"\n#6 {teams[5]:<10} v.   #11 {teams[10]}")
    file.write(f"\n#7 {teams[6]:<10} v.   #10 {teams[9]}")
    file.write(f"\n#8 {teams[7]:<10} v.   #9 {teams[8]}")

    file.write("\n\nOutside Looking In:")
    outside_counter = 0
    for i, team in enumerate(final_rankings, start=1):
        if (i <= 25) and (team['school'] not in teams):
            file.write(f"\n#{i} {team['school']}")
            outside_counter += 1


games = []
# Flatten all games into a single list
for team in final_rankings:
    games.extend(team['games'])
unique_games = []
seen = set()
for g in games:
    if g.get('dave_info', {'winCredits': -1}).get('winCredits', -1) >= 0:
        # Define a unique key (adjust fields if needed)
        key = (g.get('homeTeam'), g.get('awayTeam'), g.get('startDate', g.get('id')))
        if key not in seen:
            seen.add(key)
            unique_games.append(g)
    else:
        continue
games = unique_games
# Define a safe key extractor for nested keys
def creditKey(game):
    return game.get('dave_info', {}).get('winCredits', 0)
# Sort descending by winCredits (most impressive first)
most_impressive_wins = sorted(games, key=creditKey, reverse=True)
list_by_rank = [_['school'] for _ in final_rankings]
with open("game_impression.txt", 'w', encoding="utf-8") as file:
    file.write(f"Total games: {len(most_impressive_wins)}")
    for n, game in enumerate(most_impressive_wins):
        home = game.get('homeTeam', 'Unknown')
        homeRank = list_by_rank.index(home)+1
        homePoints = game.get('homePoints', 'Unknown')
        away = game.get('awayTeam', 'Unknown')
        awayRank = list_by_rank.index(away)+1
        awayPoints = game.get('awayPoints', 'Unknown')
        credits = game.get('dave_info', {}).get('winCredits', 'N/A')
        if isinstance(credits, float):
            credits = round(credits, ndigits=3)
        nth_string = f"{n+1:<4}   #{homeRank} {home}({homePoints})  vs  #{awayRank} {away}({awayPoints})   (Credits: {credits})"
        file.write(f"\n{nth_string}")
        # if n == 0:
        #     print(f"\nMost impressive win: {home} vs {away}   (Credits: {round(credits, ndigits=3)})")
# print(f"Total games: {len(most_impressive_wins)}")

print("Done.")