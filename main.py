import sys
from team import *
from game import *
from evaluate import *
from generate import *
from reports import *

teams = []
games = []

powerIndex = []
rankings = []
report_list = []


def main():
    global teams, games,powerIndex, rankings, report_list

    #create a few fake teams for testing purposes
    Team1 = Team("team1")
    teams.append(Team1)
    Team2 = Team("team2")
    teams.append(Team2)
    Team3 = Team("team3")
    teams.append(Team3)

    #create a fake game for testing purposes
    game1 = Game(Team1, Team2, (10,7))
    games.append(game1)

    #evaluate games and calculate credits
    evaluate_games(games)
    calculate_credits(teams)

    #generate rankings
    powerIndex = generate_powerIndex(teams)
    rankings = generate_rankings(teams)

    #add teams we have requested reports for to list
    report_list.append(Team3)
    
    #print reports
    print_top25(rankings[:25] if len(rankings) >= 25 else rankings)
    print("\n" + "Team Reports:")
    print_top25_reports(rankings[:25] if len(rankings) >= 25 else rankings)
    print_other_reports(report_list, rankings[:25] if len(rankings) >= 25 else rankings)


if __name__ == '__main__':
    print("Starting Analysis...")
    print(".")

    OGstdout = sys.stdout
    with open('output.txt', 'w') as output_file:
        sys.stdout = output_file
        main()
        sys.stdout = OGstdout

    print(".")
    print("... Done. *Output saved to output text file")