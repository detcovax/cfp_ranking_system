class Team:
    def __init__(self, name, league=None, record=None, margin=0, champ=False, credits=0):
        self.name = name
        self.league = league
        self.record = record if record else [0, 0, 0]
        self.margin = margin
        self.champ = champ
        self.credits = credits
        self.games_played = {}
        self.remaining_games = {}
        self.ratings = {}
        self.roster = []
        
    def to_dict(self):
        dict = {
            "Name": self.name,
            "League": self.league,
            "Record": self.record,
            "Margin": self.margin,
            "Conference Champion": self.champ,
            "Rankings Credits": self.credits,
            "Games Played": self.games_played,
            "Remaining Games": self.remaining_games,
            "Ratings": self.ratings,
            "Roster": self.roster
        }
        return dict