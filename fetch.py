# This module will be used to connect to an online data source, fetch that data, and store in a format that can be used in the evaluation and generating steps.
import json, requests
from bs4 import BeautifulSoup


# Step 0: Get a full ist of schools
def get_listOfAllSchools():
    ncaa_schools_index_base = "https://www.ncaa.com/schools-index/"
    page = 0
    all_schools = []

    while True:
        response = requests.get(ncaa_schools_index_base + str(page))
        if response.status_code == 200:
            print(f"Successfully retrieving the webpage {ncaa_schools_index_base + str(page)}. Status code: {response.status_code}")

            # Parse the HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the table
            table = soup.find('table', class_='responsive-enabled')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    for row in rows:
                        # Extract the school name from the <td> element
                        school_name_td = row.find_all('td')[2]
                        if school_name_td:
                            school_name = school_name_td.get_text(strip=True)
                            if school_name:
                                all_schools.append(school_name)

            page += 1

        else:
            print(f"End of schools list or error retrieving page {page}. Status code: {response.status_code}")
            break
    
    return all_schools


# Step 1: Define data source as a set of urls
ncaa_schools = get_listOfAllSchools()

urls = []
ncaa_scores_url_base = "https://www.ncaa.com/scoreboard/football/"; urls.append(ncaa_scores_url_base)
ncaa_rankings_url_base = "https://www.ncaa.com/rankings/football/"; urls.append(ncaa_rankings_url_base)
ncaa_standings_url_base = "https://www.ncaa.com/standings/football/"; urls.append(ncaa_standings_url_base)
ncaa_stats_url_base = "https://www.ncaa.com/stats/football/"; urls.append(ncaa_stats_url_base)

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
    data = {}

    # Save to a JSON file
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)
        
        
        
    # Load the JSON file
    with open('data.json', 'r') as f:
        data = json.load(f)

    # Add a player to the Ohio State Buckeyes
    newTeams = {
        "ohio-state": {"div": "fbs", "conf": "bigten"},
        "michigan": {"div": "fbs", "conf": "bigten"}
    }

    data.update(newTeams)

    # Save the updated data back to the JSON file
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=4)



# Step 5: Querry through data and prepare for evaluation
    # I will need to go through the data and pick out all the players and create each one in a list on the team roster atribute
    # I will then need to go through the data again and assign all the fields to the teams and players accordingly.