import sys
import time
import json
from team import Team
from game import Game
from evaluate import evaluate_games, calculate_credits
from generate import generate_powerIndex, generate_rankings
from reports import (
    print_powerIndex,
    print_top25,
    print_cfpRankings,
    print_apRankings,
    print_top25_reports,
    print_other_reports,
)
import fetch

ncaa_schools = []
teams = []
games = []

powerIndex = []
rankings = []
cfpRankings = []
apRankings = []
report_list = []

def convert_sets_to_lists(obj):
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(i) for i in obj]
    else:
        return obj

def main():
    global ncaa_schools, teams, games, powerIndex, rankings, cfpRankings, report_list

    # Create a few fake teams for testing purposes
    Team1 = Team("team1")
    teams.append(Team1)
    Team2 = Team("team2")
    teams.append(Team2)
    Team3 = Team("team3")
    teams.append(Team3)

    # Create fake games for testing purposes
    game1 = Game(Team1, Team2, (10, 7))
    games.append(game1)
    game2 = Game(Team2, Team3, (17, 27))
    games.append(game2)

    # Evaluate games and calculate credits
    evaluate_games(games)
    calculate_credits(teams)

    # Generate rankings
    powerIndex = generate_powerIndex(teams)
    rankings = generate_rankings(teams)

    # Add teams we have requested reports for to the list
    report_list.append(Team3)

    # Print reports
    print("College Football Rankings Generated")
    print("\nPower Index:")
    print_powerIndex(powerIndex)
    print("\nTop 25 Rankings:")
    print_top25(rankings[:25] if len(rankings) >= 25 else rankings)
    print("\nCFP Rankings:")
    print_cfpRankings(cfpRankings)
    print("\nAP Top 25 Rankings:")
    print_apRankings(apRankings)
    print("\nTeam Reports:")
    print_top25_reports(rankings[:25] if len(rankings) >= 25 else rankings)
    print_other_reports(report_list, rankings[:25] if len(rankings) >= 25 else rankings)
    print("\nHow to read the output\nPower Index: No. Team Name (W-L) (Points Margin)")
    print("Top 25 Rankings: Rk. Team Name (W-L) (Total Credits)")
    print("Team Report:\nRk. Team Name\n   Ranking Details\n   Record\n   Margin Details\n   Schedule\n      Away Team (score)   @   Home Team (score)   Result\nTotal Credits")

if __name__ == '__main__':
    OGstdout = sys.stdout
    dataLog_fileName = "data.log"
    outputText_fileName = "output.txt"

    with open(dataLog_fileName, 'w') as output_file:
        sys.stdout = output_file
        print("Data Fetch Log\n")
        sys.stdout = OGstdout

    with open(outputText_fileName, 'w') as output_file:
        sys.stdout = output_file
        print("Start of output file")
        sys.stdout = OGstdout

    print("Fetch Data...")
    print(".")

    print("fetching list of all schools...")

    with open(dataLog_fileName, 'a') as output_file:
        sys.stdout = output_file
        ncaa_schools = fetch.get_listOfAllSchools()
        sys.stdout = OGstdout
    print(f"{len(ncaa_schools)} schools found. fetch completed.")
    print(f"*data fetch steps logged to {dataLog_fileName}")
    print(".")

    data = {}
    with open('data.json', 'w') as json_file:
        json.dump(data, json_file, indent=4)

    with open('data.json', 'r') as json_file:
        data = json.load(json_file)

    print("fetching school base info...")
    print("this may take a while...")
    print(".")
    print(".")

    new_data = {}
    with open(dataLog_fileName, 'a') as output_file:
        countOfSchools = len(ncaa_schools)
        for index, school in enumerate(ncaa_schools):
            # Print progress to console
            sys.stdout = OGstdout
            percent_complete = ((index + 1) / countOfSchools) * 100
            print(f"this may take a while... {index + 1}/{countOfSchools}   {percent_complete:.2f}%", end='\r')

            # Log output to file
            sys.stdout = output_file
            school_baseInfo = fetch.get_school_base_info(school)  # Fetch actual base info
            school_data = {school: school_baseInfo}
            new_data.update(school_data)

    # Ensure final log entries are written to the file
    sys.stdout = OGstdout

    data.update(new_data)

    print(".")
    print("base info fetched. steps logged. dumping data.")
    print(".")

    with open('data.json', 'w') as json_file:
        json.dump(convert_sets_to_lists(data), json_file, indent=4)

    print("dump complete.")

    print("Starting Analysis...")
    print(".")
    print(".")
    print("evaluating games...")
    print("calculating credits...")
    print("evaluating teams...")
    print(".")

    with open(outputText_fileName, 'a') as output_file:
        sys.stdout = output_file
        main()
        sys.stdout = OGstdout
    print(f"output results... \n *output saved to {outputText_fileName}")
    print(".")

    print(".")
    print(".")

    print("... Done.")
