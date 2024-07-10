from team import *
from game import *
from evaluate import *
from generate import *
from printing import *

teams = []
games = []

powerIndex = []
rankings = []
top25 = []
report_list = []


def main():
    global teams, games,powerIndex, rankings, top25, report_list

    #create a few fake teams for testing purposes
    Team1 = Team("team1")
    teams.append(Team1)
    Team2 = Team("team2")
    teams.append(Team2)
    Team3 = Team("team3")
    teams.append(Team3)

    #create a fake game for testing purposes
    game1 = Game(Team1, Team2, [10,7])
    games.append(game1)

    evaluate_games(games)
    calculate_credits(teams)

    powerIndex = generate_powerIndex(teams)
    rankings = generate_rankings(teams)

    if len(rankings) < 25:
        top25 = rankings[:len(rankings)]
    else:
        top25 = rankings[:25]
    
    report_list.append(Team3)
    
    print_top25(top25)
    print("\n" + "Team Reports:")
    print_top25_reports(top25)
    print_other_reports(report_list, top25)


if __name__ == '__main__':
    main()