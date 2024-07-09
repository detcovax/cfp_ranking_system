# Define Game()

class Game:
    def __init__(self, home_team, away_team, score: tuple = (0,0)):
        self.home_team = home_team
        self.away_team = away_team
        if isinstance (score, tuple):
            self.result = score
            if self.result[0] > self.result[1]:
                self.winner = home_team
                self.loser = away_team
            elif self.result[0] < self.result[1]:
                self.winner = away_team
                self.loser = home_team
            else:
                self.winner = None
                self.loser = None