import json
import config
from team import Team

# Load the JSON file
with open(config.data_file, 'r') as json_file:
    teams = json.load(json_file)
    

team_list = []

for team_info in teams.values():
    team = Team(
        name=team_info.get("Name"),
        league=team_info.get("League"),
        record=team_info.get("Record"),
        margin=team_info.get("Margin"),
        champ=team_info.get("Conference Champion"),
        credits=team_info.get("Rankings Credits")
    )
    team.games_played=team_info.get("Games Played")
    team.remaining_games=team_info.get("Remaining Games")
    team.ratings=team_info.get("Ratings")
    team.roster=team_info.get("Roster")
    team_list.append(team)
    

    
power_index = sorted(
    team_list, key=lambda team:(
        (team.record[1] + (1 if "fbs" not in team.league.lower() else 0)) / sum(g for g in team.record) if sum(team.record) != 0 else 0,
        -(team.record[0] + (1 if "fbs" in team.league.lower() else 0) + (2 if "big ten" in team.league.lower() or "sec" in team.league.lower() else 0) + (1 if "big 12" in team.league.lower() or "acc" in team.league.lower() else 0)) / sum(g for g in team.record) if sum(team.record) != 0 else 0,
        -team.record[0],
        team.record[1],
        -team.margin/(team.record[0]+team.record[1]+team.record[2] if team.record[0]+team.record[1]+team.record[2] != 0 else 1),
        -team.margin
        )
    )

# fix head to head matchups if W-L is 2 or less difference (only works on adjacent teams for now)
for rank, team in enumerate(power_index, start=1):
    for game, game_info in team.games_played.items():
        home_team = game_info.get("home_team")
        away_team = game_info.get("away_team")
        opponent_name = home_team if home_team != team.name else away_team
        if game_info.get("result") == "Win" and power_index[rank-1].name == opponent_name and ((power_index[rank-1].record[0]-power_index[rank-1].record[1]) - (team.record[0]-team.record[1])) <= 2:
            power_index[rank], power_index[rank-1] = power_index[rank-1], power_index[rank]
       
# Step 1: Calculate Power Index Ranks
power_index_rank = {team.name: rank for rank, team in enumerate(power_index, start=1)}

# Step 2: Update credit calculations based on wins and losses
for team in team_list:
    # if "fbs" in team.league.lower():
    #     team.credits += 100
    #     if "big ten" in team.league.lower() or "sec" in team.league.lower():
    #         team.credits += 50
    if team.champ:
        team.credits += 100
    for game, game_info in team.games_played.items():
        home_team = game_info.get("home_team")
        away_team = game_info.get("away_team")
        opponent_name = home_team if home_team != team.name else away_team
        opponent_power = power_index_rank.get(opponent_name, 0)  # Default to 0 if opponent not found
        team_power = power_index_rank.get(team.name, 0)  # Get the current team's rank
        power_diff = abs(team_power - opponent_power) # NEED TO FIX THE POWER DIFF
        if home_team == team.name:
            opponent_league = f'{game_info.get("away_division")}' + ' - ' + f'{game_info.get("away_conference")}'
        elif away_team == team.name:
            opponent_league = f'{game_info.get("home_division")}' + ' - ' + f'{game_info.get("home_conference")}'
        else:
            opponent_league = 'none'

        point_margin = abs(game_info.get("home_points")-game_info.get("away_points")) if game_info.get("home_points") is not None and game_info.get("away_points") is not None else 0
        point_margin_multiplier = point_margin/7
        if point_margin_multiplier < 1:
            point_margin_multiplier = 1
        
        if game_info.get("result") == "Win":
            win_scale = 1
            if "fbs" in opponent_league.lower():
                win_scale *= 10
                if "big ten" in opponent_league.lower() or "sec" in opponent_league.lower():
                    win_scale *= 5
                elif "acc" in opponent_league.lower() or "big 12" in opponent_league.lower():
                    win_scale *= 3
            elif "fcs" in opponent_league.lower():
                win_scale *= 2
            if opponent_power !=0:
                if opponent_power < 5:
                    win_scale *= 12
                elif opponent_power < 10:
                    win_scale *= 10
                elif opponent_power < 15:
                    win_scale *= 7
                elif opponent_power < 25:
                    win_scale *= 5
                elif opponent_power < 50:
                    win_scale *= 3
                elif opponent_power < 100:
                    win_scale *= 2
                    
        elif game_info.get("result") == "Loss" and point_margin > 0:
            win_scale = -1
            if "fbs" not in opponent_league.lower():
                if "fcs" not in opponent_league.lower():
                    win_scale *= 10
                else:
                    win_scale *= 5
            else:
                if "big ten" not in opponent_league.lower() and "sec" not in opponent_league.lower():
                    if "acc" not in opponent_league.lower() and "big 12" not in opponent_league.lower():
                        win_scale *= 3
                    else:
                        win_scale *= 2
            if opponent_power < 100:
                if opponent_power > 25:
                    win_scale *= 2
                elif opponent_power > 50:
                    win_scale *= 3
            else:
                win_scale *= 5
                
        else:
            win_scale = 0
        
        credits = point_margin_multiplier*win_scale*power_diff/1000     # NEED TO FIX THE POWER DIFF (JUST MULTIPLIES BY ABS DIFF, NEED TO CONSIDER IF OPP IS HIGHER LOWER)
        if abs(credits) < 1 and abs(credits) !=0 and point_margin > 0:
            credits = credits/abs(credits)
        credits = int(credits)
        team.games_played[game]["win_credits"] = credits
        team.credits += credits

