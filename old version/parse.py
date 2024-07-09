# Parse soup/html and extract game data

from fetch import soup
from game import Game

#create a list of games
# Initialize a dictonary to store game results
games = {}

# Find game pods in the html for type 'game' and status 'final'
game_pods = soup.find_all('div', class_='gamePod gamePod-type-game status-final')

# Iterate through the game pods and extract information
for game_pod in game_pods:
    teams = game_pod.find_all('span', class_='gamePod-game-team-name')
    scores = game_pod.find_all('span', class_='gamePod-game-team-score')
    
    if len(teams) == 2 and len(scores) == 2:
        team1_name = teams[0].text.strip()
        team2_name = teams[1].text.strip()
        score1 = int(scores[0].text.strip())
        score2 = int(scores[1].text.strip())
        
        # Create a game object and store it in the games dictionary
        game = Game(team1_name, team2_name, (score1, score2))
        games[f"{team1_name} v {team2_name}"] = game
        
# Print the extract game results with scores
#for game_name, game_info in games.items():
#   print(f"{game_name}: Game({game_info.team1}, {game_info.team2}, {game_info.score})")

#store game info in a dictionary
games_dict = {}
for game_name, game_info in games.items():
    games_dict[game_name] = game_info
    
# eliminate duplicate games
# Create a new dictionary to store unique games
unique_games_dict = {}

# Iterate through the original dictionary and add games to the new dictionary
for game_name, game_instance in games.items():
    if game_instance not in unique_games_dict.values():
        unique_games_dict[game_name] = game_instance