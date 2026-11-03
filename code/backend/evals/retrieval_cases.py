"""Passages to search, questions about them, and pairs of cards to compare.

Each topic has several passages, so finding the right one takes more than finding the topic. Off
topic questions have `expected: None`, and some stay close to a covered subject, since those are
the ones a cutoff can get wrong. Questions avoid the passage's wording where they can, so they test
meaning and not just shared words.
"""

PASSAGES = {
    "glycolysis": (
        "Glycolysis takes place in the cytoplasm and splits one glucose molecule into two "
        "molecules of pyruvate. It needs no oxygen and yields a net gain of two ATP and two NADH."
    ),
    "krebs": (
        "In the mitochondrial matrix, the citric acid cycle oxidizes acetyl-CoA to carbon "
        "dioxide. Each turn produces three NADH, one FADH2 and one GTP, which feed later stages."
    ),
    "electron_transport": (
        "The electron transport chain sits in the inner mitochondrial membrane. It pumps protons "
        "across the membrane, and ATP synthase uses their return flow to make most of a cell's "
        "ATP, with oxygen accepting the electrons at the end."
    ),
    "light_reactions": (
        "The light-dependent reactions of photosynthesis happen in the thylakoid membranes. "
        "Chlorophyll absorbs sunlight, water is split to release oxygen, and the energy is stored "
        "in ATP and NADPH."
    ),
    "calvin": (
        "The Calvin cycle runs in the stroma of the chloroplast. The enzyme RuBisCO fixes carbon "
        "dioxide, and ATP and NADPH then turn the product into sugar."
    ),
    "french_estates": (
        "Before 1789, French society was divided into three estates. The clergy and nobility paid "
        "little tax, so the burden fell on commoners, who resented having one vote of three."
    ),
    "french_bastille": (
        "On 14 July 1789, a Paris crowd stormed the Bastille, a royal fortress and prison, looking "
        "for gunpowder. Its fall became the lasting symbol of the revolution against the monarchy."
    ),
    "french_terror": (
        "During the Reign of Terror of 1793 and 1794, the Committee of Public Safety under "
        "Robespierre sent thousands of suspected enemies to the guillotine, until he was "
        "overthrown and executed himself."
    ),
    "hash_tables": (
        "A hash table maps keys to array slots with a hash function, giving constant average "
        "lookup time. Collisions are handled by chaining or open addressing, and the table is "
        "resized when its load factor grows too high."
    ),
    "binary_search": (
        "Binary search finds a value in a sorted array by comparing it with the middle element and "
        "discarding half of the remaining range each step, so it takes logarithmic time."
    ),
    "quicksort": (
        "Quicksort picks a pivot, partitions the array around it and sorts each side recursively. "
        "It averages n log n time, but poor pivots can degrade it to quadratic time."
    ),
    "supply_demand": (
        "A market reaches equilibrium where the quantity supplied equals the quantity demanded. "
        "When the price is above that point a surplus pushes it down, and below it a shortage "
        "pushes it up."
    ),
    "inflation": (
        "Inflation is a general rise in prices over time, which reduces what money can buy. "
        "Central banks often respond by raising interest rates to slow borrowing and spending."
    ),
    "comparative_advantage": (
        "A country has a comparative advantage in a good if it gives up less to produce it than "
        "others do. Both sides can gain from trade even when one is better at making everything."
    ),
    "covalent_bonds": (
        "Covalent bonds form when atoms share pairs of electrons, as in water and methane. Atoms "
        "with similar electronegativity share them evenly, and others form polar bonds."
    ),
}

