from bs4 import BeautifulSoup
import requests

current_week = 15

# Define Team() and Game()
class Team:
    def __init__(self, name):
        self.name = name
        self.formatted_name = self.format_name(name)
        self.record = [0,0,0]
        self.margin = 0
        self.champ = False
        self.credits = 0
        self.power5 = False

    def format_name(self, name):
        return name.lower().replace(r' ', r'_').replace(r'-', r'_').replace(r'.', r'').replace(r"'", r"").replace(r'&', r'').replace(r'(', r'').replace(r')', r'')

class Game:
    def __init__(self, home_team, away_team, score: tuple = (0, 0)):
        self.home_team = home_team
        self.away_team = away_team
        if isinstance(score, tuple):
            self.result = score
            if self.result[0] > self.result[1]:
                self.winner = home_team
                self.loser = away_team
            elif self.result[0] < self.result[1]:
                self.winner = away_team
                self.loser = home_team
            else:
                self.winner = None
                self.loser = None


# fetch game data
# List of URLs to fetch data from
urls = []
n = 1
while n <= current_week:
  week_n_urls = [
      f'https://www.ncaa.com/scoreboard/football/fbs/2023/{n:02d}/all-conf',
      f'https://www.ncaa.com/scoreboard/football/fcs/2023/{n:02d}/all-conf',
      f'https://www.ncaa.com/scoreboard/football/d2/2023/{n:02d}/all-conf',
      f'https://www.ncaa.com/scoreboard/football/d3/2023/{n:02d}/all-conf'
  ]
  for url in week_n_urls:
    urls.append(url)
  n += 1

# Initialize an empty string to store the concatenated HTML content
html_combined = ''

# Loop through the list of URLs
for url in urls:
    response = requests.get(url)
    if response.status_code == 200:
        html = response.text
        # Concatenate the HTML content to the combined string
        html_combined += html
        print(f'Data fetched from {url}')
    else:
        print(f"Failed to retrieve the webpage {url}. Status code: {response.status_code}")

soup = BeautifulSoup(html_combined, 'html.parser')

# create list of games
# Initialize a dictionary to store game results
games = {}

# Find game pods in the HTML
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

# Print the extracted game results with scores
#for game_name, game_info in games.items():
#    print(f"{game_name}: Game({game_info.team1}, {game_info.team2}, {game_info.score})")

# If you want to store it as a dictionary as requested, you can simply do:
games_dict = {}
for game_name, game_info in games.items():
    games_dict[game_name] = game_info

# create list of teams
teams = []
for game_name, game_info in games_dict.items():
    team1_name = game_info.home_team  # Use home_team and away_team
    team2_name = game_info.away_team

    team1 = next((team for team in teams if team.name == team1_name), None)
    if not team1:
        team1 = Team(team1_name)
        teams.append(team1)

    team2 = next((team for team in teams if team.name == team2_name), None)
    if not team2:
        team2 = Team(team2_name)
        teams.append(team2)

# eliminate duplicate games
# Create a new dictionary to store unique games
unique_games_dict = {}

# Iterate through the original dictionary and add games to the new dictionary
for game_name, game_instance in games_dict.items():
    if game_instance not in unique_games_dict.values():
        unique_games_dict[game_name] = game_instance

# Define the Power 5 conferences
power_5_conferences = ["ACC", "Big 12", "Big Ten", "SEC", "Pac-12"]

# Create an empty list to store all teams
power_5_teams = []

fbs_standings_url = 'https://www.ncaa.com/standings/football/fbs'

response = requests.get(fbs_standings_url)

