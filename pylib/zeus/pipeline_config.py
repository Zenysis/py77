"""Config manager for zeus."""

__author__ = 'pramodg@room77.com (Pramod Gupta)'
__copyright__ = 'Copyright 2012 Room77, Inc.'

import json
import os
from datetime import datetime

from pylib.base.flags import Flags
from pylib.base.term_color import TermColor
from pylib.file.file_utils import FileUtils
import pylib.util.singleton as singleton

Flags.PARSER.add_argument('--id',
                          type=str, required=False,
                          help='The id of the pipeline. .e.g "hotel", "suggest", etc.')
Flags.PARSER.add_argument('--root',
                          type=str, required=False,
                          help='The root directory specifying the top level of the pipeline.')
Flags.PARSER.add_argument('--publish_root',
                          type=str, default='',
                          help='The directory specifying where the output data is published to.')
Flags.PARSER.add_argument('--bin_root',
                          type=str, default='',
                          help='The directory specifying where pipeline specific binaries and scripts live.')
Flags.PARSER.add_argument('--utils_root',
                          type=str, default=os.path.join(os.path.dirname(__file__), 'utils'),
                          help='The directory specifying where common pipeline utilities live.')
Flags.PARSER.add_argument('--nolog_output', action='store_true', default=False,
                          help='Do not Logs all the execution output to a file.')
Flags.PARSER.add_argument('--log_to_tmp', action='store_true', default=False,
                          help='Logs all the execution output to tmp dir.')
Flags.PARSER.add_argument('--out_dirs',
                          type=lambda x : [y for y in x.split(',') if x],
                          default=[],
                          help='Comma separated list of output directories the pipeline needs.')
Flags.PARSER.add_argument('--date',
                          type=str, default=datetime.now().strftime('%Y%m%d'),
                          help='The date for the output subfolders.')


