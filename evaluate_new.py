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
# def get_specialTeams_rating(team):
#     try:
#         sp = team["ratings"]["sp"][0]["specialTeams"]["rating"]
#         fpi = team["ratings"]["fpi"][0]["efficiencies"]["specialTeams"]
#         return (sp + fpi) / 7
#     except (IndexError, KeyError, TypeError):
#         return 0  # default value
def get_efficiency_rating(team):
    try:
        o = get_offensive_rating(team)
        d = get_defensive_rating(team)
        # s = get_specialTeams_rating(team)
        return (o + d)
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

dave_power = sorted(teams, key=get_power_rating, reverse=True)
for i, team in enumerate(dave_power, start=1):
    team["power_rating"] = round(get_power_rating(team), ndigits=3)
    team["dave_power"] = i
    # if i <= 10:
    #     print(f"#{i} {team['abbreviation']}", end="\n" if i < 10 else "\n")

# Base multiplier by classification (FBS vs others)
classification_weights = {
    "fbs": 1.0,   # baseline
    "fcs": 0.01,   # less value for win, more penalty for loss
    "ii": 0.005,
    "iii": 0.001,
}

# Conference strength weights (relative difficulty within FBS)
conference_weights = {
    "SEC": 5.0,
    "Big Ten": 5.0,
    "Big 12": 2.0,
    "ACC": 2.0,
    "Pac-12": 1.2,   # adjust for "Power 5" perception
    "American Athletic": 1.0,
    "Mountain West": 1.2,
    "Sun Belt": 1.0,
    "Conference USA": 1.0,
    "Mid-American": 1.2,
}

other_weights = {
    "Notre Dame": conference_weights["ACC"]
}

def rate_teams(team_list:list[dict]) -> list[dict]:
    team_list = sorted(team_list, key=lambda t: t.get("winCredits", t["power_rating"]), reverse=True)
    return_list = []
    for i, team in enumerate(team_list, start=1):
        return_list_team = team.copy()
        return_list_team["power_rating"] = i
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
                power_rating_multiplier = (10 ** ((len(return_list)+1 - opponent["dave_power"]) / len(return_list))) / 10
                if (i == 0) and (j == 0):
                    print(f"{team['school']}: {power_rating_multiplier}")
                if win:
                    power_scale *= power_rating_multiplier
                else:
                    power_scale =  1 / power_scale
                    power_scale /= power_rating_multiplier
                win_credits = margin * power_scale / 7
                total_margin += margin
                total_credits += win_credits
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
it_count = 5
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
        (0.6 * team["dave_power"]) + (0.4 * team["dave_rank"])
    ),
    reverse=False
)

with open("rankings.txt", 'w', encoding="utf-8") as file:
    file.write("2025 DAVE Rankings\n")

    file.write("\n\nDAVE OFFENSE:\n")
    print(f"Offensive Power Ratings: ", end="")
    for i, team in enumerate(dave_offense[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        rating_text = f"(Offensive Rating: {team['dave_offense']})"
        line = f"{rank_text} {team_text} {rating_text:<15}"
        file.write(f"{line}\n")
        if i <= 10:
            print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE DEFENSE:\n")
    print(f"Defensive Power Ratings: ", end="")
    for i, team in enumerate(dave_defense[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        rating_text = f"(Defensive Rating: {team['dave_defense']})"
        line = f"{rank_text} {team_text} {rating_text:<15}"
        file.write(f"{line}\n")
        if i <= 10:
            print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE POWER:\n")
    print(f"Power Index: ", end="")
    for i, team in enumerate(dave_power[0:10], start=1):
        i_string = f"{i}."
        rank_text = f"{i_string:<3}"  # left-align rank in 3 spaces
        team_string = f"{team['abbreviation']} ({team['school']})"
        team_text = f"{team_string:<25}"  # left-align school name in 20 spaces
        power_text = f"(Power Rating: {team['power_rating']})"
        line = f"{rank_text} {team_text} {power_text:<15}"
        file.write(f"{line}\n")
        if i <= 10:
            print(f"{i_string} {team['abbreviation']}", end=", " if i < 10 else "\n")

    file.write("\n\nDAVE CREDIT RATINGS:\n")
    print(f"Credit Ratings: ", end="")
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
        if i <= 25:
            print(f"{i_string} {team['abbreviation']}", end=", " if i < 25 else "\n")

    file.write("\n\nFINAL RANKINGS:\n")
    print(f"Rankings: ", end="")
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
        if i <= 25:
            print(f"{i_string} {team['abbreviation']}", end=", " if i < 25 else "\n")