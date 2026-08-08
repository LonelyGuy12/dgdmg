import asyncio
from mock_mcp import MockMCPClient

async def test():
    c = MockMCPClient()
    r = await c.register_dataset({"name": "my_persist_test", "description": "test"})
    print("Register result:", r)

asyncio.run(test())