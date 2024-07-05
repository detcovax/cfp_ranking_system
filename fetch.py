from bs4 import BeautifulSoup
import requests
from main import current_week, year

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