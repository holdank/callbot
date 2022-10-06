"""A module for running methods in a single thread.

Usage:
  class Adder:
    @threaded
    def add(self, a, b):
      return a + b

    @threaded
    def add_plus_ten(self, a, b):
      return self.add(a, b) + 10

  This ensures that when add() is called on its own, it's scheduled on the
  module's thread, but when it's called by add_plus_ten(), it isn't
  re-scheduled, creating a deadlock.

"""


import threading


from concurrent.futures import ThreadPoolExecutor
from functools import wraps


executor = ThreadPoolExecutor(max_workers=1)
# Create global thread-local data. This will be checked by @threaded in order
# to determine whether or not we're already in the executor.
thread_local = threading.local()
def __init_thread_local():
  thread_local.thread_id = threading.get_ident()
executor.submit(__init_thread_local).result()


def threaded(f):
  @wraps(f)
  def wrapper(*args, **kwargs):
    if "thread_id" not in thread_local.__dict__:
      return executor.submit(f, *args, **kwargs).result()
    return f(*args, **kwargs)
  return wrapper
