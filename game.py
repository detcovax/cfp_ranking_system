class Game:
    def __init__(self, home_team, away_team, result: tuple=(0,0)):
        self.home_team = home_team
        self.away_team = away_team
        self.result = result