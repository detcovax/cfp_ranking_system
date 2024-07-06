#create a list of all teams

from team import Team
from parse import games_dict as games

teams = []

for game_name, game_info in games.items():
    team1_name = game_info.home_team
    team2_name = game_info.away_team
    
    team1 = next((team for team in teams if team.name == team1_name), None)
    if not team1:
        team1 = Team(team1_name)
        teams.append(team1)
        
    team2 = next((team for team in teams if team.name == team2_name), None)
    if not team2:
        team2 = Team(team2_name)
        teams.append(team2)
        
# Create a dictionary to map team names to their corresponding Team objects
team_name_to_object = {team.name: team for team in teams}