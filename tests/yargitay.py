import asyncio
import httpx


async def test_search():
    url = "http://127.0.0.1:8005/api/yargitay/search"  # Endpoint URL'niz

    payload = {
        "arananKelime": '+"mülkiyet hakkı" +"iptal"',
        "birimYrgKurulDaire": "1. Hukuk Dairesi",
        "baslangicTarihi": "01.01.2020",
        "bitisTarihi": "31.12.2024",
        "pageSize": 5,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        print(response.json())


if __name__ == "__main__":
    asyncio.run(test_search())