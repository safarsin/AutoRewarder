"""Gemini LLM Query Generator for Rewards daily tasks using the official google-genai SDK."""

import requests
from google import genai

def generate_search_query(title, description, model, api_key, logger=None):
    """
    Generate a natural, localized search query via Google AI Studio API (Gemini) using the GenAI SDK.
    """
    # Try to resolve public IP geolocation details using requests
    location = "Unknown Location"
    try:
        response = requests.get("http://ip-api.com/json", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                city = data.get("city", "")
                state = data.get("regionName", "")
                country = data.get("country", "")
                timezone = data.get("timezone", "")
                location = f"City: {city}, State/Region: {state}, Country: {country}, Local Timezone: {timezone}"
    except Exception:
        pass

    prompt = (
        "You are an assistant for a Microsoft Rewards auto-completer.\n"
        "A card on the dashboard has the following details:\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        "This card requires the user to perform a search on Bing to earn points.\n"
        f"The user's current location/situation is:\n{location}\n\n"
        "Please generate a single, highly realistic, natural search query that matches what the description asks for.\n"
        "To make it look like a real human search from their location:\n"
        "- If searching for time zone: search for the time in a different time zone relative to their local timezone.\n"
        "- If searching for local products/services: localize the search query to their city or state (e.g. including the city/state name naturally, or using local search intent).\n"
        "- If searching for stocks or finance: make it relevant to companies commonly discussed in their country/region.\n"
        "- Do NOT use punctuation or quotes around the query. Do NOT add any extra text, explanation, or markdown formatting.\n"
        "Generate ONLY the search query text."
    )

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model=model,
        input=prompt
    )
    
    query = interaction.output_text.strip()
    if query.startswith('"') and query.endswith('"'):
        query = query[1:-1].strip()
    if query.startswith("'") and query.endswith("'"):
        query = query[1:-1].strip()
    return query
