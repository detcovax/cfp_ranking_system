import requests
from bs4 import BeautifulSoup
from setup import current_week, year
from teams_list import teams

cfp_ranking = []

cfp_week = {    # Find a way to get this more systematically
    1: f'',
    2: f'',
    3: f'',
    4: f'',
    5: f'',
    6: f'',
    7: f'',
    8: f'',
    9: f'',
    10:f'',
    11:f'',
    12:f'',
    13:f'',
    14:f'',
    15:f'',
}

cfp_url = 'https://collegefootballplayoff.com/news/2023' + cfp_week[current_week]

response = requests.get(cfp_url)

if response.status_code == 200:
    html_content = response.text
    
    # Parse the html content
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find the table with the class "cfp-table"
    table = soup.find('table', class_='cfp-table')
    
    # Find all the rows in the table (skip the header)
    rows = table.find_all('tr')[1:]
    
    #Loop through the rows and extract the ranking, team, and record
    for row in rows:
        columns = row.find_all('td')
        ranking = columns[0].text.strip()
        team_name = columns[1].text.strip().replace('State','St.')
        team_name = team_name.replace('Mississippi','Ole Miss').replace('Ole Miss St.','Mississippi St.')
        for team in teams:
            if team.name == team_name:
                cfp_team = team
                # Append the team to the cfp_ranking list
                cfp_ranking.append(cfp_team)
            
    print(f'Data fetched from {cfp_url}')
    
else:
    print(f'Failed to retrieve the webpage {cfp_url}. Status code: {response.status_code}')