SEARCH_CASES = [
    {
        "name": "sugar_breakdown_without_oxygen",
        "query": "How do cells begin breaking down sugar when no oxygen is available?",
        "expected": "glycolysis",
    },
    {
        "name": "acetyl_coa_fate",
        "query": "What happens to acetyl-CoA inside mitochondria?",
        "expected": "krebs",
    },
    {
        "name": "where_most_atp_comes_from",
        "query": "Which stage of respiration makes the most energy for the cell, and how?",
        "expected": "electron_transport",
    },
    {
        "name": "where_plant_oxygen_comes_from",
        "query": "Where does the oxygen released by plants come from?",
        "expected": "light_reactions",
    },
    {
        "name": "exact_enzyme_name",
        "query": "RuBisCO",
        "expected": "calvin",
    },
    {
        "name": "unfair_french_taxes",
        "query": "Why were ordinary people in pre-revolutionary France angry about taxes?",
        "expected": "french_estates",
    },
    {
        "name": "bastille_motive",
        "query": "Why did the crowd attack the Paris prison in the summer of 1789?",
        "expected": "french_bastille",
    },
    {
        "name": "robespierre_end",
        "query": "What happened to Robespierre?",
        "expected": "french_terror",
    },
    {
        "name": "key_value_collisions",
        "query": "What can a key-value lookup structure do when two keys land in the same place?",
        "expected": "hash_tables",
    },
    {
        "name": "halving_a_sorted_list",
        "query": "What is a fast way to look up a number in an ordered list?",
        "expected": "binary_search",
    },
    {
        "name": "worst_case_sorting",
        "query": "Why can a usually fast sorting algorithm sometimes become very slow?",
        "expected": "quicksort",
    },
    {
        "name": "price_too_high",
        "query": "What happens to a product's price when more is offered than people want to buy?",
        "expected": "supply_demand",
    },
    {
        "name": "central_bank_response",
        "query": "How do central banks try to bring rising prices under control?",
        "expected": "inflation",
    },
    {
        "name": "trade_benefits",
        "query": "Why does trading help two countries if one is more productive at everything?",
        "expected": "comparative_advantage",
    },
    {
        "name": "sharing_electrons",
        "query": "What holds the hydrogen and oxygen atoms in a water molecule together?",
        "expected": "covalent_bonds",
    },
    {"name": "off_recipe", "query": "How long should I knead sourdough bread?", "expected": None},
    {"name": "off_guitar", "query": "How do I tune a guitar by ear?", "expected": None},
    {
        "name": "off_football",
        "query": "How many players does a soccer team have on the field?",
        "expected": None,
    },
    {
        "name": "near_vaccines",
        "query": "How do vaccines train the immune system to recognize a virus?",
        "expected": None,
    },
    {
        "name": "near_rome",
        "query": "What caused the fall of the Western Roman Empire?",
        "expected": None,
    },
    {
        "name": "near_graphs",
        "query": "How does Dijkstra's algorithm find the shortest path in a graph?",
        "expected": None,
    },
    {
        "name": "near_stocks",
        "query": "How do I value a company before buying its shares?",
        "expected": None,
    },
]

# Card text as it's embedded: the front, a space, then the back. `same` says whether both state the
# same fact. A pair that differs must stay below the threshold, because a match lets one learner's
# card confirm another's, and the false twins are what that rule exists to stop.
CARD_PAIRS = [
    {
        "name": "same_capital_of_australia",
        "first": "What is the capital of Australia? Canberra",
        "second": "Which city is Australia's capital? Canberra",
        "same": True,
    },
    {
        "name": "same_powerhouse",
        "first": "Which organelle makes most of a cell's ATP? The mitochondrion",
        "second": "Where in the cell is most ATP produced? In the mitochondria",
        "same": True,
    },
    {
        "name": "same_bastille_date",
        "first": "When was the Bastille stormed? 14 July 1789",
        "second": "On what date did the Bastille fall? July 14, 1789",
        "same": True,
    },
    {
        "name": "same_binary_search",
        "first": "What is the time complexity of binary search? O(log n)",
        "second": "How fast is binary search? Logarithmic time, O(log n)",
        "same": True,
    },
    {
        "name": "same_water_formula",
        "first": "What is the chemical formula of water? H2O",
        "second": "Water's molecular formula is what? H2O",
        "same": True,
    },
    {
        "name": "same_question_wording_exact",
        "first": "What enzyme fixes carbon in the Calvin cycle? RuBisCO",
        "second": "What enzyme fixes carbon in the Calvin cycle? RuBisCO.",
        "same": True,
    },
    {
        "name": "false_capital_of_australia",
        "first": "What is the capital of Australia? Canberra",
        "second": "What is the capital of Australia? Sydney",
        "same": False,
    },
    {
        "name": "false_bastille_year",
        "first": "When was the Bastille stormed? 14 July 1789",
        "second": "When was the Bastille stormed? 14 July 1798",
        "same": False,
    },
    {
        "name": "false_binary_search",
        "first": "What is the time complexity of binary search? O(log n)",
        "second": "What is the time complexity of binary search? O(n)",
        "same": False,
    },
    {
        "name": "false_water_formula",
        "first": "What is the chemical formula of water? H2O",
        "second": "What is the chemical formula of water? H2O2",
        "same": False,
    },
    {
        "name": "false_organelle",
        "first": "Which organelle makes most of a cell's ATP? The mitochondrion",
        "second": "Which organelle makes most of a cell's ATP? The ribosome",
        "same": False,
    },
    {
        "name": "related_cycles",
        "first": "Where does the Calvin cycle occur? The stroma",
        "second": "Where does the citric acid cycle occur? The mitochondrial matrix",
        "same": False,
    },
]