if response.status_code == 200:
    html_content = response.text

    # Parse the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all the conference figures
    conference_figures = soup.find_all("figure", class_="standings-conference")

    # Iterate through the conference figures and check if each team's conference is in the Power 5
    for figure in conference_figures:
        conference_name = figure.get_text(strip=True)  # Get the text content of the figure
        if conference_name in power_5_conferences:
            # Find the table in the same section as the Power 5 conference
            conference_table = figure.find_next_sibling("div").find("table")

            # Find all the team names in the table
            team_names = [team.text for team in conference_table.find_all("td", class_="standings-team")]

            # Add the team names to the list of all teams
            power_5_teams.extend(team_names)

    print(f'Data fetched from {fbs_standings_url} for power5')

else:
    print(f"Failed to retrieve the webpage {fbs_standings_url}. Status code: {response.status_code}")

# Now you have all the teams in the `power_5_teams` list
# You can use this list to check if a team is a Power 5 team or for other purposes


cfp_ranking = []

cfp_week = {    # Rewrite this so I dont have to manually define the weeks
    1:  '',
    2:  '',
    3:  '',
    4:  '',
    5:  '',
    6:  '',
    7:  '',
    8:  '',
    9:  '',
    10:  '/10/31/cfp-rankings-2023-1031',
    11:  '/11/7/cfp-rankings-2023-1107',
    12:  '/11/14/cfp-rankings-2023-1114',
    13:  '/11/21/cfp-rankings-2023-1121',
    14:  '/11/28/cfp-rankings-2023-1128',
    15:  '/12/3/cfp-rankings-2023-1203',
}

cfp_url = 'https://collegefootballplayoff.com/news/2023' + cfp_week[current_week]   # Fix what happens if current_week does not exist in cfp

response = requests.get(cfp_url)

if response.status_code == 200:
    html_content = response.text

    # Parse the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Find the table with the class "cfp-table"
    table = soup.find('table', class_='cfp-table')

    # Find all the rows in the table (skip the header row)
    rows = table.find_all('tr')[1:]

    # Loop through the rows and extract the ranking, team, and record
    for row in rows:
        columns = row.find_all('td')
        ranking = columns[0].text.strip()
        team_name = columns[1].text.strip().replace('State','St.')
        team_name = team_name.replace('Mississippi', 'Ole Miss').replace('Ole Miss St.','Mississippi St.')   #Ole Miss name issue
        for team in teams:
          if team.name == team_name:
            cfp_team = team
            # Append the team to the cfp_ranking list
            cfp_ranking.append(cfp_team)

    print(f'Data fetched from {cfp_url}')

else:
    print(f"Failed to retrieve the webpage. Status code: {response.status_code}")



# reset teams
for team in teams:
    team.record = [0, 0, 0]
    team.margin = 0
    team.champ = False
    team.credits = 0

# Apply +10 margin bonus to Power 5 teams
for team in teams:
    if team.name in power_5_teams:
        team.credits = 3000


# Create a dictionary to map team names to their corresponding Team objects
team_name_to_object = {team.name: team for team in teams}

# Evaluate games
for game_name in unique_games_dict:
    game = unique_games_dict[game_name]
    if game.winner is not None:
        margin_of_victory = abs(game.result[0] - game.result[1])
        winner = team_name_to_object.get(game.winner)
        loser = team_name_to_object.get(game.loser)
        if winner and loser:
            winner.record[0] += 1
            loser.record[1] += 1
            winner.margin += margin_of_victory
            loser.margin -= margin_of_victory

    if 'Champ' in game_name:
        champ_team = team_name_to_object.get(game_name.replace('Champ', '').strip())
        if champ_team:
            champ_team.champ = True


# Power Index
power_index = sorted(teams, key=lambda team: (-team.record[0] + (4 if team.name not in power_5_teams else 0), team.record[1] + (4 if team.name not in power_5_teams else 0), -team.margin))


