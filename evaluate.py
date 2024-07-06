from parse import unique_games_dict
from teams_list import team_name_to_object

def evaluateGames():
    for game_name in unique_games_dict:
        game = unique_games_dict[game_name]
        margin_of_victory = abs(game.result[0] - game.result[1])
        if game.winner is not None:
            winner = team_name_to_object.get(game.winner)
            loser = team_name_to_object.get(game.loser)
            if winner and loser:
                winner.record[0] += 1
                loser.record[1] += 1
                winner.margin += margin_of_victory
                loser.margin -= margin_of_victory
                
        if 'Champ' in game_name:    # I think this needs to be fixed ot call for what the champ games in the html actually look like
            champ_team = team_name_to_object.get(game_name.replace('Champ','').strip())
            if champ_team:
                champ_team.champ = True