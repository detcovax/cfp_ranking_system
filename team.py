from main import rankings, power_index
from cfp_official_ranking import cfp_ranking

# Define Team() class

class Team:
    def __init__(self, name):
        self.name = name
        self.formatted_name = self.format_name(self.name)
        self.div = None
        self.conf = None
        self.record = [0,0,0]
        self.margin = 0
        self.formatted_margin = '{:+}'.format(self.margin)
        self.champ = False
        self.credits = 0
        self.rank = None
        self.power_index_rank = None
        self.cfp_ranking = None
        
    def format_name(self, name):
        return name.lower().replace(r' ', r'_').replace(r'-', r'_').replace(r'.',r'').replace(r"'",r'').replace(r'&',r'').replace(r'(',r'').replace(r')',r'')
    
    def resetTeam(self):
        self.record = [0,0,0]
        self.margin = 0
        self.champ = False
        self.credits = 0
        
    def generate_report(self):
        for rank, ranked_team in enumerate(rankings, start=1):
            if self.name == ranked_team.name:
                self.rank = rank
                break
        
        for rank, ranked_team in enumerate(power_index, start=1):
            if self.name == ranked_team.name:
                self.power_index_rank = rank
                break
            
        for rank, ranked_team in enumerate(cfp_ranking, start=1):
            if self.name == ranked_team.name:
                self.cfp_ranking = rank
                break
            
        report = '\n' + 'REPORT' + '\n' + f'___________________________________________________' + '\n'
        report += f'Team: {self.name}'
        if self.champ:
            report += '(Conferemce Champion)'
        if self.rank is not None:
            report += '\n' + f'Rank: {self.rank}'
        if self.power_index_rank is not None:
            report += '\n' + f'Power Index: {self.power_index_rank}'
        if self.cfp_ranking is not None:
            report += '\n' + f'CFP: {self.cfp_ranking}'
        report += '\n'
        report += f'Overall Record: {self.record[0]}-{self.record[1]}'
        if self.record[2] > 0:
            report += f'-{self.record[2]}\n'
        else:
            report += '\n'
        report += f'Margin {self.formatted_margin}\n'
        report += f'Credits: {self.credits}\n'
        
        report += '\n' + 'Schedule: \n'
        games_remaining = 12 #counter for games remaining in regular season
        # Maybe I try giving each team a list of games as an attribute and then just run through the list of games in the attribute