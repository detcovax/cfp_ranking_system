def generate_powerIndex(teams):
    powerIndex = sorted(teams, key=lambda x: (x.credits, x.record[0]-x.record[1], x.points[0]-x.points[1]), reverse=True)
    for team in teams:
        team.powerIndex = powerIndex.index(team) + 1
    return powerIndex

def generate_rankings(teams):
    rankings = generate_powerIndex(teams)
    for team in teams:
        team.rank = rankings.index(team) + 1
    return rankings