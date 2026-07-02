import requests
from strands import tool


DRUG_ALIASES = {
    "paracetamol": "acetaminophen",
    "zinc sulphate": "zinc sulfate",
    "co-trimoxazole": "sulfamethoxazole trimethoprim"
}


def normalize_drug_name(drug_name: str) -> str:

    return DRUG_ALIASES.get(
        drug_name.strip().lower(),
        drug_name.strip().lower()
    )


def find_best_match(
    normalized_name: str,
    matches: list
):
    """
    Select the best DailyMed result.
    """

    if not matches:
        return None

    exact_matches = []

    for item in matches:

        title = (
            item.get("title", "")
            .lower()
        )

        if normalized_name in title:

            exact_matches.append(
                item
            )

    if exact_matches:
        return exact_matches[0]

    return matches[0]

@tool
def drug_lookup(drug_name: str):

    normalized_name = (
        normalize_drug_name(
            drug_name
        )
    )

    print(
        f"\n[DRUG LOOKUP]"
        f"\nOriginal   : {drug_name}"
        f"\nNormalized : {normalized_name}"
    )

    try:

        url = (
            "https://dailymed.nlm.nih.gov/"
            "dailymed/services/v2/spls.json"
            f"?drug_name={normalized_name}"
        )

        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        matches = data.get(
            "data",
            []
        )

        if not matches:

            result = {
                "drug": drug_name,
                "normalized_name": normalized_name,
                "found": False,
                "message":
                    "Drug not found in DailyMed",
                "source":
                    "DailyMed"
            }

            print("\n[TOOL RESULT]")
            print(result)

            return result

        selected = find_best_match(
            normalized_name,
            matches
        )

        result = {
            "drug":
                drug_name,

            "normalized_name":
                normalized_name,

            "found":
                True,

            "title":
                selected.get(
                    "title"
                ),

            "setid":
                selected.get(
                    "setid"
                ),

            "published_date":
                selected.get(
                    "published_date"
                ),

            "source":
                "DailyMed"
        }

        print("\n[TOOL RESULT]")
        print(result)

        return result

    except Exception as e:

        result = {
            "drug":
                drug_name,

            "found":
                False,

            "error":
                str(e),

            "source":
                "DailyMed"
        }

        print("\n[TOOL ERROR]")
        print(result)

        return result