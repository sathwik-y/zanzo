"""Prompts for classification and per-category extraction."""
from recall.categories import Category

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [c.value for c in Category],
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["category", "confidence"],
}

CLASSIFIER_PROMPT = """You are classifying a saved Instagram post/reel into exactly one category.

Categories:
- EDUCATIONAL: tutorials, explainers, how-tos, study/career advice, skill content
- EVENT: concerts, meetups, conferences, festivals, workshops - anything happening at a time/place
- RECIPE: cooking content with a dish being made or described
- TRAVEL: destinations, itineraries, places to visit, restaurants/cafes as travel recommendations
- TECH_REFERENCE: tools, apps, code, commands, product comparisons, tech tips
- OTHER: anything that fits none of the above (memes, vlogs, fashion, fitness, etc.)

Decide from the caption, the audio transcript, and the thumbnail (if provided).
Confidence is 0.0-1.0. If the content genuinely straddles two categories, pick the
one a person would search for later and lower the confidence.

CAPTION:
{caption}

TRANSCRIPT:
{transcript}
"""

EXTRACTOR_BOILERPLATE = """Extract structured information from this Instagram {kind}.
Rules:
- Extract ONLY what is actually present in the caption or transcript. Do not invent or guess.
- Leave a field null (or an empty list) if the information is not stated.
- Dates: resolve to ISO 8601 if the year is stated or clearly implied; otherwise keep the raw text in the summary and leave the date field null.
- Keep list items short and self-contained.

CAPTION:
{caption}

TRANSCRIPT:
{transcript}
"""

EXTRACTOR_INSTRUCTIONS: dict[Category, str] = {
    Category.EDUCATIONAL: "This is educational content. Capture the topic, the concrete takeaways a learner would want to recall, any tools/resources mentioned (with handles or URLs when stated), and a 2-3 sentence summary.",
    Category.EVENT: "This is an event announcement or promotion. Capture title, type, start/end datetimes, venue, city, country, RSVP/ticket links, and price info exactly as stated.",
    Category.RECIPE: "This is a recipe. Capture the dish name, cuisine, servings, prep/cook times, every ingredient with quantity when stated, ordered steps, tips, and dietary tags that apply.",
    Category.TRAVEL: "This is travel content. Capture the destination, every specific place mentioned (restaurants, hotels, attractions) with what was said about it, practical tips, and budget info.",
    Category.TECH_REFERENCE: "This is tech/product reference content. Capture the subject, tools/products mentioned (with URLs when stated), any code or commands verbatim, key insights, and comparisons with verdicts.",
    Category.OTHER: "Summarize this content in 1-2 sentences, capture any notable text verbatim, and produce 3-8 short descriptive tags.",
}


def build_classifier_prompt(caption: str | None, transcript: str | None) -> str:
    return CLASSIFIER_PROMPT.format(
        caption=(caption or "(no caption)")[:4000],
        transcript=(transcript or "(no transcript)")[:8000],
    )


def build_extractor_prompt(category: Category, caption: str | None, transcript: str | None, kind: str = "reel") -> str:
    base = EXTRACTOR_BOILERPLATE.format(
        kind=kind,
        caption=(caption or "(no caption)")[:4000],
        transcript=(transcript or "(no transcript)")[:12000],
    )
    return EXTRACTOR_INSTRUCTIONS[category] + "\n\n" + base
