from team import *

def print_top25_reports():
    for team in top25:
        team.print_report()

def print_other_reports():
    for team in report_list:
        if team not in top25:
            team.print_report()

teams = []
top25 = []
report_list = []

def main():
    Team1 = Team("team1")
    teams.append(Team1)
    top25.append(Team1)
    report_list.append(Team1)
    #print_powerIndex()
    #print_rankings()
    #print_cfp_rankings()
    print_top25_reports()
    print_other_reports()


if __name__ == '__main__':
    main()