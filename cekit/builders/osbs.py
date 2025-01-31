import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import time

import yaml

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from cekit import tools
from cekit.config import Config
from cekit.builder import Builder
from cekit.descriptor.resource import _PlainResource
from cekit.errors import CekitError
from cekit.tools import Chdir, copy_recursively

LOGGER = logging.getLogger('cekit')
CONFIG = Config()


class OSBSBuilder(Builder):
    """Class representing OSBS builder."""

    def __init__(self, common_params, params):
        super(OSBSBuilder, self).__init__('osbs', common_params, params)

        self._rhpkg_set_url_repos = []
        self.dist_git = None
        self.dist_git_dir = None
        self.artifacts = []

        if CONFIG.get('common', 'redhat'):
            if self.params.get('stage'):
                self._fedpkg = '/usr/bin/rhpkg-stage'
                self._koji = '/usr/bin/brew-stage'
                self._koji_url = 'https://brewweb.stage.engineering.redhat.com/brew'
            else:
                self._fedpkg = '/usr/bin/rhpkg'
                self._koji = '/usr/bin/brew'
                self._koji_url = 'https://brewweb.engineering.redhat.com/brew'
        else:
            self._fedpkg = '/usr/bin/fedpkg'
            self._koji = '/usr/bin/koji'
            self._koji_url = 'https://koji.fedoraproject.org/koji'

    @staticmethod
    def dependencies():
        deps = {}

        if CONFIG.get('common', 'redhat'):
            if CONFIG.get('common', 'stage'):
                fedpkg = 'rhpkg-stage'
                koji = 'brewkoji-stage'
                koji_executable = '/usr/bin/brew-stage'
            else:
                fedpkg = 'rhpkg'
                koji = 'brewkoji'
                koji_executable = '/usr/bin/brew'
        else:
            fedpkg = 'fedpkg'
            koji = 'koji'
            koji_executable = '/usr/bin/koji'

        deps[fedpkg] = {
            'package': fedpkg,
            'executable': fedpkg
        }

        deps[koji] = {
            'package': koji,
            'executable': koji_executable
        }

        return deps

    def before_build(self):
        """Prepares dist-git repository for OSBS build."""

        super(OSBSBuilder, self).before_build()

        self.prepare_dist_git()
        self.copy_to_dist_git()

    def prepare_dist_git(self):
        repository_key = self.generator.image.get('osbs', {}).get('repository', {})

        repository = repository_key.get('name')
        branch = repository_key.get('branch')

        if not (repository and branch):
            raise CekitError(
                "OSBS builder needs repository and branch provided, see http://docs.cekit.io/en/latest/descriptor/image.html#osbs for more information")

        if self.params.stage:
            osbs_dir = 'osbs-stage'
        else:
            osbs_dir = 'osbs'

        self.dist_git_dir = os.path.join(os.path.expanduser(CONFIG.get('common', 'work_dir')),
                                         osbs_dir,
                                         repository)
        if not os.path.exists(os.path.dirname(self.dist_git_dir)):
            os.makedirs(os.path.dirname(self.dist_git_dir))

        self.dist_git = DistGit(self.dist_git_dir,
                                self.target,
                                repository,
                                branch)

        self.dist_git.prepare(self.params.stage, self.params.user)
        self.dist_git.clean()

        # First get all artifacts that are not plain artifacts
        self.artifacts = [a.target_file_name()
                          for a in self.generator.image.all_artifacts if not isinstance(a, _PlainResource)]
        # When plain artifact was handled using lookaside cache, we need to add it too
        # TODO Rewrite this!
        self.artifacts += [a.target_file_name()
                           for a in self.generator.image.all_artifacts if isinstance(a, _PlainResource) and a.get('lookaside')]

        if 'packages' in self.generator.image and 'set_url' in self.generator.image['packages']:
            self._rhpkg_set_url_repos = [x['url']['repository']
                                         for x in self.generator.image['packages']['set_url']]

    def copy_to_dist_git(self):
        LOGGER.debug("Copying files to dist-git '{}' directory".format(self.dist_git_dir))
        copy_recursively(os.path.join(self.target, 'image'), self.dist_git_dir)

    def _merge_container_yaml(self, src, dest):
        # FIXME - this is temporary needs to be refactored to proper merging
        with open(src, 'r') as _file:
            generated = yaml.safe_load(_file)

        target = {}
        if os.path.exists(dest):
            with open(dest, 'r') as _file:
                target = yaml.safe_load(_file)

        target.update(generated)
        # FIXME - run x86-build if there is *repo commited to dist-git
        if glob.glob(os.path.join(self.dist_git_dir,
                                  'repos',
                                  '*.repo')):

            if 'platforms' in target:
                target['platforms']['only'] = ['x86_64']
            else:
                target['platforms'] = {'only': ['x86_64']}

        with open(dest, 'w') as _file:
            yaml.dump(target, _file, default_flow_style=False)

    def _wait_for_osbs_task(self, task_id, current_time=0, timeout=7200):
        """ Default timeout is 2hrs """

        LOGGER.debug("Checking if task {} is finished...".format(task_id))

        # Time between subsequent querying the API
        sleep_time = 20

        if current_time > timeout:
            raise CekitError(
                "Timed out while waiting for the task {} to finish, please check the task logs!".format(task_id))

        # Definition of task states
        states = {'free': 0, 'open': 1, 'closed': 2, 'cancelled': 3, 'assigned': 4, 'failed': 5}

        # Get information about the task
        try:
            json_info = subprocess.check_output(
                [self._koji, "call", "--json-output", "getTaskInfo", task_id]).strip().decode("utf8")
        except subprocess.CalledProcessError as ex:
            raise CekitError("Could not check the task {} result".format(task_id), ex)

        # Parse the returned JSON
        info = json.loads(json_info)

        # Task is closed which means that it was successfully finished
        if info['state'] == states['closed']:
            return True

        # Task is in progress
        if info['state'] == states['free'] or info['state'] == states['open'] or info['state'] == states['assigned']:
            # It's not necessary to query the API so often
            time.sleep(sleep_time)
            return self._wait_for_osbs_task(task_id, current_time+sleep_time, timeout)

        # In all other cases (failed, cancelled) task did not finish successfully
        raise CekitError(
            "Task {} did not finish successfully, please check the task logs!".format(task_id))

    def update_lookaside_cache(self):
        LOGGER.info("Updating lookaside cache...")
        if not self.artifacts:
            return
        cmd = [self._fedpkg]
        if self.params.user:
            cmd += ['--user', self.params.user]
        cmd += ["new-sources"] + self.artifacts

        LOGGER.debug("Executing '%s'" % cmd)
        with Chdir(self.dist_git_dir):
            try:
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as ex:
                LOGGER.error("Cannot run '%s', output: '%s'" % (cmd, ex.output))
                raise CekitError("Cannot update sources.")

        LOGGER.info("Update finished.")

    def run(self):
        cmd = [self._koji]

        if self.params.user:
            cmd += ['--user', self.params.user]

        cmd += ['call', '--python', 'buildContainer', '--kwargs']

        with Chdir(self.dist_git_dir):
            self.dist_git.add(self.artifacts)
            self.update_lookaside_cache()

            if self.dist_git.stage_modified():
                self.dist_git.commit(self.params.commit_message)
                self.dist_git.push()
            else:
                LOGGER.info("No changes made to the code, committing skipped")

            # Get the url of the repository
            url = subprocess.check_output(
                ["git", "config", "--get", "remote.origin.url"]).strip().decode("utf8")
            # Get the latest commit hash
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("utf8")
            # Parse the dist-git repository url
            url = urlparse(url)
            # Construct the url again, with a hash and removed username and password, if any
            src = "git://{}{}#{}".format(url.hostname, url.path, commit)

            target = "{}-containers-candidate".format(self.dist_git.branch)

            if self.params.koji_target:
                target = self.params.koji_target

            scratch = True

            if self.params.release:
                scratch = False

            kwargs = "{{'src': '{}', 'target': '{}', 'opts': {{'scratch': {}, 'git_branch': '{}', 'yum_repourls': {}}}}}".format(
                src, target, scratch, self.dist_git.branch, self._rhpkg_set_url_repos)

            cmd.append(kwargs)

            LOGGER.info("About to execute '%s'." % ' '.join(cmd))

            if tools.decision("Do you want to build the image in OSBS?"):
                build_type = "scratch" if scratch else "release"
                LOGGER.info("Executing %s container build in OSBS..." % build_type)

                try:
                    task_id = subprocess.check_output(cmd).strip().decode("utf8")

                except subprocess.CalledProcessError as ex:
                    raise CekitError("Building container image in OSBS failed", ex)

                LOGGER.info("Task {0} was submitted, you can watch the progress here: {1}/taskinfo?taskID={0}".format(
                    task_id, self._koji_url))

                if self.params.nowait:
                    return

                self._wait_for_osbs_task(task_id)

                LOGGER.info("Image was built successfully in OSBS!")


