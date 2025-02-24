import threading
import time
from functools import wraps

from django_redis import get_redis_connection

from celery import shared_task

# for tasks using a redis lock to prevent overlapping this is the default timeout for the lock
DEFAULT_TASK_LOCK_TIMEOUT = 900
# how often the watchdog thread should check and extend the lock (in seconds)
LOCK_REFRESH_INTERVAL = 60


def extend_lock(redis_client, lock_key, lock_timeout):
    """
    Helper function to extend the TTL of a Redis lock
    """
    while True:
        # Check if the lock still exists
        if not redis_client.get(lock_key):
            break

        # Extend the lock TTL
        redis_client.expire(lock_key, lock_timeout)

        # Wait before next refresh
        time.sleep(LOCK_REFRESH_INTERVAL)


def nonoverlapping_task(*task_args, **task_kwargs):
    """
    Decorator to create a task whose executions are prevented from overlapping by a redis lock.

    Args:
        use_watchdog: If True, creates a watchdog thread to extend the lock TTL while the task is running.
    """
    # Extract watchdog flag from kwargs, defaulting to False
    use_watchdog = task_kwargs.pop("use_watchdog", False)

    def _nonoverlapping_task(task_func):
        @wraps(task_func)
        def wrapper(*exec_args, **exec_kwargs):
            r = get_redis_connection()

            task_name = task_kwargs.get("name", task_func.__name__)

            # lock key can be provided or defaults to celery-task-lock:<task_name>
            lock_key = task_kwargs.pop("lock_key", "celery-task-lock:" + task_name)

            # lock timeout can be provided or defaults to task hard time limit
            lock_timeout = task_kwargs.pop("lock_timeout", None)
            if lock_timeout is None:
                lock_timeout = task_kwargs.get("time_limit", DEFAULT_TASK_LOCK_TIMEOUT)

            if r.get(lock_key):
                print("Skipping task %s to prevent overlapping" % task_name)
            else:
                with r.lock(lock_key, timeout=lock_timeout):
                    if use_watchdog:
                        # Start watchdog thread to extend lock TTL
                        watchdog = threading.Thread(
                            target=extend_lock,
                            args=(r, lock_key, lock_timeout),
                            daemon=True,
                        )
                        watchdog.start()

                        try:
                            # Execute the actual task
                            task_func(*exec_args, **exec_kwargs)
                        finally:
                            # The lock will be released by the context manager
                            # The watchdog thread will stop when it can't find the lock
                            pass
                    else:
                        # Execute without watchdog
                        task_func(*exec_args, **exec_kwargs)

        return shared_task(*task_args, **task_kwargs)(wrapper)

    return _nonoverlapping_task
