def generate_powerIndex(teams):
    powerIndex = sorted(teams, key=lambda x: x.credits, reverse=True)
    for team in teams:
        team.powerIndex = powerIndex.index(team) + 1
    return powerIndex

def generate_rankings(teams):
    rankings = generate_powerIndex(teams)
    for team in teams:
        team.rank = rankings.index(team) + 1
    return rankings