class DistGit(object):
    """Git support for osbs repositories"""
    @staticmethod
    def repo_info(path):

        with Chdir(path):
            if subprocess.check_output(["git", "rev-parse", "--is-inside-work-tree"]).strip().decode("utf8") != "true":

                raise Exception("Directory %s doesn't seem to be a git repository. "
                                "Please make sure you specified correct path." % path)

            name = os.path.basename(subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"]).strip().decode("utf8"))
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip().decode("utf8")
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"]).strip().decode("utf8")

        return name, branch, commit

    def __init__(self, output, source, repo, branch, noninteractive=False):
        self.output = output
        self.source = source
        self.repo = repo
        self.branch = branch
        self.dockerfile = os.path.join(self.output, "Dockerfile")
        self.noninteractive = noninteractive

        self.source_repo_name, self.source_repo_branch, self.source_repo_commit = DistGit.repo_info(
            source)

    def stage_modified(self):
        # Check if there are any files in stage (return code 1). If there are no files
        # (return code 0) it means that this is a rebuild, so skip committing
        if subprocess.call(["git", "diff-index", "--quiet", "--cached", "HEAD"]):
            return True

        return False

    def prepare(self, stage, user=None):
        if os.path.exists(self.output):
            with Chdir(self.output):
                LOGGER.info("Pulling latest changes in repo %s..." % self.repo)
                subprocess.check_call(["git", "fetch"])
                subprocess.check_call(
                    ["git", "checkout", "-f", self.branch], stderr=subprocess.STDOUT)
                subprocess.check_call(
                    ["git", "reset", "--hard", "origin/%s" % self.branch])
            LOGGER.debug("Changes pulled")
        else:
            LOGGER.info("Cloning %s git repository (%s branch)..." %
                        (self.repo, self.branch))

            if stage:
                cmd = ['rhpkg-stage']
            else:
                cmd = ['rhpkg']

            if user:
                cmd += ['--user', user]
            cmd += ["-q", "clone", "-b", self.branch, self.repo, self.output]
            LOGGER.debug("Cloning: '%s'" % ' '.join(cmd))
            subprocess.check_call(cmd)
            LOGGER.debug("Repository %s cloned" % self.repo)

    def clean(self):
        """ Removes old generated scripts, repos and modules directories """
        with Chdir(self.output):
            git_files = subprocess.check_output(
                ["git", "ls-files", "."]).strip().decode("utf8").splitlines()
            for d in ["repos", "modules"]:
                LOGGER.info("Removing old '%s' directory" % d)
                shutil.rmtree(d, ignore_errors=True)

                if d in git_files:
                    subprocess.check_call(["git", "rm", "-rf", d])

    def add(self, artifacts):
        LOGGER.debug("Adding files to git stage...")

        for obj in os.listdir('.'):
            if obj in artifacts:
                LOGGER.debug("Skipping staging '{}' in git because it is an artifact".format(obj))
                continue

            if obj == ".git":
                LOGGER.debug("Skipping '.git' directory")
                continue

            LOGGER.debug("Staging '{}'...".format(obj))

            subprocess.check_call(["git", "add", "--all", obj])

    def commit(self, commit_msg):
        if not commit_msg:
            commit_msg = "Sync"

            if self.source_repo_name:
                commit_msg += " with %s" % self.source_repo_name

            if self.source_repo_commit:
                commit_msg += ", commit %s" % self.source_repo_commit

        # Commit the change
        LOGGER.info("Commiting with message: '%s'" % commit_msg)
        subprocess.check_call(["git", "commit", "-q", "-m", commit_msg])

        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"]).decode("utf8")

        if untracked:
            LOGGER.warning("There are following untracked files: %s. Please review your commit."
                           % ", ".join(untracked.splitlines()))

        diffs = subprocess.check_output(["git", "diff-files", "--name-only"]).decode("utf8")

        if diffs:
            LOGGER.warning("There are uncommited changes in following files: '%s'. "
                           "Please review your commit."
                           % ", ".join(diffs.splitlines()))

        if not self.noninteractive:
            subprocess.call(["git", "status"])
            subprocess.call(["git", "show"])

        if not (self.noninteractive or tools.decision("Are you ok with the changes?")):
            LOGGER.info("Executing bash in the repo directory. "
                        "After fixing the issues, exit the shell and Cekit will continue.")
            subprocess.call(["bash"], env={"PS1": "cekit $ ",
                                           "TERM": os.getenv("TERM", "xterm"),
                                           "HOME": os.getenv("HOME", "")})

    def push(self):
        if self.noninteractive or tools.decision("Do you want to push the commit?"):
            print("")
            LOGGER.info("Pushing change to the upstream repository...")
            cmd = ["git", "push", "-q", "origin", self.branch]
            LOGGER.debug("Running command '%s'" % ' '.join(cmd))
            subprocess.check_call(cmd)
            LOGGER.info("Change pushed.")
        else:
            LOGGER.info("Changes are not pushed, exiting")
            sys.exit(0)
