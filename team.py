# Define Team() class

class Team:
    def __init__(self, name):
        self.name = name
        self.formatted_name = self.format_name(name)
        self.div = None
        self.conf = None
        self.record = [0,0,0]
        self.margin = 0
        self.champ = False
        self.credits = 0
        
    def format_name(self, name):
        return name.lower().replace(r' ', r'_').replace(r'-', r'_').replace(r'.',r'').replace(r"'",r'').replace(r'&',r'').replace(r'(',r'').replace(r')',r'')
    
    def resetTeam(self):
        self.record = [0,0,0]
        self.margin = 0
        self.champ = False
        self.credits = 0