import sys
import time
import json
import fetch

ncaa_schools = []

def convert_sets_to_lists(obj):
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(i) for i in obj]
    else:
        return obj


if __name__ == '__main__':
    OGstdout = sys.stdout
    dataLog_fileName = "data.log"

    with open(dataLog_fileName, 'w') as output_file:
        sys.stdout = output_file
        print("Data Fetch Log\n")
        sys.stdout = OGstdout

    print("Fetch Data...")
    print(".")

    print("fetching list of all schools...")

    with open(dataLog_fileName, 'a') as output_file:
        sys.stdout = output_file
        ncaa_schools = fetch.get_listOfAllSchools()
        sys.stdout = OGstdout
    print(f"{len(ncaa_schools)} schools found. fetch completed.")
    print(f"*data fetch steps logged to {dataLog_fileName}")
    print(".")

    data = {}
    with open('data.json', 'w') as json_file:
        json.dump(data, json_file, indent=4)

    with open('data.json', 'r') as json_file:
        data = json.load(json_file)

    print("fetching school base info...")
    print("this may take a while...")
    print(".")
    print(".")

    new_data = {}
    with open(dataLog_fileName, 'a') as output_file:
        countOfSchools = len(ncaa_schools)
        for index, school in enumerate(ncaa_schools):
            # Print progress to console
            sys.stdout = OGstdout
            percent_complete = ((index + 1) / countOfSchools) * 100
            print(f"this may take a while... {index + 1}/{countOfSchools}   {percent_complete:.2f}%", end='\r')

            # Log output to file
            sys.stdout = output_file
            school_baseInfo = fetch.get_school_base_info(school)  # Fetch actual base info
            school_data = {school: school_baseInfo}
            new_data.update(school_data)

    # Ensure final log entries are written to the file
    sys.stdout = OGstdout

    data.update(new_data)

    print(".")
    print("base info fetched. steps logged. dumping data.")
    print(".")

    with open('data.json', 'w') as json_file:
        json.dump(convert_sets_to_lists(data), json_file, indent=4)

    print("dump complete.")
    print("... Done.")
