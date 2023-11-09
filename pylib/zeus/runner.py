#!/usr/bin/env python

"""Handles run."""

__author__ = 'pramodg@room77.com (Pramod Gupta)'
__copyright__ = 'Copyright 2012 Room77, Inc.'

from collections import defaultdict
from functools import reduce
import itertools
import json
import operator
import os
import re
import sys
import time

from pylib.base.flags import Flags
from pylib.base.exec_utils import ExecUtils
from pylib.base.term_color import TermColor
from pylib.file.file_utils import FileUtils
from pylib.util.mail.mailer import Mailer

from pylib.zeus.pipeline_cmd_base import PipelineCmdBase
from pylib.zeus.pipeline_config import PipelineConfig
from pylib.zeus.pipeline_utils import PipelineUtils

class Runner(PipelineCmdBase):
  """Class to handle run."""

  # The different exit codes that can be returned after running a task.
  EXITCODE = {
    '_LOWEST':-1,  # Internal use.
    'SUCCESS': 0,
    'ALLOW_FAIL': 1,
    'FAILURE': 2,
    'ABORT_FAIL': 3,
  }

  EXITCODE_DESCRIPTION = {
    0: 'SUCCESS',
    1: 'ALLOW_FAIL',
    2: 'FAILURE',
    3: 'ABORT_FAIL',
  }

  EXITCODE_FILE = {
    0: 'SUCCESS',
    1: 'SUCCESS',
    2: 'FAILURE',
    3: 'ABORT',
  }

  TASK_OPTIONS = {
    # Default option. Task will run regardless of if earlier tasks in the directory
    # were successful or not. Task will not run if any task across the pipeline was
    # marked as `abort_fail`.
    'NORMAL': 0,
    # If this step fails, prevent any subsequent steps across the entire pipeline from
    # running. The pipeline will be aborted. All currently running tasks will finish,
    # but no further tasks will be run. To enable this option, add `.abort_fail` to the
    # task name.
    'ABORT_FAIL': 1,
    # If this step fails, do not mark the out directory as failed. Mark it as successful
    # if all other tasks at this level have succeeded. This will allow publishing of a
    # task directory even if the only steps that failed were marked as `allow_fail`. To
    # enable this option, add `.allow_fail` to the task name.
    'ALLOW_FAIL': 2,
    # If any earlier tasks located in the same directory as this task failed, prevent
    # this task from running. This task will also be marked as failed. To enable this
    # option, add `.require_dir_success` to the task name.
    'REQUIRE_DIR_SUCCESS': 3,
  }

  @classmethod
  def Init(cls, parser):
    super(Runner, cls).Init(parser)
    parser.add_argument('-t', '--timeout', type=float, default=86400,
                        help='Timeout for each task in seconds.')
    parser.add_argument('-s', '--single-threaded', action='store_true',
                        help='Run sequentially with all the output dumped to console')
    parser.add_argument('--pool_size', type=int, default=0,
                        help='The pool size for parallelization.')
    parser.add_argument('--detailed_success_mail', action='store_true', default=False,
                        help='Sends a detailed mail even on success. Useful for debugging.')
    parser.add_argument('--success_mail', type=str, default='',
                        help='The mail to use to send info in case of success.')
    parser.add_argument('--failure_mail', type=str, default='',
                        help='The mail to use to send info in case of success.')
    parser.add_argument('--mail_domain', type=str, default='corp.room77.com',
                        help='The domain to use when sending automated '
                             'pipeline mail.')

  @classmethod
  def WorkHorse(cls, tasks):
    """Runs the workhorse for the command.

    Args:
      tasks: OrderedDict {int, set(string)}: Dict from priority to set of tasks to execute at the
          priority. Note: the dict is ordered by priority.

    Return:
      (list, list): Returns a tuple of list in the form
          (successful_tasks, failed_tasks) specifying tasks that succeeded and
          ones that failed.
    """
    # All our binaries assume they will be run from the source root.
    start = time.time()

    os.chdir(FileUtils.GetSrcRoot())
    cls._CreateDirsForTasks(tasks)

    successful_run = []; failed_run = []
    aborted_task = None

    # NOTE(stephen): Storing task dir status and task out dir status separately since
    # pipelines do not always have an out dir defined.
    dirs_status = {}
    out_dirs_status = {}

    tasks_by_dir = defaultdict(list)
    for set_tasks in tasks.values():
      for task in set_tasks:
        tasks_by_dir[os.path.dirname(task)].append(task)

    key = lambda task: int(os.path.basename(task)[:2])
    for task_dir in tasks_by_dir:
      tasks_by_dir[task_dir].sort(key=key)
    sorted_dirs = sorted(tasks_by_dir, key=key)
    groupped_dirs = itertools.groupby(sorted_dirs, key=key)

    def skip_tasks(tasks_to_run, failed_run, is_aborted):
      """
      Skip tasks that shouldn't run for various reasons, most likely
      because of failure of the dependencies
      """
      result = []
      if is_aborted:
        # whole pipeline is aborted, nothing should be run anymore
        return result

      for task in tasks_to_run:
        task_options = cls.__GetTaskOptions(task)
        # Check if this task requires all previous tasks in the same directory to be
        # successful.
        if task_options[Runner.TASK_OPTIONS['REQUIRE_DIR_SUCCESS']]:
          task_dir = PipelineUtils.TaskDirName(task)
          cur_dir_status = dirs_status.get(task_dir)
          # If any previous tasks have been run in this directory, check to ensure all
          # of them were successful.
          if cur_dir_status and cur_dir_status != Runner.EXITCODE['SUCCESS']:
            failed_run += [task]
            done_tasks.add(task)
            task_display_name = PipelineUtils.TaskDisplayName(task)
            TermColor.Info('Skipped   %s' % task_display_name)
            TermColor.Failure(
              'Skipped Task: %s due to earlier failures in task dir' % task_display_name
            )
            continue
        result.append(task)
      return result

    def get_tasks_to_run():
      """
      Computes what tasks can now run from the current state.
      """
      res = set()
      for tdir, prio in current_prios.items():
        for _, tasks in (
          (task_prio, tasks)
          for task_prio, tasks in itertools.groupby(tasks_by_dir[tdir], key=key)
          if task_prio >= prio  # everything below current prio is done
        ):
          eligible_tasks = set(tasks)
          # from the tasks with correct prio we aren't interested
          # in those already done or currently executing
          can_run = eligible_tasks - done_tasks - in_fly
          if can_run:
            # some tasks can be run, return them and update
            # current priority
            res.update(can_run)
            current_prios[tdir] = prio
            break
          # no tasks can be done but we can't jump to the next prio
          # because there are still tasks running at the current one
          if eligible_tasks.intersection(in_fly):
            res.update(can_run - in_fly)
            break
          # we're done here, lvl^Wprio up!
      return res

    task_gen = None
    _, task_dirs = next(groupped_dirs)
    current_prios = {task_dir: 0 for task_dir in task_dirs}
    in_fly = set()
    done_tasks = set()
    executor = (
      ExecUtils.ExecuteSequentiallyGenerator
      if Flags.ARGS.single_threaded
      else ExecUtils.ExecuteParallelGenerator
    )

    while True:
      while (
          not(
            tasks_to_run := skip_tasks(
              get_tasks_to_run(), failed_run, bool(aborted_task)
            )
          ) and not in_fly):
        try:
          _, task_dirs = next(groupped_dirs)
        except StopIteration:
          task_gen.send(None)
          break
        current_prios = {task_dir: 0 for task_dir in task_dirs}

      if not tasks_to_run and not in_fly:
        break

      in_fly.update(tasks_to_run)

      if tasks_to_run or in_fly:
        # Run all the tasks at the same priority in parallel.
        args = (
            zip(itertools.repeat(cls), itertools.repeat('_RunSingeTask'), tasks_to_run)
            if not aborted_task else ()
        )
        if not task_gen:
          task_gen = executor(args, Flags.ARGS.pool_size)
          res, task = next(task_gen)
        else:
          res, task = task_gen.send(args)
        if res == Runner.EXITCODE['SUCCESS']:
          successful_run += [task]
        elif res == Runner.EXITCODE['FAILURE']:
          failed_run += [task]
        elif res == Runner.EXITCODE['ALLOW_FAIL']:
          failed_run += [task]
        elif res == Runner.EXITCODE['ABORT_FAIL']:
          failed_run += [task]
          aborted_task = task
        else:
          TermColor.Fatal('Invalid return %d code for %s' % (res, task))

        in_fly.remove(task)
        done_tasks.add(task)
        task_dir = os.path.dirname(task)

        # Update the current status of all tasks in the same directory.
        task_dir = PipelineUtils.TaskDirName(task)
        dirs_status[task_dir] = max(
          dirs_status.get(task_dir, Runner.EXITCODE['_LOWEST']), res,
        )

        # Update the out dir status.
        out_dir = PipelineUtils.GetOutDirForTask(task)
        if out_dir:
          out_dirs_status[out_dir] = max(
            out_dirs_status.get(out_dir, Runner.EXITCODE['_LOWEST']), res,
          )

    if aborted_task:
      all_tasks = set(reduce(operator.iadd, tasks.values(), []))
      failed_run += sorted(all_tasks - done_tasks)

    # Write the status files to the dirs.
    cls._WriteOutDirsStatus(out_dirs_status)

    # Send the final status mail.
    time_taken = time.time() - start
    cls._SendFinalStatusMail(successful_run, failed_run, aborted_task, time_taken)

    if aborted_task:
      TermColor.Failure('Aborted by task: %s' % aborted_task)

    return (successful_run, failed_run)

  @classmethod
  def _CreateDirsForTasks(cls, tasks):
    """Creates the relevant dirs for tasks.

    Args:
      tasks: OrderedDict {int, set(string)}: Dict from priority to set of tasks to execute at the
          priority. Note: the dict is ordered by priority.

    """
    for set_tasks in tasks.values():
      for task in set_tasks:
        rel_path = PipelineUtils.GetTaskOutputRelativeDir(task)
        PipelineConfig.Instance().CreateAllSubDirsForPath(rel_path)

  @classmethod
  def _RunSingeTask(cls, task):
    """Runs a Single Task.

    Args:
      task: string: The task to run.

    Return:
      (EXITCODE, string): Returns a tuple of the result status and the task.
    """
    TermColor.Info('Executing %s' % PipelineUtils.TaskDisplayName(task))
    task_vars = cls.__GetEnvVarsForTask(task)
    TermColor.VInfo(4, 'VARS: \n%s' % task_vars)

    task_cmd = task
    pipe_output = not Flags.ARGS.single_threaded # Print to console for debugging single threaded
    log_file = PipelineUtils.GetLogFileForTask(task)
    if not Flags.ARGS.single_threaded and log_file:
       task_cmd += f' > {log_file} 2>&1'
       pipe_output = False

    timeout = cls.__GetTimeOutForTask(task)
    start = time.time()
    (status, out) = ExecUtils.RunCmd(task_cmd, timeout, pipe_output, task_vars)
    time_taken = time.time() - start
    TermColor.Info('Executed  %s. Took %.2fs' % (PipelineUtils.TaskDisplayName(task), time_taken))
    if status:
      TermColor.Failure('Failed Task: %s' % PipelineUtils.TaskDisplayName(task))
      if task_vars.get('PIPELINE_TASK_ABORT_FAIL', None):
        status_code = Runner.EXITCODE['ABORT_FAIL']
      elif task_vars.get('PIPELINE_TASK_ALLOW_FAIL', None):
        status_code = Runner.EXITCODE['ALLOW_FAIL']
      else:
        status_code = Runner.EXITCODE['FAILURE']
    else:
      status_code = Runner.EXITCODE['SUCCESS']

    cls._SendMailForTask(task, status_code, time_taken, log_file, out)

    # Everything done. Mark the task as successful.
    return (status_code, task)

  @classmethod
  def __GetEnvVarsForTask(cls, task):
    """Returns the env vars for the task.

    Args:
      task: string: The task for which the envvar should be prepared.

    Returns:
      dict {string, string}: The dictionary of IDS to values.
    """
    rel_path = PipelineUtils.GetTaskOutputRelativeDir(task)
    vars = {}
    for k, v in PipelineConfig.Instance().GetAllSubDirsForPath(rel_path).items():
      vars[k] = v
      prev_dir = FileUtils.GetPreviousDatedDir(v)
      if not prev_dir: prev_dir = v
      vars[k + '_PREV'] = prev_dir
    vars.update(PipelineConfig.Instance().GetAllENVVars())

    # Check if the task is critical or not.
    task_options = cls.__GetTaskOptions(task)
    if task_options[Runner.TASK_OPTIONS['ABORT_FAIL']]:
      vars['PIPELINE_TASK_ABORT_FAIL'] = '1'
    if task_options[Runner.TASK_OPTIONS['ALLOW_FAIL']]:
      vars['PIPELINE_TASK_ALLOW_FAIL'] = '1'
    return vars

  @classmethod
  def __GetTimeOutForTask(cls, task):
    """Returns the timeout for the task.

    Args:
      task: string: The task for which the timeout should be prepared.

    Returns:
      int: The timeout in seconds.
    """
    timeout = FileUtils.FileContents(task + '.timeout')
    if not timeout:
      timeout = FileUtils.FileContents(os.path.join(PipelineUtils.TaskDirName(task), 'timeout'))

    if not timeout: return Flags.ARGS.timeout

    timeout = re.sub('\s*', '', timeout)
    timeout_parts = re.split('(\d+)', timeout)
    if len(timeout_parts) < 3:
      TermColor.Warning('Ignoring invalid timeout [%s] for task: %s' % (timeout, task))
      return Flags.ARGS.timeout

    timeout = float(timeout_parts[1])
    annotation = timeout_parts[2]
    if not annotation: return timeout
    elif annotation == 'd': timeout *= 86400
    elif annotation == 'h': timeout *= 3600
    elif annotation == 'm': timeout *= 60
    elif annotation == 'ms': timeout *= 0.001
    elif annotation == 'us': timeout *= 0.000001
    return timeout

  @classmethod
  def __GetTaskOptions(cls, task):
    rel_task = PipelineUtils.TaskRelativeName(task)
    options = {
      v: False
      for v in Runner.TASK_OPTIONS.values()
    }

    if '.abort_fail' in rel_task:
      options[Runner.TASK_OPTIONS['ABORT_FAIL']] = True
    if '.allow_fail' in rel_task:
      options[Runner.TASK_OPTIONS['ALLOW_FAIL']] = True
    if '.require_dir_success' in rel_task:
      options[Runner.TASK_OPTIONS['REQUIRE_DIR_SUCCESS']] = True

    if not options:
      options[Runner.TASK_OPTIONS['NORMAL']] = True
    return options

  @classmethod
  def _SendMailForTask(cls, task, status_code, time_taken, log_file, msg):
    """Sends the mail if required for the task.

    Args:
      task: string: The task for which the envvar should be prepared.
      status_code: EXITCODE: The exit code for the task.
      time_taken: float: Time taken in seconds.
      log_file: string: The log file containing the output of the task.
      msg: string: The output message piped directly. Note only one of msg or log_file will be
          present at any time.

    Returns:
      dict {string, string}: The dictionary of IDS to values.
    """
    if status_code == Runner.EXITCODE['SUCCESS']:
      if not Flags.ARGS.detailed_success_mail: return
      receiver = Flags.ARGS.success_mail
    else: receiver = Flags.ARGS.failure_mail


    # Check if there is no receiver for the mail.
    if not receiver: return
    mail_domain = Flags.ARGS.mail_domain
    status_description = Runner.EXITCODE_DESCRIPTION[status_code]
    subject = "[%s:%s] %s : %s" % (PipelineConfig.Instance().pipeline_id(),
                                   PipelineConfig.Instance().pipeline_date(),
                                   status_description, PipelineUtils.TaskDisplayName(task))

    body = 'Executed task: %s. \nStatus:%s \nTime: %.2fs.' % (task, status_description, time_taken)
    if msg:
      body += '\n%s' % msg
      Mailer().send_simple_message(
        PipelineUtils.ZeusEmailId(mail_domain), [receiver], subject, body)
    else:
      Mailer().send_message_from_files(
        PipelineUtils.ZeusEmailId(mail_domain), [receiver], subject, [log_file],
        body)

  @classmethod
  def _WriteOutDirsStatus(cls, out_dirs_status):
    """Writes the status for each of the dirs in the dict.

    Args:
      out_dirs_status: dict {string, EXITCODE}: Dict of dir -> exit status.
    """
    for k, v in out_dirs_status.items():
      FileUtils.RemoveFiles([os.path.join(k, x) for x in Runner.EXITCODE_FILE.values()])
      status_file = Runner.EXITCODE_FILE.get(v, '')
      if not status_file: continue
      FileUtils.CreateFileWithData(os.path.join(k, status_file))

  @classmethod
  def _SendFinalStatusMail(cls, successful_run, failed_run, aborted_task, time_taken):
    """Sends the final status mail if required.

    Args:
      (list, list): Returns a tuple of list in the form
          (successful_tasks, failed_tasks) specifying tasks that succeeded and
          ones that failed.
      aborted_task: string: True if the pipeline was aborted.
      time_taken: float: Time taken in seconds.

    """
    if not successful_run and not failed_run: return

    if not failed_run:
      receiver = Flags.ARGS.success_mail
      status_description = 'SUCCESS'
    else:
      receiver = Flags.ARGS.failure_mail
      status_description = 'ABORT FAIL' if aborted_task else 'FAIL'

    # Check if there is no receiver for the mail.
    if not receiver: return

    mail_domain = Flags.ARGS.mail_domain
    subject = "[%s:%s] Final Status: %s" % (PipelineConfig.Instance().pipeline_id(),
                                            PipelineConfig.Instance().pipeline_date(),
                                            status_description)
    body = 'Aborted by: %s\n\n' % aborted_task if aborted_task else ''
    body += ('Successful tasks: %d\n%s\n\n'
             'Failed tasks: %d\n%s\n\n'
             'Total Time: %.2fs.\n'
             '\n%s\n\n' %
             (len(successful_run), json.dumps(successful_run, indent=2),
              len(failed_run), json.dumps(failed_run, indent=2),
              time_taken,
              PipelineConfig.Instance().GetConfigString()))
    Mailer().send_simple_message(
      PipelineUtils.ZeusEmailId(mail_domain), [receiver], subject, body)


def main():
  try:
    Runner.Init(Flags.PARSER)
    Flags.InitArgs()
    return Runner.Run()
  except KeyboardInterrupt as e:
    TermColor.Warning('KeyboardInterrupt')
    return 1


if __name__ == '__main__':
  sys.exit(main())
