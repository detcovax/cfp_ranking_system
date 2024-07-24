import sys
from team import *
from game import *
from evaluate import *
from generate import *
from reports import *
import fetch

teams = []
games = []

powerIndex = []
rankings = []
cfpRankings = []
apRankings = []
report_list = []

def main():
    global teams, games,powerIndex, rankings, cfpRankings, report_list

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
    game2 = Game(Team2, Team3, (17,27))
    games.append(game2)

    #evaluate games and calculate credits
    evaluate_games(games)
    calculate_credits(teams)

    #generate rankings
    powerIndex = generate_powerIndex(teams)
    rankings = generate_rankings(teams)

    #add teams we have requested reports for to list
    report_list.append(Team3)
    
    #print reports
    print("College Football Rankings Generated")
    print("\n" + "Power Index:")
    print_powerIndex(powerIndex)
    print("\n" + "Top 25 Rankings:")
    print_top25(rankings[:25] if len(rankings) >= 25 else rankings)
    print("\n" + "CFP Rankings:")
    print_cfpRankings(cfpRankings)
    print("\n" + "AP Top 25 Rankings:")
    print_apRankings(apRankings)
    print("\n" + "Team Reports:")
    print_top25_reports(rankings[:25] if len(rankings) >= 25 else rankings)
    print_other_reports(report_list, rankings[:25] if len(rankings) >= 25 else rankings)
    print("\n" + "How to read the output" + "\n" + "Power Index: No. Team Name (W-L) (Points Margin)" + "\n" + "Top 25 Rankings: Rk. Team Name (W-L) (Total Credits)")
    print("Team Report:" + "\n" + "Rk. Team Name" + "\n" + "   Ranking Details" + "\n" + "   Record" + "\n" + "   Margin Details" + "\n" + "   Schedule" + "\n" + "      Away Team (score)   @   Home Team (score)   Result" + "\n" + "Total Creidts")



if __name__ == '__main__':

    OGstdout = sys.stdout
    dataLog_fileName = "data.log"
    outputText_fileName = "output.txt"

    print("Fetch Data...")
    print(".")
    with open(dataLog_fileName, 'w') as output_file:
        sys.stdout = output_file
        print("Data Fetch Log\n")
        fetch.request_html()
        fetch.write2json()
        sys.stdout = OGstdout
    print(f"*data fetch steps logged to {dataLog_fileName}")
    print(".")

    print("Starting Analysis...")
    print(".")
    print(".")
    print("evaluating games...")
    print("calculating credits...")
    print("evaluating teams...")
    print(".")

    with open('output.txt', 'w') as output_file:
        sys.stdout = output_file
        main()
        sys.stdout = OGstdout
    print(f"output results... \n *output saved to {outputText_fileName}")
    print(".")

    print(".")
    print(".")

    print("... Done.")