# Calculate credits
for game_name in unique_games_dict:
    game = unique_games_dict[game_name]
    if game.winner is not None:
        winner = team_name_to_object.get(game.winner)
        loser = team_name_to_object.get(game.loser)
    if 'Champ' not in game_name:
        if winner:
            if loser in power_5_teams:
              winner.credits += 1000
              winner.credits += ((len(teams) - power_index.index(loser)) + (100 if abs(game.result[0]-game.result[1]) >= 18 else 0))*2
              winner.credits += 100 if power_index.index(loser) < 10 else 0
            else:
              winner.credits += (len(teams) - power_index.index(loser)) + (100 if abs(game.result[0]-game.result[1]) >= 18 else 0)
            if winner not in power_5_teams:
              loser.credits -= 1000
              loser.credits -= ((len(teams) - power_index.index(winner)) + (100 if abs(game.result[0]-game.result[1]) >= 18 else 0))*2
            else:
              loser.credits -= (len(teams) - power_index.index(winner)) + (100 if abs(game.result[0]-game.result[1]) >= 18 else 0)
    if 'Champ' in game_name:
        winner.credits += 1000 + (250 if abs(game.result[0]-game.result[1]) >= 18 else 0)


# Rankings
rankings = sorted(teams, key=lambda team: (-team.credits, -team.record[0] + (1 if team.name not in power_5_teams else 0), team.record[1] + (1 if team.name not in power_5_teams else 0), -team.champ, -team.margin))
#head-to-head preference
for n in range(50):
    for game_name in unique_games_dict:
        game = unique_games_dict[game_name]
        if game.winner is not None:
            winner = team_name_to_object.get(game.winner)
            loser = team_name_to_object.get(game.loser)
        if winner == rankings[n] and loser == rankings[n-1] and loser.credits - winner.credits < 100:
            # Swap the positions of the winners and losers in the rankings
            rankings[n], rankings[n-1] = rankings[n-1], rankings[n]
# Switch to using .pop() and .insert() to just move the winner ahead of the loser. also consider if teams are more than one rank apart?


#keep only FBS teams in standings
fbs_teams = []
fbs_standings_url = 'https://www.ncaa.com/standings/football/fbs'

response = requests.get(fbs_standings_url)

if response.status_code == 200:
    html = response.text
    soup = BeautifulSoup(html, 'html.parser')

    # Find all the table rows that contain team names
    team_rows = soup.select('.standings-team')

    # Extract the team names and add them to the list
    for team_row in team_rows:
        team_name = team_row.text.strip()
        fbs_teams.append(team_name)

    print(f'Data fetched from {fbs_standings_url} for all fbs teams')

else:
    print(f"Failed to retrieve the webpage {fbs_standings_url}. Status code: {response.status_code}")


new_power_index = [team for team in power_index if team.name in fbs_teams]
power_index = new_power_index

new_rankings = [team for team in rankings if team.name in fbs_teams]
rankings = new_rankings


