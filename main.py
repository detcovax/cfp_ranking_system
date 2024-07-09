class Team():
    def __init__(self, name):
        self.name = name
        self.powerIndex = 0
        self.cfpRank = 0
        self.rank = 0
        self.games_played = []
        self.record = [0,0,0]
        self.points = [0,0]
        self.yards = [0,0]
        self.conference_champ = False

    def print_report(self):
        report_text = ""
        report_text += "__________________________________________________________\n"
        report_text += self.name + "\n"
        report_text += "Power Index: " + str(self.powerIndex) + "\n"
        report_text += "CFP Rank: " + str(self.cfpRank) + "\n"
        report_text += "Rank: " + str(self.rank) + "\n"
        report_text += "Record: " + str(self.record[0]) + "-" + str(self.record[1])
        if self.record[2] != 0:
            report_text += "-" + str(self.record[2])
        report_text += "\n"
        report_text += "Point Margin: " + str(self.points[0]-self.points[1]) + "\n"
        report_text += "Yard Margin: " + str(self.yards[0]-self.yards[1]) + "\n"
        report_text += "__________________________________________________________\n"
        print(report_text)

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