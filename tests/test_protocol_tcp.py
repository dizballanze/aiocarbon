import asyncio

import pytest

from aiocarbon.metric import Metric
from aiocarbon.protocol.tcp import TCPClient


pytestmark = pytest.mark.asyncio


class Server:
    def __init__(self, loop, host, port):
        self.loop = loop
        self.loop.run_until_complete(
            asyncio.start_server(
                self.handler, host, port, loop=loop
            )
        )

        self.host = host
        self.port = port
        self.data = b''
        self.event = asyncio.Event(loop=self.loop)

    async def handler(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter):
        while not reader.at_eof():
            self.data += await reader.read(1)

        self.event.set()

    async def wait_data(self):
        await self.event.wait()
        self.event = asyncio.Event(loop=self.loop)


@pytest.fixture()
def tcp_server(event_loop, random_port):
    server = Server(loop=event_loop, host='127.0.0.1', port=random_port)
    yield server


async def test_tcp_simple(tcp_server: Server, event_loop):
    client = TCPClient(
        tcp_server.host,
        port=tcp_server.port,
        namespace='',
    )

    metric = Metric(name='foo', value=42)
    client.add(metric)

    task = event_loop.create_task(client.run())

    await tcp_server.wait_data()

    name, value, ts = tcp_server.data.decode().strip().split(" ")

    assert name == metric.name
    assert value == str(metric.value)
    assert ts == str(metric.timestamp)

    task.cancel()
    await asyncio.wait([task])


async def test_tcp_many(tcp_server: Server, event_loop):
    client = TCPClient(
        tcp_server.host,
        port=tcp_server.port,
        namespace='',
    )

    task = event_loop.create_task(client.run())

    for i in range(199):
        metric = Metric(name='foo', value=42)
        client.add(metric)

    await tcp_server.wait_data()

    for i in range(199):
        metric = Metric(name='foo', value=42)
        client.add(metric)

    await tcp_server.wait_data()

    lines = list(filter(None, tcp_server.data.split(b"\n")))

    assert len(lines) == 398

    for line in lines:
        name, value, ts = line.decode().strip().split(" ")

        assert name == 'foo'
        assert value == '42'

    task.cancel()
    await asyncio.wait([task])


async def test_tcp_reconnect(event_loop: asyncio.AbstractEventLoop,
                             random_port):

    async def handler(reader, writer):
        await reader.read(10)
        writer.close()
        reader.feed_eof()

    server = await asyncio.start_server(
        handler, '127.0.0.1', random_port, loop=event_loop
    )

    client = TCPClient('127.0.0.1', port=random_port, namespace='')
    count = 199907

    for i in range(count):
        metric = Metric(name='foo', value=i)
        client.add(metric)

    with pytest.raises(ConnectionError):
        await client.send()

    server.close()
    await server.wait_closed()

    event = asyncio.Event(loop=event_loop)

    data = b''
    async def handler(reader, writer):
        nonlocal data
        while not reader.at_eof():
            try:
                data += await reader.read(1024)
            except:
                break

        try:
            data += await reader.read(1024)
        except:
            pass

        event.set()

    server = await asyncio.start_server(
        handler, '127.0.0.1', random_port, loop=event_loop
    )

    await client.send()
    await event.wait()

    server.close()
    await server.wait_closed()

    lines = list(
        enumerate(
            filter(None, map(lambda x: x.decode(), data.split(b"\n")))
        )
    )

    for idx, line in lines:
        name, value, _ = line.split(" ")
        value = int(value)

        assert name == 'foo'
        assert idx == value

    assert len(lines) == count