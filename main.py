from team import *
from game import *

teams = []
games = []

powerIndex = []
rankings = []
cfp_rankings = []
top25 = []
report_list = []

def generate_top25():
    pass

def print_top25_reports():
    for team in top25:
        team.print_report()

def print_other_reports():
    for team in cfp_rankings or report_list:
        if team not in top25:
            team.print_report()

def main():
    Team1 = Team("team1")
    teams.append(Team1)
    generate_top25()
    report_list.append(Team1)
    #print_powerIndex()
    #print_top25()
    #print_cfp_rankings()
    print_top25_reports()
    print_other_reports()


if __name__ == '__main__':
    main()