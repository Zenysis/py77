"""Utils file for the different build operations."""

__author__ = 'pramodg@room77.com (Pramod Gupta)'
__copyright__ = 'Copyright 2012 Room77, Inc.'

from collections import deque
import multiprocessing
import os
import signal
import subprocess
import sys
import shlex
from threading import Thread, Timer

from pylib.base.term_color import TermColor


class KeyboardInterruptError(Exception):
  """Exception to translate keyboard interrupt in child processes."""
  def __init__(self, value="Keyboard Interrupt."):
    self.value = value

  def __str__(self):
    return repr(self.value)


class PicklableCallback():
  """Class to use as a picklable callback(e.g. for pools)."""

  def __call__(self, args):
    """The default call method for the class. We want to explicitly handle
    KeyboardInterrupt as otherwise this may lead to invalid child task.

    Args:
      args: tuple: List of args. We expect args to be as follows:
          arg[0]: The class object.
          arg[1]: Method to be called for the class object.
          arg[2:]: All the arguments to be passed to the method.

    Return:
      Passes on the value from the called method.
    """
    try:
      handler = getattr(args[0], args[1], None)
      method_args = args[2:]
      res = handler(*method_args)
      sys.stdout.flush()
      return res
    except KeyboardInterrupt:
      raise KeyboardInterruptError()


class ExecUtils:
  """Utility class."""

  @staticmethod
  def ExecuteParallel(args, pool_size=0, callback=PicklableCallback()):
    """Executes a list of methods in parallel. Uses the PicklableCallback
    as default callback to run individual handlers with the given set of args.

    Args:
      callback: callable method: A method that can be pickled and called.
      args: list: List of args to pass to PicklableCallback which in turn calls
          the callback handler.
      pool_size: int: The size of the task pool.
    Return:
      list: Returns a list of results passed on by the callback handler.
    """
    if not args:
      TermColor.Warning('Nothing to execute.')
      return []

    if not pool_size:
      pool_size = max(multiprocessing.cpu_count(), 1)

    in_queue = multiprocessing.Queue()
    for job in args:
        in_queue.put(job)
    out_queue = multiprocessing.Queue()
    def worker(in_queue, out_queue):
      while (job := in_queue.get()):
        out_queue.put(callback(job))

    for _ in range(pool_size):
      Thread(target=worker, args=(in_queue, out_queue)).start()

    try:
      while True:
        res = out_queue.get()
        new_work = yield res
        if new_work is None:
          break
        for job in new_work:
          in_queue.put(job)
    except (KeyboardInterrupt, Exception) as e:
      TermColor.Error('%s: %s' % (type(e), e))
      # Pass on the keyboard interrupt.
      if type(e) == KeyboardInterrupt: raise e
    finally:
      for _ in range(pool_size):
        in_queue.put(None)
      sys.stdout.flush()
      yield None

  @staticmethod
  def ExecuteSequentially(args, pool_size=0, callback=PicklableCallback()):
    """Executes a list of methods sequentially. Uses the PicklableCallback
    as default callback to run individual handlers with the given set of args.

    Args:
      callback: callable method: A method that can be pickled and called.
      args: list: List of args to pass to PicklableCallback which in turn calls
          the callback handler.
      pool_size: int: The size of the task pool.
    Return:
      list: Returns a list of results passed on by the callback handler.
    """
    if not args:
      TermColor.Warning('Nothing to execute.')
      return []

    queue = deque(args)
    try:
      while queue:
        job = queue.popleft()
        new_jobs = yield callback(job)
        queue.extend(new_jobs or ())
      yield  # wait for the final sentinel
    except (KeyboardInterrupt, Exception) as e:
      TermColor.Error('%s: %s' % (type(e), e))
      # Pass on the keyboard interrupt.
      if type(e) == KeyboardInterrupt: raise e
    finally:
      sys.stdout.flush()

  @staticmethod
  def RunCmd(cmd, timeout_sec=sys.maxsize, piped_output=True, extra_env=None):
    """Executes a command.
    Args:
      cmd: string: A string specifying the command to execute.
      timeout: float: Timeout for the command in seconds.
      piped_output: bool: Set to true if the output is to be dumped directly
          to termimal.
      extra_env: dict{string, string}: The extra environment variables to pass to the cmd.
    """
    TermColor.VInfo(2, 'Executing: %s' % cmd)

    try:
      if extra_env:
        cmd_env = os.environ.copy()
        cmd_env.update(extra_env)
      else:
        cmd_env = os.environ

      timer = None
      proc = None

      if piped_output:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=cmd_env)
      else:
        proc = subprocess.Popen(cmd, shell=True, env=cmd_env)

      # Start timeout.
      timer = Timer(timeout_sec, ExecUtils.__ProcessTimedOut,
                    [proc, cmd, timeout_sec])
      timer.start()
      (merged_out, unused) = proc.communicate()
      timer.cancel()
      retcode = proc.poll()
      if not merged_out:
        merged_out = ''

      if retcode:
        TermColor.Error('%s failed.\nErrorcode: %d' % (cmd, retcode))
        TermColor.Info('%s Output: \n%s' % (cmd, merged_out))
      else:
        TermColor.VInfo(4, '%s Output: \n%s' % (cmd, merged_out))
      return (retcode, merged_out)
    except (KeyboardInterrupt, OSError) as e:
      TermColor.Error('Command: %s failed. Error: %s' % (cmd, e))
      if timer: timer.cancel()
      if proc:
        ExecUtils.__KillSubchildren(proc.pid)
        proc.communicate()
      # Pass on the keyboard interrupt.
      if type(e) == KeyboardInterrupt: raise e
    return (301, '')

  @staticmethod
  def __ProcessTimedOut(proc, cmd, timeout_sec):
    """Handles timed out process. Kills the process and all its children.
    Args:
      cmd: string: The cmd that launched the proc.
      proc: subprocess.Popen: The proc created for the command.
      timeout_sec: int: The timeout for the process.
    """
    TermColor.Error('Command: %s Timed Out (%dsec)!' % (cmd, timeout_sec))
    ExecUtils.__KillSubchildren(proc.pid)

  @staticmethod
  def __KillSubchildren(root_pid):
    """Kills the process and all its subchildren specified by the pid.
    Args:
      root_pid: int: The pid of the process to be killed.
    """
    # Get all child processes.
    p = subprocess.Popen('ps --no-headers -o pid --ppid %d' % root_pid,
                         shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (stdout, stderr) = p.communicate()
    pids = [int(p) for p in stdout.split()]

    try:
      os.kill(root_pid, signal.SIGKILL)
    except OSError as e:
      TermColor.Warning('Could not kill %d. Error %s' % (root_pid, e))

    # Kill all subchildren recursively.
    for pid in pids:
      ExecUtils.__KillSubchildren(pid)
