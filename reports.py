from rank import rankings

with open('reports.txt', 'w', encoding="utf-8") as output_file:
    output_file.write("Team Reports:\n")
    for team in rankings:
        output_file.write(
            "\n"
            f"{team.rank}. {team.name}" + (f"   {team.league} Champion" if team.champ==True else "") + "\n"
            f"   Power Index: {team.power}\n"
            f"   Record: {team.record[0]}-{team.record[1]}-{team.record[2]}\n"
            f"   Margin: {('+' if team.margin > 0 else '')}{team.margin}\n"
            f"   Total Credits: {team.credits}\n"
            f"   Schedule:\n"
        )
        for game, game_info in team.games_played.items():
            result = game_info.get("result")
            home_team = game_info.get("home_team")
            away_team = game_info.get("away_team")
            home_points = game_info.get("home_points")
            away_points = game_info.get("away_points")
            notes = game_info.get("notes")
            credits = game_info.get("win_credits")
            output_file.write(
                f"      " + (f"{notes}: " if notes else "") + f"{home_team}" + f" ({home_points})" + " vs. " + f"{away_team}" + f" ({away_points})" + f" - {result} ({credits} Win Credits)" + "\n"
            )
        for game, game_info in team.remaining_games.items():
            week = game_info.get("week")
            home_team = game_info.get("home_team")
            away_team = game_info.get("away_team")
            notes = game_info.get("notes")
            output_file.write(
                f"      Week {week} - " + (f"{notes}: " if notes else "") + f"{home_team}" + " vs. " + f"{away_team}" + "\n"
            )
        output_file.write(f"    Games Remaining: {len(team.remaining_games)}")
        output_file.write("\n")