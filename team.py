from game import *

class Team:
    def __init__(self, name):
        self.name = name
        self.conference = None
        self.powerIndex = None
        self.cfpRank = None
        self.rank = None
        self.games_played = []
        self.record = [0,0,0]
        self.points = [0,0]
        self.yards = [0,0]
        self.conf_champ = False
        self.credits = 0

    def print_report(self):
        report_text = ""
        report_text += "__________________________________________________________\n"
        report_text += self.name + "\n"
        if self.powerIndex != None:
            report_text += "Power Index: " + str(self.powerIndex) + "\n"
        if self.cfpRank != None:
            report_text += "CFP Rank: " + str(self.cfpRank) + "\n"
        if self.rank != None:
            report_text += "Rank: " + str(self.rank) + "\n"
        report_text += "Record: " + str(self.record[0]) + "-" + str(self.record[1])
        if self.record[2] != 0:
            report_text += "-" + str(self.record[2])
        report_text += "\n"
        report_text += "Point Margin: " + str(self.points[0]-self.points[1]) + "\n"
        report_text += "Yard Margin: " + str(self.yards[0]-self.yards[1]) + "\n"
        if self.conf_champ:
            report_text += self.conference + "Champion\n"
        report_text += "\n" + "Schedule:" + "\n"
        for game in self.games_played:
            report_text += game.home_team + " v " + game.away_team + " " + game.result + "\n"
        report_text += "Credits: " + str(self.credits) + "\n"
        report_text += "__________________________________________________________\n"
        print(report_text)