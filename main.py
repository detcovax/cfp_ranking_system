from setup import *
from teams_list import teams, team_name_to_object
from conferences import power_4_teams
from evaluate import evaluateGames
from calculate import calculateCredits
from parse import unique_games_dict
    
for team in teams:
    # Reset teams
    team.resetTeam()
    # Apply a bonus credit to power 4 teams
    if team.name in power_4_teams:
        team.credits = 3000


evaluateGames()

# Power Index
power_index = sorted(teams, key=lambda team: (-team.record[0] + (4 if team.name not in power_4_teams else 0), team.record[1] + (4 if team.name not in power_4_teams else 0), -team.margin))

calculateCredits()

# Rankings
rankings = sorted(teams, key=lambda team: (-team.credits, -team.record[0] + (1 if team.name not in power_4_teams else 0), team.record[1] + (1 if team.name not in power_4_teams else 0), -team.champ, -team.margin))
#head-to-head preference
for n in range(50):
    for game_name in unique_games_dict:
        game = unique_games_dict[game_name]
        if game.winner is not None:
            winner = team_name_to_object.get(game.winner)
            loser = team_name_to_object.get(game.loser)
        if winner == rankings[n] and loser == rankings[n-1] and loser.credits - winner.credits < 100:
            # Swap the position of the winner and loser in the rankings for head-to-head win if the credits are close enough
            rankings[n], rankings[n-1] = rankings[n-1], rankings[n]
            
#keep only the FBS teams in standings
fbs_teams = []
fbs_standings_url = 'https://www.ncaa.com/standings/football/fbs'

new_power_index = [team for team in power_index if team.name in fbs_teams]
power_index = new_power_index

new_rankings = [team for team in rankings if team.name in fbs_teams]
rankings = new_rankings