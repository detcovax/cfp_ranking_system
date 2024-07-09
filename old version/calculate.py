from main import power_index
from parse import unique_games_dict
from teams_list import teams, team_name_to_object
from conferences import power_4_teams

# Calculate Credits
def calculateCredits():
    for game_name in unique_games_dict:
        game = unique_games_dict[game_name]
        margin_of_victory = abs(game.result[0] - game.result[1])
        if game.winner is not None:
            winner = team_name_to_object.get(game.winner)
            loser = team_name_to_object.get(game.loser)
        if 'Champ' not in game_name:    # I think this needs to be fixed ot call for what the champ games in the html actually look like
            if winner:
                if loser in power_4_teams:
                    winner.credits += 1000
                    winner.credits += ((len(teams) - power_index.index(loser)) + (100 if abs(margin_of_victory) >= 18 else 0))*2
                    winner.credits += 100 if power_index.index(loser) < 10 else 0
                else:
                    winner.credits += (len(teams) - power_index.index(loser)) + (100 if abs(margin_of_victory) >= 18 else 0)
                if winner not in power_4_teams:
                    loser.credits -= 1000
                    loser.credits -= ((len(teams) - power_index.index(winner)) + (100 if abs(margin_of_victory) >= 18 else 0))*2
                else:
                    loser.credits -= (len(teams) - power_index.index(winner)) + (100 if abs(margin_of_victory) >= 18 else 0)
        if 'Champ' in game_name:
            winner.credits += 1000 + (250 if abs(margin_of_victory) >= 18 else 0)
                    