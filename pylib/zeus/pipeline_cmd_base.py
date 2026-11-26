"""Base class for command handlers."""

__author__ = 'pramodg@room77.com (Pramod Gupta)'
__copyright__ = 'Copyright 2012 Room77, Inc.'

import json
import os
from collections import OrderedDict

from pylib.base.flags import Flags
from pylib.base.term_color import TermColor
from pylib.file.file_utils import FileUtils

from pylib.zeus.pipeline_config import PipelineConfig
from pylib.zeus.pipeline_utils import PipelineUtils

class PipelineCmdBase(object):
  """Base class for various pipeline commands."""

  @classmethod
  def Init(cls, parser):
    """Initialize the cleaner.
    Args:
      parser: ArgumentParser: The argument parser for the command.
    """
    parser.add_argument('--ignore_tasks',
                        type=lambda x : [y for y in x.split(',') if x],
                        default=['deprecated', 'no_exec', 'xxx'],
                        help='Comma separated list of substrings specifying '
                        'rules to ignore. e.g. specify "_xxx" to ignore all '
                        'rules containing "_xxx".')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Debug mode.')
    parser.add_argument('task', type=str, nargs='*', default=['...'],
                        help='Can be any of: \n'
                            'Files: "meta/search/search_server.cc"; '
                            'tasks: "meta/search/search_server"; '
                            'Directories: "meta" "meta/*"; '
                            'Tree: "meta/..." ')

  @classmethod
  def Run(cls):
    """Runs the command handler.

    Return:
      int: Exit status. 0 means no error.
    """
    tasks = cls._ComputeTasks(Flags.ARGS.task, Flags.ARGS.ignore_tasks)
    # TermColor.Info('Tasks: %s' % tasks)
    # TermColor.Info('')
    # for key in tasks.iterkeys():
    #   TermColor.Info('%s: %s' % (key, tasks[key]))

    if not tasks:
      TermColor.Warning('Could not find any tasks.')
      return 101

    (successful_tasks, failed_tasks) = cls.WorkHorse(tasks)
    if successful_tasks:
      TermColor.Info('')
      TermColor.Success('No. of tasks: %d' % len(successful_tasks))
      TermColor.VInfo(1, 'Successful tasks: %s' %
                      json.dumps(PipelineUtils.TasksDisplayNames(successful_tasks), indent=2))

    if failed_tasks:
      TermColor.Info('')
      TermColor.Failure('No. of tasks: %d' % len(failed_tasks))
      TermColor.Failure('tasks: %s' %
                        json.dumps(PipelineUtils.TasksDisplayNames(failed_tasks), indent=2))
      return 102

    return 0

  @classmethod
  def WorkHorse(cls, tasks):
    """Runs the workhorse for the command. All derived classes must implement
    this method.

    Args:
      tasks: OrderedDict {int, set(string)}: Dict from priority to set of tasks to execute at the
          priority. Note: the dict is ordered by priority.

    Return:
      (list, list): Returns a tuple of list in the form
          (successful_tasks, failed_tasks) specifying tasks that succeeded and
          ones that failed.
    """
    TermColor.Fatal('Not supported!')
    return (None, None)

  @classmethod
  def _ComputeTasks(cls, targets, ignore_list=[]):
    """Computes the tasks to be evaluate given the input targets.
    Args:
      targets: list: List of input targets.
      ignore_list: list: List of strings to ignore.

    Return:
      dict{int, set(string)}: Dict from priority to set of tasks to execute at the priority.
    """
    # First create a simple task list of priority string to task.
    # Once all the tasks have been collected, then sort them to create an actual priority order.
    tasks = {}
    ignore_list += ['timeout']
    for target in targets:
      ignore = FileUtils.IgnorePath(target, ignore_list)
      if ignore:
        TermColor.Warning('Ignored target %s as anything with [%s] is ignored.' %
                          (target, ignore))
        continue

      recurse = False
      if os.path.basename(target) == '...' :
        target = os.path.dirname(target)
        if not target:
          target = FileUtils.GetAbsPathForFile(os.getcwd())
          if target.find(PipelineConfig.Instance().pipeline_base_dir()) != 0:
            target = PipelineConfig.Instance().pipeline_base_dir()
        recurse = True

      abs_target = FileUtils.GetAbsPathForFile(target)
      if not abs_target:
        TermColor.Warning('[%s] is not a valid path' % (target))
        continue
      abs_target = cls.__PathUnderRoot(abs_target)

      if os.path.isfile(abs_target):
        cls.__AddFileToTasks(tasks, abs_target)
      elif os.path.isdir(abs_target):
        targets += FileUtils.GetFilesInDir(abs_target, recurse, ignore_list)
      else:
        TermColor.Warning('[%s] is not supported' % (abs_target))
        continue

    return cls.__MergeTasks(tasks)

  @classmethod
  def __PathUnderRoot(cls, path):
    """Rewrites a path that reaches the pipeline root through a symlink to sit under the root.

    Only the part of the path above the root is resolved. Symlinks below the root, including the
    task itself, keep their names, since the name relative to the root sets the task's priority
    and output directories.

    Args:
      path: string: Absolute path of the target.

    Return:
      string: The path under the pipeline root, or the input path if no parent resolves to it.
    """
    root = PipelineConfig.Instance().pipeline_base_dir()
    if path == root or path.startswith(root + os.sep):
      return path

    head, tail = path, []
    while True:
      head, part = os.path.split(head)
      if not part:
        return path
      tail.insert(0, part)
      if os.path.realpath(head) == root:
        return os.path.join(root, *tail)

  @classmethod
  def __AddFileToTasks(cls, tasks, target):
    """Adds a file to the tasks.

    Args:
      tasks: dict{int, set(string)}: Dict from priority to set of tasks to execute at the priority.
      target: string: File to consider.
    """
    priority = PipelineUtils.GetTaskPriority(target)
    if not priority:
      TermColor.Warning('Ignored target %s as it has no priority info.' % target)
    else:
      tasks.update({priority : tasks.get(priority, set()) | set([target])})

  @classmethod
  def __MergeTasks(cls, tasks):
    """Adds a file to the tasks.

    Args:
      tasks: dict{int, set(string)}: Dict from priority to set of tasks to execute at the priority.
    Return:
      OrderedDict: dict{int, set(string)}: Dict from priority to set of tasks to execute at the
          priority. However the dict is ordered by priority.
    """
    # Dict to hold the primary priority for a given priority.
    res = OrderedDict()
    current_priority = ''
    for key in sorted(tasks):
      if (not current_priority or len(current_priority) >= len(key) or
          key.find(current_priority) != 0 or int(key[len(current_priority):]) != 0):
        # Either
        # 1. The current priority is not set.
        # 2. The current priority is not smaller than the key.
        # 3. They do not have the same prefix.
        # 4. The rest of the string is not 0.
        current_priority = key
        res[key] = tasks[key]
        continue

      # The currenty key is really the same priority as the current, lets mark it that way.
      res[current_priority] |= tasks[key]
    return res
