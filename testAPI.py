import cfbd, json

def convert_sets_to_lists(obj):
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(i) for i in obj]
    else:
        return obj

configuration = cfbd.Configuration()
configuration.api_key['Authorization'] = '+Sqyig0d+UEMqF2z6qHGsIhEtTs1vdeFIqeE+1Sa3wANtLXMOiydjvXKC/iU39Xp'
configuration.api_key_prefix['Authorization'] = 'Bearer'

api_instance = cfbd.GamesApi(cfbd.ApiClient(configuration))
games = api_instance.get_games(year=2023, season_type='both')

json_dump_file = 'api_test.json'
data_to_dump = {}

# with open(json_dump_file, 'w') as json_file:
#         json.dump({}, json_file, indent=4)
    
n = 0
for game in games:
        n += 1
        data_to_dump[(f"{game.notes}: " if game.notes else "") + f"{game.home_team} vs. {game.away_team}"] = game.to_dict()
with open(json_dump_file, 'w') as json_file:
        json.dump(data_to_dump, json_file, indent=4)