#function to generate team reports when called
def generate_team_report(team):
    # Check if the team is ranked in the top 25
    team_rank = None
    team_power_index_rank = None
    team_cfp_ranking = None

    for rank, ranked_team in enumerate(rankings, start=1):
        if team.name == ranked_team.name:
            team_rank = rank
            break

    for rank, ranked_team in enumerate(power_index, start=1):
        if team.name == ranked_team.name:
            team_power_index_rank = rank
            break

    for rank, ranked_team in enumerate(cfp_ranking, start=1):
        if team.name == ranked_team.name:
            team_cfp_ranking = rank
            break


    report = "\n" + "REPORT" + "\n" + f"___________________________________________________" + "\n"
    report += f"Team: {team.name}" + f" {'(Conference Champion)' if team.champ else ''}"
    if team_rank is not None:
        report += "\n" + f"Rank: {team_rank}"
    if team_power_index_rank is not None:
        report += "\n" + f"Power Index: {team_power_index_rank}"
    if team_cfp_ranking is not None:
        report += "\n" + f"CFP: {team_cfp_ranking}"
    report += "\n"
    report += f"Overall Record: {team.record[0]}-{team.record[1]}"
    if team.record[2] > 0:
        report += f"-{team.record[2]}\n"
    else:
        report += "\n"
    report += f"Margin: {('+' if team.margin > 0 else '')}{team.margin}\n"
    report += f"Credits: {team.credits}\n"

    report += "\n" + "Schedule:\n"
    games_remaining = 12  # Counter for games remaining
    for game_name, game_info in games_dict.items():
        if game_info.home_team == team.name or game_info.away_team == team.name:
            result = "W" if game_info.winner == team.name else "L" if game_info.loser == team.name else "T"

            #keep count of games left in regular season
            if games_remaining > 0:
                games_remaining -= 1

            team_rank_home = None
            team_rank_away = None

            for rank, ranked_team in enumerate(rankings, start=1):
                if game_info.home_team == ranked_team.name:
                    team_rank_home = rank
                if game_info.away_team == ranked_team.name:
                    team_rank_away = rank

            #does not show yet but this gives the ability to denote if an opponent is a power_index team
            for power, power_team in enumerate(power_index, start=1):
                if game_info.home_team == power_team.name:
                    team_power_home = power
                if game_info.away_team == power_team.name:
                    team_power_away = power

            team_name_home = f"{team_rank_home}. {game_info.home_team}" if team_rank_home is not None and team_rank_home <= 25 else game_info.home_team
            team_name_away = f"{team_rank_away}. {game_info.away_team}" if team_rank_away is not None and team_rank_away <= 25 else game_info.away_team

            report += f"({result})   {team_name_home} ({game_info.result[0]}) at {team_name_away} ({game_info.result[1]})\n"

    report += f"Games Remaining: {games_remaining}\n"
    report += f"___________________________________________________"

    return report



# PRINTING OF RANKINGS AND REPORTS

# print power index
print('')
print('Power Index:')
for rank, team in enumerate(power_index, start=1):
    if rank > 25:
        break
    else:
        margin_sign = "+" if team.margin > 0 else ""
        if team.record[2] == 0:
            print(f'{rank}. {team.name} ({team.record[0]}-{team.record[1]}) ({margin_sign}{team.margin})')
        elif team.record[2] > 0:
            print(f'{rank}. {team.name} ({team.record[0]}-{team.record[1]}-{team.record[2]}) ({margin_sign}{team.margin})')
        else:
            print(f'{rank}. {team.name} (Error {team.record}) ({margin_sign}{team.margin})')


# print rankings
print('')
print('Rankings:')
for rank, team in enumerate(rankings, start=1):
    if rank > 30:
        break
    else:
        champ_win = 1 if team.champ else 0
        champ_text = "*" if team.champ else ""
        margin_sign = "+" if team.margin > 0 else ""
        if team.record[2] == 0:
            print(f'{rank}. {team.name}{champ_text} ({team.record[0]+champ_win}-{team.record[1]}) {team.credits}')
        elif team.record[2] > 0:
            print(f'{rank}. {team.name}{champ_text} ({team.record[0]+champ_win}-{team.record[1]}-{team.record[2]}) {team.credits}')
        else:
            print(f'{rank}. {team.name}{champ_text} (Error {team.record}) ({margin_sign}{team.margin}) {team.credits}')


#print cfp rankings
print('\n' + 'CFP Committee Rankings:')
if len(cfp_ranking) > 0:
    for rank, team in cfp_ranking:
        print(f"{rank}. {team.name}")
else:
    print('First CFP Rankings in week 10')



print('')


# create list of teams to print reports for
report_teams = []

for rank, team in enumerate(rankings, start=1):
    if rank > 25:
        break
    else:
        report_teams.append(team.name)

# Iterate through teams and generate reports for those in report_teams
for team in rankings:
    if team.name in report_teams:
        team_report = generate_team_report(team)
        print(team_report)

# print reports for CFP top 25 not already printed
for rank, team in enumerate(cfp_ranking, start=1):
    if team.name not in report_teams:
        team_report = generate_team_report(team)
        print(team_report)