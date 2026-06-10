"""Content categories and their extraction JSON schemas.

The schemas double as Gemini structured-output response schemas and as
validation contracts for what lands in extractions.payload.
"""
from enum import StrEnum

SCHEMA_VERSION = "1"


class Category(StrEnum):
    EDUCATIONAL = "EDUCATIONAL"
    EVENT = "EVENT"
    RECIPE = "RECIPE"
    TRAVEL = "TRAVEL"
    TECH_REFERENCE = "TECH_REFERENCE"
    OTHER = "OTHER"


EXTRACTION_SCHEMAS: dict[Category, dict] = {
    Category.EDUCATIONAL: {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "key_takeaways": {"type": "array", "items": {"type": "string"}},
            "concepts_introduced": {"type": "array", "items": {"type": "string"}},
            "tools_or_resources_mentioned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url_or_handle": {"type": "string", "nullable": True},
                    },
                    "required": ["name"],
                },
            },
            "difficulty": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced"],
                "nullable": True,
            },
            "summary": {"type": "string"},
        },
        "required": ["topic", "key_takeaways", "summary"],
    },
    Category.EVENT: {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "event_type": {
                "type": "string",
                "enum": ["concert", "meetup", "conference", "festival", "workshop", "other"],
            },
            "starts_at": {"type": "string", "nullable": True},
            "ends_at": {"type": "string", "nullable": True},
            "venue_name": {"type": "string", "nullable": True},
            "venue_address": {"type": "string", "nullable": True},
            "city": {"type": "string", "nullable": True},
            "country": {"type": "string", "nullable": True},
            "rsvp_url": {"type": "string", "nullable": True},
            "ticket_url": {"type": "string", "nullable": True},
            "price_info": {"type": "string", "nullable": True},
            "summary": {"type": "string"},
        },
        "required": ["title", "event_type", "summary"],
    },
    Category.RECIPE: {
        "type": "object",
        "properties": {
            "dish_name": {"type": "string"},
            "cuisine": {"type": "string", "nullable": True},
            "servings": {"type": "number", "nullable": True},
            "prep_time_minutes": {"type": "number", "nullable": True},
            "cook_time_minutes": {"type": "number", "nullable": True},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "quantity": {"type": "string", "nullable": True},
                        "notes": {"type": "string", "nullable": True},
                    },
                    "required": ["item"],
                },
            },
            "steps": {"type": "array", "items": {"type": "string"}},
            "tips": {"type": "array", "items": {"type": "string"}},
            "dietary_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["dish_name", "ingredients", "steps"],
    },
    Category.TRAVEL: {
        "type": "object",
        "properties": {
            "destination": {"type": "string"},
            "country": {"type": "string", "nullable": True},
            "city": {"type": "string", "nullable": True},
            "best_time_to_visit": {"type": "string", "nullable": True},
            "places_mentioned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["name", "type"],
                },
            },
            "tips": {"type": "array", "items": {"type": "string"}},
            "budget_info": {"type": "string", "nullable": True},
            "summary": {"type": "string"},
        },
        "required": ["destination", "summary"],
    },
    Category.TECH_REFERENCE: {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "tools_mentioned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string", "nullable": True},
                        "category": {"type": "string"},
                    },
                    "required": ["name", "category"],
                },
            },
            "code_or_command_snippets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string"},
                        "snippet": {"type": "string"},
                        "purpose": {"type": "string"},
                    },
                    "required": ["language", "snippet", "purpose"],
                },
            },
            "key_insights": {"type": "array", "items": {"type": "string"}},
            "comparisons_made": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "between": {"type": "array", "items": {"type": "string"}},
                        "verdict": {"type": "string"},
                    },
                    "required": ["between", "verdict"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["subject", "summary"],
    },
    Category.OTHER: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "notable_text": {"type": "string", "nullable": True},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "tags"],
    },
}
