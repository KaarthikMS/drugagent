import re


class IntentClassifier:

    DRUG_KEYWORDS = [

        "drug",

        "medicine",

        "tablet",

        "capsule",

        "what is",

        "dose",

        "dosage",

        "indication",

        "manufacturer",

        "brand",

        "generic",

    ]

    TOXICITY_KEYWORDS = [

        "toxicity",

        "poison",

        "poisoning",

        "overdose",

        "overdosed",

        "side effect",

        "black box",

        "contraindication",

        "warning",

        "adverse",

    ]

    INTERACTION_KEYWORDS = [

        "interaction",

        "interact",

        "together",

        "combine",

        "along with",

        "can i take",

        "with",

    ]

    def classify(self, question: str):

        question = question.lower()

        intents = set()

        #
        # Drug Information
        #

        if any(

            keyword in question

            for keyword in self.DRUG_KEYWORDS

        ):

            intents.add("drug")

        #
        # Toxicology
        #

        if any(

            keyword in question

            for keyword in self.TOXICITY_KEYWORDS

        ):

            intents.add("toxicity")

        #
        # Drug Interaction
        #

        if any(

            keyword in question

            for keyword in self.INTERACTION_KEYWORDS

        ):

            intents.add("interaction")

        #
        # Default
        #

        if len(intents) == 0:

            intents.add("drug")

        return list(intents)