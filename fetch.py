# This module will be used to connect to an online data source, fetch that data, and store in a format that can be used in the evaluation and generating steps.
import json, requests
from bs4 import BeautifulSoup


# Step 1: Define data source as a set of urls
urls = []
ncaa_scores_url_base = "https://www.ncaa.com/scoreboard/football/"; urls.append(ncaa_scores_url_base)
ncaa_rankings_url_base = "https://www.ncaa.com/rankings/football/"; urls.append(ncaa_rankings_url_base)
ncaa_standings_url_base = "https://www.ncaa.com/standings/football/"; urls.append(ncaa_standings_url_base)
ncaa_stats_url_base = "https://www.ncaa.com/stats/football/"; urls.append(ncaa_stats_url_base)

    # I need to get a list of all the teams, previously I did this by scrapping the scoreboard page for game results and list out each unique instance of a team, then create a team based on each one. Somethign liek this might work again. Maybe ncaa site just has a list of all teams somewhere to make it easier? Alternatively I could start from the standings page to pull all the teams by conference.

# Step 2: Request html from urls
def request_html():
    for url in urls:
        response = requests.get(url)
        if response.status_code == 200:
            print(f"Success retieving the webpage {url}. Status code: {response.status_code}")
        else:
            print(f"Failed to retieve the webpage {url}. Status code: {response.status_code}")

# Step 3: Parse html, identify and collect data

# Step 4: Clean data and store in a json file to be accessed later
def write2json():
# Initial JSON structure
    data = {"conferences":{
        "bigten":[],
        "sec":[],
        "big12":[],
        "acc":[],
        "pac12":[],
        "mountainwest":[],
        "mac":[],
        "sunbelt":[],
        "american":[],
        "fcs":[],
        "d2":[],
        "d3":[]
    }}

    # Save to a JSON file
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)
        
        
        
    # Load the JSON file
    with open('data.json', 'r') as f:
        data = json.load(f)

    # Add a player to the Ohio State Buckeyes
    newTeams = [{"ohio-state":{"games":[],"players":[]}},
                #{"michigan":{"games":[],"players":[]}}
            ]
    for newTeam in newTeams:
        data["conferences"]["bigten"].append(newTeam)

    # Save the updated data back to the JSON file
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)



# Step 5: Querry through data and prepare for evaluation
    # I will need to go through the data and pick out all the players and create each one in a list on the team roster atribute
    # I will then need to go through the data again and assign all the fields to the teams and players accordingly.