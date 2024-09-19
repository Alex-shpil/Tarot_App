# ai_module.py
import logging
from openai import AsyncOpenAI, OpenAIError, RateLimitError  # Import OpenAIError directly
import backoff
from dotenv import load_dotenv



# Load environment variables (if needed)
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize AsyncOpenAI with the provided API key
aclient = AsyncOpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger(__name__)

@backoff.on_exception(backoff.expo, RateLimitError)
async def completions_with_backoff(**kwargs):
    """Call OpenAI's completions API with backoff handling."""
    try:
        response = await aclient.chat.completions.create(**kwargs)
        return response
    except OpenAIError as e:
        if "rate limit" in str(e).lower():
            raise RateLimitError("Rate limit exceeded")
        else:
            raise e

async def call_openai(user_input: str) -> str:
    """Handles OpenAI API calls with retry logic using backoff."""
    try:
        response = await completions_with_backoff(
            model="gpt-3.5-turbo",  # or "gpt-4" if available
            messages=[{"role": "user", "content": user_input}]
        )
        return response.choices[0].message["content"].strip()

    except OpenAIError as e:
        logging.error(f"OpenAI API error: {e}")
        return "Sorry, I'm having trouble processing your request right now."
