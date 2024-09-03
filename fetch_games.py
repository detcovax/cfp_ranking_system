import cfbd, json
import config

configuration = cfbd.Configuration()
configuration.api_key['Authorization'] = '+Sqyig0d+UEMqF2z6qHGsIhEtTs1vdeFIqeE+1Sa3wANtLXMOiydjvXKC/iU39Xp'
configuration.api_key_prefix['Authorization'] = 'Bearer'

api_instance = cfbd.GamesApi(cfbd.ApiClient(configuration))
games = api_instance.get_games(year=config.year, season_type='both')


data_to_dump = {}
    
n = 0
for game in games:
        n += 1
        data_to_dump[(f"{game.notes}: " if game.notes else "") + f"{game.home_team} vs. {game.away_team}"] = game.to_dict()
with open(config.json_games_file, 'w') as json_file:
        json.dump(data_to_dump, json_file, indent=4)