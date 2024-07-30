# This module will be used to connect to an online data source, fetch that data, and store in a format that can be used in the evaluation and generating steps.
import json, requests
from bs4 import BeautifulSoup

# urls = []
# ncaa_scores_url_base = "https://www.ncaa.com/scoreboard/football/"; urls.append(ncaa_scores_url_base)
# ncaa_rankings_url_base = "https://www.ncaa.com/rankings/football/"; urls.append(ncaa_rankings_url_base)
# ncaa_standings_url_base = "https://www.ncaa.com/standings/football/"; urls.append(ncaa_standings_url_base)
# ncaa_stats_url_base = "https://www.ncaa.com/stats/football/"; urls.append(ncaa_stats_url_base)



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