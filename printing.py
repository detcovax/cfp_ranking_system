def print_top25(top25):
    print("Top 25:")
    for index, team in enumerate(top25):
        print(f"{index+1}. {team.name} ({team.record[0]}-{team.record[1]})")

def print_top25_reports(top25):
    for team in top25:
        team.print_report()

def print_other_reports(report_list, top25):
    for team in report_list:
        if team not in top25:
            team.print_report()