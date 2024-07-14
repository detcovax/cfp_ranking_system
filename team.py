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
        
        self.roster = []
        self.nonActivePlayers = []
        



    def report(self):
        report_text = ""
        report_text += "__________________________________________________________\n"
        
        report_text += (str(self.rank) + ". " if self.rank is not None else "") 
        report_text += self.name + "\n"
        
        if self.powerIndex != None:
            report_text += "   Power Index: " + str(self.powerIndex) + "\n"
        
        if self.cfpRank != None:
            report_text += "   CFP Rank: " + str(self.cfpRank) + "\n"
        
        report_text += "   Record: " + str(self.record[0]) + "-" + str(self.record[1])
        if self.record[2] != 0:
            report_text += "-" + str(self.record[2])
        report_text += "\n"
        
        report_text += "   Point Margin: "
        if self.points[0]-self.points[1] > 0:
            report_text += "+"
        report_text += str(self.points[0]-self.points[1]) + "\n"
        
        report_text += "   Yard Margin: "
        if self.yards[0]-self.yards[1] > 0:
            report_text += "+"
        report_text += str(self.yards[0]-self.yards[1]) + "\n"
        
        if self.conf_champ:
            report_text += "   " + self.conference + " Champion\n"
        
        report_text += "\n" + "   Schedule:" + "\n"
        for game in self.games_played:
            report_text += "      "
            report_text += (str(game.away_team.rank) + ". " if game.away_team.rank is not None else "") + str(game.away_team.name) + " (" + str(game.result[1]) + ")" + "   @   " + (str(game.home_team.rank) + ". " if game.home_team.rank is not None else "") + str(game.home_team.name) + " (" + str(game.result[0]) + ")   Final\n"
        
        report_text += "\n" + " Total Credits: " + str(self.credits) + "\n"
        
        report_text += "__________________________________________________________\n"
        return report_text