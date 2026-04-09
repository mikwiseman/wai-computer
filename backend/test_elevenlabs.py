import asyncio
import os

import httpx


async def test():
    # Use dummy value locally or get real key
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("Missing API KEY")
        return
    async with httpx.AsyncClient(base_url="https://api.elevenlabs.io", timeout=15.0) as client:
        response = await client.post(
            "/v1/single-use-token/realtime_scribe",
            headers={"xi-api-key": api_key},
        )
        print(response.status_code)
        print(response.text)


asyncio.run(test())
