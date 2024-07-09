import requests
from bs4 import BeautifulSoup

# Define the power 4 conferences
power_4_conferences = ["ACC", "Big 12", "Big Ten", "SEC"]
power_4_teams = []

fbs_standings_url = 'https://www.ncaa.com/standings/football/fbs'

response = requests.get(fbs_standings_url)

if response.status_code == 200:
    html_content = response.text
    
    # Parse the html content
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find all the conference figures
    conference_figures = soup.find_all('figure', class_='standings-conference')
    
    # Iterate through the conference figures and check if each team's conference is in the Power 4
    for figure in conference_figures:
        conference_name = figure.get_text(strip=True)   # Get the text content of the figure
        if conference_name in power_4_conferences:
            # Find the table in the same section as the Power 4 conference
            conference_table = figure.find_next_sibling('div').find('table')
            
            #Find all the team names in the table
            team_names = [team.text for team in conference_table.find_all('td', class_='standings-team')]
            
            # Add the team names to the list of all teams
            power_4_teams.extend(team_names)
            
    print(f'Data fetch from {fbs_standings_url}. Status code: {response.status_code}')
    
else:
    print(f'Failed to retrieve the webpage {fbs_standings_url}. Status code: {response.status_code}')
    
# Now you have all the teams in teh 'power_4_teams' list
# You can use this list to check if a team is a Power 4 team

#define FBS teams
fbs_teams = []
fbs_standings_url = 'https://www.ncaa.com/standings/football/fbs'

response = requests.get(fbs_standings_url)

if response.status_code == 200:
    html = response.text
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find all the table rows that contain team names
    team_rows = soup.select('.standings-team')
    
    # Extract the team names and add them to the FBS list
    for team_row in team_rows:
        team_name = team_row.text.strip()
        fbs_teams.append(team_name)
        
    print(f'Data fetched from {fbs_standings_url} for all the fbs teams')
    
else:
    print(f'Failed to retrieve the webpage {fbs_standings_url}. Status code: {response.status_code}')