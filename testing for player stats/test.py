from __future__ import print_function
import time
import cfbd
from cfbd.rest import ApiException

# Configure API key authorization: ApiKeyAuth
configuration = cfbd.Configuration()
configuration.api_key['Authorization'] = '+Sqyig0d+UEMqF2z6qHGsIhEtTs1vdeFIqeE+1Sa3wANtLXMOiydjvXKC/iU39Xp'
# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
configuration.api_key_prefix['Authorization'] = 'Bearer'

# create an instance of the API class
api_instance = cfbd.PlayersApi(cfbd.ApiClient(configuration))
year = 2024 # int | Year filter
team = 'Ohio State' # str | Team filter (optional)
# conference = 'conference_example' # str | Conference abbreviation filter (optional)
# start_week = 56 # int | Start week filter (optional)
# end_week = 56 # int | Start week filter (optional)
season_type = 'both' # str | Season type filter (regular, postseason, or both) (optional)
# category = 'category_example' # str | Stat category filter (e.g. passing) (optional)

try:
    # Player stats by season
    api_response = api_instance.get_player_season_stats(
        year,
        team=team,
        #conference=conference,
        #start_week=start_week,
        #end_week=end_week,
        season_type=season_type,
        #category=category
    )
    open('example.txt', 'w')
    open('example.txt', 'a').write(str(api_response))
    # for stat in api_response:
    #     open('example.txt', 'a').write(str(stat)+'\n\n')
except ApiException as e:
    open('example.txt', 'w').write("Exception when calling PlayersApi->get_player_season_stats: %s\n" % e)