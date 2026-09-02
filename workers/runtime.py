import asyncio, logging, signal
from verideploy.config import get_settings
from verideploy.observability.logging import configure_logging
from verideploy.observability.telemetry import configure_telemetry

log=logging.getLogger("verideploy.worker")

class WorkerRuntime:
    def __init__(self) -> None: self.stop_event=asyncio.Event()
    def request_stop(self) -> None: self.stop_event.set()
    async def run(self) -> None:
        log.info("worker_started")
        await self.stop_event.wait()
        log.info("worker_stopped")

async def main() -> None:
    settings=get_settings(); configure_logging(settings.log_level); configure_telemetry(settings, service_name="verideploy-worker-runtime"); runtime=WorkerRuntime()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, runtime.request_stop)
        except NotImplementedError:
            continue
    await runtime.run()

if __name__ == "__main__": asyncio.run(main())