class PipelineConfig(singleton.Singleton):
  """Class to manage the config for the file.
  This is a singleton class. Make sure to always access it through  PipelineConfig.Instance().

  Members:
    _id: string: The id for the pipeline.
    _pipeline_base_dir: string: The src root dir for the pipeline.
    _pipeline_bin_dir: string: The directory containing pipeline specific binaries and scripts
    _pipeline_date: string: The date for which the pipeline is being run.
    _pipeline_output_dir: string: The output directory of the pipeline.
    _pipeline_log_dir: string: The output directory of the logs.
    _pipeline_publish_dir: string: The directory where the output is published.
    _pipeline_utils_dir: string: The directory containing common pipeline utilities.
    _subdirs: dict {string, string}: The dictionary of SUBDIR_IDS to the paths of the
        subdirectories.
  """

  def __init__(self):
    """Initialize the singleton instance."""
    self._id = Flags.ARGS.id
    self._pipeline_date = Flags.ARGS.date

    # Set the src root.
    self._pipeline_base_dir = FileUtils.GetAbsPathForFile(Flags.ARGS.root)
    if not os.path.isdir(self._pipeline_base_dir):
      TermColor.Fatal('Invalid Root directory: %s' % Flags.ARGS.root)

    # Set the pipeline specific binary directory, if specified
    self._pipeline_bin_dir = ''
    if Flags.ARGS.bin_root:
      self._pipeline_bin_dir = FileUtils.GetAbsPathForFile(Flags.ARGS.bin_root)

    # Set the pipeline utilities directory
    self._pipeline_utils_dir = FileUtils.GetAbsPathForFile(Flags.ARGS.utils_root)

    # Create all necessary directories.
    self._pipeline_output_dir = ''
    self._pipeline_log_dir = ''
    self._pipeline_publish_dir = Flags.ARGS.publish_root
    self._subdirs = {}
    self.__CreateInitialSubDirs()
    self.PrintConfig()

  def pipeline_id(self):
    """Returns: string: the pipeline id."""
    return self._id

  def pipeline_date(self):
    """Returns: string: the pipeline date."""
    return self._pipeline_date

  def pipeline_base_dir(self):
    """Returns: string: the source root."""
    return self._pipeline_base_dir

  def pipeline_bin_dir(self):
    """Returns: string: the bin root."""
    return self._pipeline_bin_dir

  def pipeline_utils_dir(self):
    """Returns: string: the utils root."""
    return self._pipeline_utils_dir

  def pipeline_output_dir(self):
    """Returns: string: the pipeline output directory."""
    return self._pipeline_output_dir

  def pipeline_log_dir(self):
    """Returns: string: the pipeline output directory."""
    return self._pipeline_log_dir

  def pipeline_publish_dir(self):
    """Returns: string: the pipeline publish directory."""
    return self._pipeline_publish_dir

  def pipeline_subdirs(self):
    """ Returns the pipeline subdirs.
    Returns:
      dict {string, string}: The dictionary of SUBDIR_IDS to the paths of the subdirectories.
    """
    return self._subdirs

  def GetAllSubDirsForPath(self, path, add_date=True):
    """Returns all the subdirs for the given node.

    Args:
      node: string: The node for which the path needs to be returned.

    Returns:
      dict {string, string}: The dictionary of SUBDIR IDS to actual paths.
    """
    res = {}
    for k, v in self.pipeline_subdirs().items():
      dir = os.path.join(v, path)
      if add_date:  dir = os.path.join(dir, self.pipeline_date())
      res[k] = dir
    return res

  def GetAllENVVars(self):
    """Returns all the relevant env vars for the given node.

    Returns:
      dict {string, string}: The dictionary of IDS to values.
    """
    # ADD all other relevant dirs.
    res = {}
    res['PIPELINE_ID'] = self.pipeline_id()
    res['PIPELINE_DATE'] = self.pipeline_date()
    res['PIPELINE_SRC_ROOT'] = FileUtils.GetSrcRoot()
    res['PIPELINE_BASE_DIR'] = self.pipeline_base_dir()
    res['PIPELINE_UTILS_DIR'] = self.pipeline_utils_dir()

    if self.pipeline_bin_dir(): res['PIPELINE_BIN_DIR'] = self.pipeline_bin_dir()
    if self.pipeline_output_dir(): res['PIPELINE_OUT_ROOT'] = self.pipeline_output_dir()
    if self.pipeline_log_dir(): res['PIPELINE_LOG_DIR'] = self.pipeline_log_dir()
    if self.pipeline_publish_dir(): res['PIPELINE_PUBLISH_DIR'] = self.pipeline_publish_dir()
    return res

  def CreateAllSubDirsForPath(self, path):
    """Creates all the subdirs for the given node.

    Args:
      node: string: The node for which the path needs to be created.

    Returns:
      dict {string, string}: The dictionary of SUBDIR IDS to actual paths.
    """
    for k, v in self.GetAllSubDirsForPath(path).items():
      FileUtils.MakeDirs(v)

  def GetConfigString(self):
    """Returns the config string for the pipeline.

    Returns:
      string: The config string for the dict.
    """
    return ('CONFIG:\nEnvVars: \n%s\nSubdirs: \n%s\n' % (
        json.dumps(self.GetAllENVVars(), indent=2), json.dumps(self.pipeline_subdirs(), indent=2)))

  def PrintConfig(self):
    """Prints the config string for the pipeline."""
    TermColor.Info(self.GetConfigString())

  def __CreateInitialSubDirs(self):
    """Creates all necessary directories."""
    # Check if we have to create any output directory
    if not Flags.ARGS.out_dirs and Flags.ARGS.nolog_output: return

    # Create the user friendly link to pipeline dir if it doesn't already exist.
    FileUtils.CreateLink(FileUtils.GetPipelineLinkDir(), FileUtils.GetPipelineDir())

    # Create the output directory.
    if Flags.ARGS.out_dirs or not Flags.ARGS.log_to_tmp:
      self._pipeline_output_dir = os.path.join(FileUtils.GetPipelineDir(), self._id)
      FileUtils.MakeDirs(self._pipeline_output_dir)

    # Create the log dir if required.
    if not Flags.ARGS.nolog_output:
      if Flags.ARGS.log_to_tmp:
        log_root = os.path.join('/tmp', 'pipeline', self.pipeline_id())
      else:
        log_root = self._pipeline_output_dir
      self._pipeline_log_dir = os.path.join(log_root, 'log', self.pipeline_date())
      FileUtils.MakeDirs(self._pipeline_log_dir)

    # Create all the subdirs.
    self._subdirs = {}
    for i in Flags.ARGS.out_dirs:
      subdir = os.path.join(self.pipeline_output_dir(), i)
      FileUtils.MakeDirs(subdir)
      self._subdirs['PIPELINE_' + i.upper() + '_DIR'] = subdir
