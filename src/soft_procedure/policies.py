"""只返回候选工件，不推进时钟、不修改队列。"""


def choose(waiting, machine, now: float, name: str, aging_threshold: float):
    def fifo_key(job):
        return job.queue_entered_at, job.job_id

    if name == "fifo" or machine.last_product is None:
        return min(waiting, key=fifo_key)
    if name == "aging":
        overdue = [job for job in waiting if now - job.queue_entered_at >= aging_threshold]
        if overdue:
            return min(overdue, key=fifo_key)
    return min(waiting, key=lambda job: (job.product != machine.last_product, *fifo_key(job)))
