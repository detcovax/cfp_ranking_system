def generate_powerIndex(teams):
    return sorted(teams, key=lambda x: x.credits, reverse=True)

def generate_rankings(teams):
    rankings = generate_powerIndex(teams)
    for team in rankings[:25]:
        team.rank = rankings.index(team) + 1
    return rankings