rankings = sorted(power_index, key=lambda team: (-team.credits))

# fix head to head matchups if credits are no more than 100 or less (only works on adjacent teams for now)
for rank, team in enumerate(rankings, start=1):
    for game, game_info in team.games_played.items():
        home_team = game_info.get("home_team")
        away_team = game_info.get("away_team")
        opponent_name = home_team if home_team != team.name else away_team
        if game_info.get("result") == "Win" and rankings[rank-1].name == opponent_name and (rankings[rank-1].credits - team.credits) <= 100:
            rankings[rank], rankings[rank-1] = rankings[rank-1], rankings[rank]

for power, team in enumerate(power_index, start=1):
    team.power = power
for rank, team in enumerate(rankings, start=1):
    team.rank = rank

with open('rankings.txt', 'w', encoding="utf-8") as output_file:
    output_file.write("Dave's Power Index:")
    for rank, team in enumerate(power_index, start=1):
        if rank > 15:
            break
        else:
            output_file.write('\n ')
            margin_sign = "+" if team.margin > 0 else ""
            output_file.write(f'{rank}. {team.name} ')
            output_file.write("(C) " if team.champ == True else "")
            if team.record[2] == 0:
                output_file.write(f'({team.record[0]}-{team.record[1]})')
            elif team.record[2] > 0:
                output_file.write(f'({team.record[0]}-{team.record[1]}-{team.record[2]})')
            else:
                output_file.write(f'(Error {team.record})')
            output_file.write(f' ({margin_sign}{team.margin})')
    output_file.write('\n\n\nRankings:')
    for rank, team in enumerate(rankings, start=1):
        if rank > 30:
            break
        else:
            output_file.write('\n ')
            output_file.write(f'{rank}. {team.name} ')
            output_file.write("(C) " if team.champ == True else "")
            if team.record[2] == 0:
                output_file.write(f'({team.record[0]}-{team.record[1]})')
            elif team.record[2] > 0:
                output_file.write(f'({team.record[0]}-{team.record[1]}-{team.record[2]})')
            else:
                output_file.write(f'(Error {team.record})')
            output_file.write(f' ({team.credits})')
            
            

with open('reports.txt', 'w', encoding="utf-8") as output_file:
    output_file.write("Team Reports:\n")
    for team in rankings:
        output_file.write(
            "\n"
            f"{team.rank}. {team.name}" + (f"   {team.league} Champion" if team.champ==True else "") + "\n"
            f"   Dave's Power Index Ranking: {team.power}\n"
            f"   Record: {team.record[0]}-{team.record[1]}-{team.record[2]}\n"
            f"   Margin: {('+' if team.margin > 0 else '')}{team.margin}\n"
            f"   Total Credits: {team.credits}\n"
            f"   Schedule:\n"
        )
        for game, game_info in team.games_played.items():
            result = game_info.get("result")
            home_team = game_info.get("home_team")
            away_team = game_info.get("away_team")
            home_points = game_info.get("home_points")
            away_points = game_info.get("away_points")
            notes = game_info.get("notes")
            credits = game_info.get("win_credits")
            output_file.write(
                f"      " + (f"{notes}: " if notes else "") + f"{home_team}" + f" ({home_points})" + " vs. " + f"{away_team}" + f" ({away_points})" + f" - {result} ({credits} Win Credits)" + "\n"
            )
        for game, game_info in team.remaining_games.items():
            week = game_info.get("week")
            home_team = game_info.get("home_team")
            away_team = game_info.get("away_team")
            notes = game_info.get("notes")
            output_file.write(
                f"      Week {week} - " + (f"{notes}: " if notes else "") + f"{home_team}" + " vs. " + f"{away_team}" + "\n"
            )
        output_file.write(f"    Games Remaining: {len(team.remaining_games)}")
        output_file.write("\n")