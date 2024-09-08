import cfbd, json
import config
from team import Team

season_year = config.year # int | Season year (optional)
week = config.week # int | Week filter (optional)
season_type = 'both' # str | Season type filter (regular or postseason) (optional) (default to regular)


# Configure API key authorization: ApiKeyAuth
configuration = cfbd.Configuration()
configuration.api_key['Authorization'] = '+Sqyig0d+UEMqF2z6qHGsIhEtTs1vdeFIqeE+1Sa3wANtLXMOiydjvXKC/iU39Xp'
# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
configuration.api_key_prefix['Authorization'] = 'Bearer'
# API Client
client = cfbd.ApiClient(configuration)

# create an instance of the API class
teams_api = cfbd.TeamsApi(client)
games_api = cfbd.GamesApi(client)
rankings_api = cfbd.RankingsApi(client)
ratings_api = cfbd.RatingsApi(client)

print("connecting to api...")
rosters = teams_api.get_roster(year=season_year)
games = games_api.get_games(year=season_year, season_type='both')
rankings = rankings_api.get_rankings(year=season_year)
fpi = ratings_api.get_fpi_ratings(year=season_year)

print("initializing...")
teams = []


print("fetching games...")
for game in games:
    game_title = (f"{game.notes}: " if game.notes else "") + f"{game.home_team} vs. {game.away_team}"
    home_team = next((team for team in teams if team.name == game.home_team), None)
    if not home_team:
        home_team = Team(game.home_team)
        home_team.league = f'{game.home_division}' + ' - ' + f'{game.home_conference}'
        teams.append(home_team)
    away_team = next((team for team in teams if team.name == game.away_team), None)
    if not away_team:
        away_team = Team(game.away_team)
        away_team.league = f'{game.away_division}' + ' - ' + f'{game.away_conference}'
        teams.append(away_team)
    if game.completed == True:
        home_team.games_played[game_title] = game
        away_team.games_played[game_title] = game
        try:
            margin = game.home_points - game.away_points
        except:
            margin = 0
        home_team.margin += margin
        away_team.margin -= margin
        
        # Update records based on the margin
        if margin > 0:
            home_team.record[0] += 1  # Home team wins
            away_team.record[1] += 1  # Away team loses
            home_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the home team
            home_team.games_played[game_title]["result"] = "Win"
            away_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the away team
            away_team.games_played[game_title]["result"] = "Loss"
        elif margin < 0:
            home_team.record[1] += 1  # Home team loses
            away_team.record[0] += 1  # Away team wins
            home_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the home team
            home_team.games_played[game_title]["result"] = "Loss"
            away_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the away team
            away_team.games_played[game_title]["result"] = "Win"
        else:  # Tie scenario
            home_team.record[2] += 1  # Tie for home team
            away_team.record[2] += 1  # Tie for away team
            home_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the home team
            home_team.games_played[game_title]["result"] = "Tie"
            away_team.games_played[game_title] = game.to_dict().copy()  # Create a copy for the away team
            away_team.games_played[game_title]["result"] = "Tie"
        # Championship Scenario
        if isinstance((game.notes), str):
            if "championship" in game.notes.lower():
                if margin > 0:
                    home_team.champ = True
                elif margin < 0:
                    away_team.champ = True
    else:
        home_team.remaining_games[game_title] = game.to_dict().copy()
        away_team.remaining_games[game_title] = game.to_dict().copy()

print("fetching rosters...")
for player in rosters:
    team = next((team for team in teams if team.name == player.team), None)
    if not team:
        team = Team(player.team)
        teams.append(team)
    team.roster.append(player.to_dict())

print("fetching fpi standings...")
for school in fpi:
    team = next((team for team in teams if team.name == school.team), None)
    if not team:
        team = Team(school.team)
        teams.append(team)
    team.ratings["FPI"] = school.to_dict()

n = 0
while n <= week:
    print(f"fetching week {n} rankings...")
    try:
        for poll in rankings[n].polls:
            for rank in poll.ranks:
                team = next((team for team in teams if team.name == rank.school), None)
                if not team:
                    team = Team(rank.school)
                    teams.append(team)
                team.ratings[f"{poll.poll} Week {rankings[n].week}"] = rank.to_dict()
    except:
        pass
    n += 1

print("writing to file...")
data_file = config.data_file
data_to_dump = {}
for team in teams:
    data_to_dump[f"{team.name}"] = team.to_dict()
with open(data_file, 'w', encoding="utf-8") as json_file:
    json.dump(data_to_dump, json_file, indent=4)