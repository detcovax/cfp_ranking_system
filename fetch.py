# This module will be used to connect to an online data source, fetch that data, and store in a format that can be used in the evaluation and generating steps.
import json, requests
from bs4 import BeautifulSoup

# urls = []
# https://collegefootballdata.com/
# ncaa_scores_url_base = "https://www.ncaa.com/scoreboard/football/"; urls.append(ncaa_scores_url_base)
# ncaa_rankings_url_base = "https://www.ncaa.com/rankings/football/"; urls.append(ncaa_rankings_url_base)
# ncaa_standings_url_base = "https://www.ncaa.com/standings/football/"; urls.append(ncaa_standings_url_base)
# ncaa_stats_url_base = "https://www.ncaa.com/stats/football/"; urls.append(ncaa_stats_url_base)



def get_listOfAllSchools():
    ncaa_schools_index_baseurl = "https://www.ncaa.com/schools-index/"
    page = 0
    all_schools = []

    while True:
        response = requests.get(ncaa_schools_index_baseurl + str(page))
        if response.status_code == 200:
            print(f"Successfully retrieving the webpage {ncaa_schools_index_baseurl + str(page)}. Status code: {response.status_code}")

            # Parse the HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the table
            table = soup.find('table', class_='responsive-enabled')
            if table:
                tbody = table.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    if not rows:
                        # If no rows are found, assume end of list
                        print(f"No rows found on page {page}. Ending pagination.")
                        break

                    for row in rows:
                        # Extract the href attribute from the first <td><a href="..."> element
                        school_name_td = row.find_all('td')[0]  # Assuming the href is in the first <td>
                        a_tag = school_name_td.find('a')
                        if a_tag and 'href' in a_tag.attrs:
                            href_value = a_tag['href']
                            # Extract the abbreviated and hyphenated name from the href attribute
                            school_slug = href_value.split('/')[-1]  # Take the last part of the URL
                            if school_slug:
                                all_schools.append(school_slug)
            else:
                print(f"No table found on page {page}. Ending pagination.")
                break

            page += 1

        else:
            print(f"Error retrieving page {page}. Status code: {response.status_code}. Ending pagination.")
            break
    
    return all_schools

def get_school_base_info(school_name):
    ncaa_school_base_url = "https://www.ncaa.com/schools/"
    school_base_info = {}

    response = requests.get(ncaa_school_base_url + school_name)
    if response.status_code == 200:
        print(f"Successfully retrieved the webpage {ncaa_school_base_url + school_name}. Status code: {response.status_code}")
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extracting True Name
        trueName_header = soup.find('h1', class_='school-name')
        if trueName_header:
            true_name = trueName_header.text.strip()
            school_base_info['Name'] = true_name

        # Extracting Nickname
        nickname_dd = soup.find('dt', text='Nickname')
        if nickname_dd:
            nickname = nickname_dd.find_next_sibling('dd').text.strip()
            school_base_info['Nickname'] = nickname

        # Extracting Division Information
        division_div = soup.find('div', class_='division-location')
        if division_div:
            school_division = division_div.text.strip().split('-')[0].strip()
            school_base_info['Division'] = school_division
        
        # Extracting Conference Information
        conference_dd = soup.find('dt', text='Conference')
        if conference_dd:
            school_conference = conference_dd.find_next_sibling('dd').text.strip()
            school_base_info['Conference'] = school_conference

    else:
        print(f"{ncaa_school_base_url + school_name} ... Failed to retrieve the webpage. Status code: {response.status_code}")

    return school_base_info

def get_team_roster(school_name):
    pass