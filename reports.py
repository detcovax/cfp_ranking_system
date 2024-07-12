def print_powerIndex(powerIndex):
    for index, team in enumerate(powerIndex):
        print(f" {index+1}. {team.name} ({team.record[0]}-{team.record[1]}) (" + ("+" if team.points[0]-team.points[1] > 0 else "") + f"{team.points[0]-team.points[1]})")

def print_top25(top25):
    for index, team in enumerate(top25):
        print(f" {index+1}. {team.name} ({team.record[0]}-{team.record[1]}) ({team.credits})")

def print_top25_reports(top25):
    for team in top25:
        print(team.report())

def print_other_reports(report_list, top25):
    for team in report_list:
        if team not in top25:
            print(team.report())