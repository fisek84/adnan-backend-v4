import asyncio
from services.write_gateway.write_gateway import WriteGateway

wg = WriteGateway()


async def main():
    result = await wg.write(
        {
            "command": "demo_write",
            "actor_id": "user-123",
            "resource": "demo-resource",
            "payload": {"foo": "bar"},
            # opcionalno:
            # "task_id": "DEMO",
            # "execution_id": "exec_123",
        }
    )
    print(result)


asyncio.run(main())
