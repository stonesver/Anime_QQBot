from anime_qqbot.scheduling.worker import Worker


async def run_worker(worker: Worker) -> None:
    await worker.run()
