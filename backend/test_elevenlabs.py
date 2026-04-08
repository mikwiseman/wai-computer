import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv("backend/.env.example")

async def test():
    api_key = os.getenv("ELEVENLABS_API_KEY") or "dummy"
    async with httpx.AsyncClient(base_url="https://api.elevenlabs.io", timeout=15.0) as client:
        response = await client.post(
            "/v1/single-use-token/realtime_scribe",
            headers={"xi-api-key": api_key},
        )
        print(response.status_code)
        print(response.text)

asyncio.run(test())