import requests
from bs4 import BeautifulSoup

def evaluate_team_for_cfp(team):
    # Extract relevant information from the team's data
    name = team_data["Name"]
    league = team_data["League"]    
    record = team_data["Record"]  # [wins, losses, ties]
    margin = team_data["Margin"]
    conf_champ = team_data["Conference Champion"]
    fpi_data = team_data.get("Ratings", {}).get("FPI", {})
    rankings = team_data.get("Rankings Credits", 0)
    games_played = team_data["Games Played"]
    
    if 'fbs' not in league:
        return None
    
    # 1. Win-Loss Record
    record_eval = record[0] - record[1] + record[2]/2
    
    # 2. Strength of Schedule (use FPI strength of schedule data)
    #sos = fpi_data.get("resume_ranks", {}).get("strength_of_schedule", 0)
    
    # 3. Conference Championship

    
    # 4. Game Control (use FPI game control data)
    #game_control = fpi_data.get("resume_ranks", {}).get("game_control", 0)
    
    # 5. Quality Wins (rank wins over strong teams)

    
    # Overall score: weighted average of the above metrics
    evaluation = record_eval * 1
    
    return evaluation



#def create_playoff_rankings(evals, rankings):
def create_playoff_rankings(rankings):
    # Sort teams based on their overall scores in descending order
    #sorted_teams = [evals[team_name] for team_name, _ in rankings]
    sorted_teams = rankings
    top_conference_champions = []
    
    #if a conf does not have a formal champion named yet, just take the standings leader.
    leaders = {}
    standings_url = "https://www.ncaa.com/standings/football/fbs"
    try:
        response = requests.get(standings_url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            conferences = soup.find_all('figure', class_='standings-conference')
            for conference in conferences:
                conference_name = conference.get_text(strip=True)
                if 'independent' not in conference_name.lower():
                    table = conference.find_next('table')
                    rows = table.find_all('tr')
                    for row in rows:
                        team_td = row.find('td', class_="standings-team")
                        if team_td:
                            conference_leader = team_td.get_text(strip=True)
                            leaders[conference_name] = conference_leader
                            break   # Stop after the first valid team is found
            
            print(f"\nLeaders: {leaders}\n")
        else:
            raise Exception(response)
    except Exception as e:
        print(f"Error requesting standings from ncaa.com: {e}")
            
        
    # Identify the highest-ranked conference champions
    print(f"\nSorted Teams:\n")
    for team in sorted_teams[:30]:
        print(str(team['Name']) + "   " + str(team['League']) + "\n")
    while len(top_conference_champions) < 5:
        for team in sorted_teams:
            for conference_name, leader in leaders.items():
                if team["Name"].lower() in leader.lower():
                    top_conference_champions.append(team)
                    break
            if len(top_conference_champions) == 5:
                break
    print(f"\nTop 5 conference champs: {top_conference_champions}\n")
                
    #Add top 4 champions
    playoff_rankings = top_conference_champions[:4]
    
    #add the next 8 teams
    while len(playoff_rankings) < 12:
        for team in sorted_teams:
            if team not in playoff_rankings:
                playoff_rankings.append(team)
            if len(playoff_rankings) == 12:
                break
                
    # check the last champion are included
    if top_conference_champions[4] not in playoff_rankings:
        playoff_rankings[-1] = top_conference_champions[4]
    
    return playoff_rankings




import config
import json

# Load the JSON file
with open(config.data_file, 'r') as json_file:
    teams = json.load(json_file)

evals = {}
for team_name, team_data in teams.items():
    eval = evaluate_team_for_cfp(team_data)  # Pass the team data to the evaluation function
    if eval:  # Only keep evaluations for FBS teams
        evals[team_name] = {}
        evals[team_name]['Name'] = team_data['Name']
        evals[team_name]['eval'] = eval
        evals[team_name]['League'] = team_data['League']
        evals[team_name]['Conference Champion'] = team_data['Conference Champion']

rankings = sorted(evals.items(), key=lambda item: item[1]['eval'], reverse=True)

playoff_rankings = create_playoff_rankings(evals, rankings)

# Print rankings
with open('newest_stuff.txt', 'w', encoding="utf-8") as output_file:
    output_file.write('Playoff Rankings:\n')
    for seed, team in enumerate(playoff_rankings, start=1):
        # champion_indicator = " (Conference Champion)" if team["Is Conference Champion"] else ""
        output_file.write(f"Seed {seed}: {team['Name']} (CFP Eval: {team['eval']})\n")

    output_file.write('\nOverall Rankings:\n')
    for rank, (team, evaluation) in enumerate(rankings, start=1):
        # champion_indicator = " (Conference Champion)" if evaluation["Is Conference Champion"] else ""
        output_file.write(f"{rank}. {team}\n")



