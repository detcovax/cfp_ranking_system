import json
import config
from team import Team

teams = []

# Load the JSON file
with open(config.json_games_file, 'r') as json_file:
    games = json.load(json_file)

# Iterate over the items in the dictionary
for game_title, game_info in games.items():
    # Check if the game info is a dictionary before accessing keys
    if isinstance(game_info, dict):
        home_team = next((team for team in teams if team.name == game_info.get("home_team")), None)
        if not home_team:
            home_team = Team(game_info.get("home_team"))
            home_team.league = f'{game_info.get("home_division")}' + ' - ' + f'{game_info.get("home_conference")}'
            teams.append(home_team)
        away_team = next((team for team in teams if team.name == game_info.get("away_team")), None)
        if not away_team:
            away_team = Team(game_info.get("away_team"))
            away_team.league = f'{game_info.get("away_division")}' + ' - ' + f'{game_info.get("away_conference")}'
            teams.append(away_team)
            
        if game_info.get("completed") == True:
            home_team.games_played[game_title] = game_info
            away_team.games_played[game_title] = game_info
            try:
                margin = game_info.get("home_points") - game_info.get("away_points")
            except:
                margin = 0
            home_team.margin += margin
            away_team.margin -= margin
            # Update records based on the margin
            if margin > 0:
                home_team.record[0] += 1  # Home team wins
                away_team.record[1] += 1  # Away team loses
                home_team.games_played[game_title] = game_info.copy()  # Create a copy for the home team
                home_team.games_played[game_title]["result"] = "Win"
                away_team.games_played[game_title] = game_info.copy()  # Create a copy for the away team
                away_team.games_played[game_title]["result"] = "Loss"
            elif margin < 0:
                home_team.record[1] += 1  # Home team loses
                away_team.record[0] += 1  # Away team wins
                home_team.games_played[game_title] = game_info.copy()  # Create a copy for the home team
                home_team.games_played[game_title]["result"] = "Loss"
                away_team.games_played[game_title] = game_info.copy()  # Create a copy for the away team
                away_team.games_played[game_title]["result"] = "Win"
            else:  # Tie scenario
                home_team.record[2] += 1  # Tie for home team
                away_team.record[2] += 1  # Tie for away team
                home_team.games_played[game_title] = game_info.copy()  # Create a copy for the home team
                home_team.games_played[game_title]["result"] = "Tie"
                away_team.games_played[game_title] = game_info.copy()  # Create a copy for the away team
                away_team.games_played[game_title]["result"] = "Tie"
            if isinstance(game_info.get("notes"), str):
                if "championship" in game_info.get("notes").lower():
                    if margin > 0:
                        home_team.champ = True
                    elif margin < 0:
                        away_team.champ = True
        else:
            home_team.remaining_games[game_title] = game_info
            away_team.remaining_games[game_title] = game_info
            
    else:
        print(f"Unexpected data format for game: {game_title}")
        


team_json = {}
for team in teams:
        team_json[f"{team.name}"] = team.to_dict()
with open(config.json_teams_file, 'w') as json_file:
        json.dump(team_json, json_file, indent=4)