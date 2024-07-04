current_week = 0    # i need to find a good way to define current week in a mor erobust way so its not a variable i enter, although I want to be abel to run partial or hypothetical simulations too...
year = 2024

from bs4 import BeautifulSoup
import requests

#Define Team() and Game()
class Team:
    def __init__(self, name):
        self.name = name
        self.formatted_name = self.format_name(name)
        self.div = None
        self.conf = None
        self.record = [0,0,0]
        self.margin = 0
        self.champ = False
        self.credits = 0
        
    def format_name(self, name):
        return name.lower().replace(r' ', r'_').replace(r'-', r'_').replace(r'.',r'').replace(r"'",r'').replace(r'&',r'').replace(r'(',r'').replace(r')',r'')
    
class Game:
    def __init__(self, home_team, away_team, score: tuple = (0,0)):
        self.home_team = home_team
        self.away_team = away_team
        if isinstance (score, tuple):
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
                
                
#fetch game data
# List of URLs to fetch data from
urls = []
n = 1
while n <= current_week:
    week_n_urls = [
        f'https://www.ncaa.com/scoreboard/football/fbs/{year}/{n:02d}/all-conf',
        f'https://www.ncaa.com/scoreboard/football/fcs/{year}/{n:02d}/all-conf',
        f'https://www.ncaa.com/scoreboard/football/d2/{year}/{n:02d}/all-conf',
        f'https://www.ncaa.com/scoreboard/football/d3/{year}/{n:02d}/all-conf'
    ]
    for url in week_n_urls:
        urls.append(url)
    n += 1
    
    # Initialize an empty string to store the concatenated HTML content
    html_combined = ''
    
    # Loop thorugh the list of URLs
    for url in urls:
        response = requests.get(url)
        if response.status_code == 200:
            html = response.text
            # Concatenate the HTML content to the combined string
            html_combined += html
            print(f'Data fetched from {url}')
        else:
            print(f'Failed to retieve the webpage {url}. Status code: {response.status_code}')