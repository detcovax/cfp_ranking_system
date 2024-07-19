# This module will be used to connect to an online data source, fetch that data, and store in a format that can be used in the evaluation and generating steps.

# Step 1: Define data source as a set of urls
urls = []
ncaa_scores_url_base = "https://www.ncaa.com/scoreboard/football/"
ncaa_rankings_url_base = "https://www.ncaa.com/rankings/football/"
ncaa_standings_url_base = "https://www.ncaa.com/standings/football/"
ncaa_stats_url_base = "https://www.ncaa.com/stats/football/"

# Step 2: Request html from urls

# Step 3: Parse html, identify and collect data

# Step 4: Clean data and store in a json file to be accessed later

# Step 5: Querry through data and prepare for evaluation
    # I will need to go through the data and pick out all the players and create each one in a list on the team roster atribute
    # I will then need to go through the data again and assign all the fields to the teams and players accordingly.