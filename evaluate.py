def evaluate_games(games):
    for game in games:
        game.home_team.games_played.append(game)
        game.away_team.games_played.append(game)
        if game.result[0] > game.result[1]:
            game.home_team.record[0] += 1
            game.away_team.record[1] += 1
        elif game.result[0] < game.result[1]:
            game.home_team.record[1] += 1
            game.away_team.record[0] += 1
        else:
            game.home_team.record[2] += 1
            game.away_team.record[2] += 1
        
        game.home_team.points[0] += game.result[0]
        game.home_team.points[1] += game.result[1]
        
        game.away_team.points[0] += game.result[1]
        game.away_team.points[1] += game.result[0]


def calculate_credits(teams):
    for team in teams:
        team.credits += team.record[0] - team.record[1]