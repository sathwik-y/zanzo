"""Spike: verify the Gemini API key works for generation + embeddings."""
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# 1. Structured generation (what classify/extract will use)
resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents='Classify this caption into one of EDUCATIONAL, EVENT, RECIPE, TRAVEL, TECH_REFERENCE, OTHER. Reply as JSON {"category": ..., "confidence": ...}. Caption: "Best ramen spots in Shibuya, Tokyo - save this for your trip!"',
    config={"response_mime_type": "application/json"},
)
print("GENERATION OK:", resp.text)

# 2. Embeddings
emb = client.models.embed_content(
    model="gemini-embedding-001",
    contents="ramen restaurants in tokyo",
    config={"output_dimensionality": 1536},
)
print("EMBEDDING OK: dims =", len(emb.embeddings[0].values))
