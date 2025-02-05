#!/usr/bin/env python

# Copyright 2017 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Need to figure out why this only fails on travis
# pylint: disable=too-few-public-methods

"""Test for kubernetes_e2e.py"""

import json
import os
import re
import shutil
import string
import tempfile
import urllib
import unittest

import kubernetes_e2e

FAKE_WORKSPACE_STATUS = 'STABLE_BUILD_GIT_COMMIT 599539dc0b99976fda0f326f4ce47e93ec07217c\n' \
'STABLE_BUILD_SCM_STATUS clean\n' \
'STABLE_BUILD_SCM_REVISION v1.7.0-alpha.0.1320+599539dc0b9997\n' \
'STABLE_BUILD_MAJOR_VERSION 1\n' \
'STABLE_BUILD_MINOR_VERSION 7+\n' \
'STABLE_gitCommit 599539dc0b99976fda0f326f4ce47e93ec07217c\n' \
'STABLE_gitTreeState clean\n' \
'STABLE_gitVersion v1.7.0-alpha.0.1320+599539dc0b9997\n' \
'STABLE_gitMajor 1\n' \
'STABLE_gitMinor 7+\n'

FAKE_WORKSPACE_STATUS_V1_6 = 'STABLE_BUILD_GIT_COMMIT 84febd4537dd190518657405b7bdb921dfbe0387\n' \
'STABLE_BUILD_SCM_STATUS clean\n' \
'STABLE_BUILD_SCM_REVISION v1.6.4-beta.0.18+84febd4537dd19\n' \
'STABLE_BUILD_MAJOR_VERSION 1\n' \
'STABLE_BUILD_MINOR_VERSION 6+\n' \
'STABLE_gitCommit 84febd4537dd190518657405b7bdb921dfbe0387\n' \
'STABLE_gitTreeState clean\n' \
'STABLE_gitVersion v1.6.4-beta.0.18+84febd4537dd19\n' \
'STABLE_gitMajor 1\n' \
'STABLE_gitMinor 6+\n'

def fake_pass(*_unused, **_unused2):
    """Do nothing."""
    pass

def fake_bomb(*a, **kw):
    """Always raise."""
    raise AssertionError('Should not happen', a, kw)


class Stub(object):
    """Replace thing.param with replacement until exiting with."""
    def __init__(self, thing, param, replacement):
        self.thing = thing
        self.param = param
        self.replacement = replacement
        self.old = getattr(thing, param)
        setattr(thing, param, self.replacement)

    def __enter__(self, *a, **kw):
        return self.replacement

    def __exit__(self, *a, **kw):
        setattr(self.thing, self.param, self.old)


class ClusterNameTest(unittest.TestCase):
    def test_name_filled(self):
        """Return the cluster name if set."""
        name = 'foo'
        build = '1984'
        actual = kubernetes_e2e.cluster_name(name, build)
        self.assertTrue(actual)
        self.assertIn(name, actual)
        self.assertNotIn(build, actual)

    def test_name_empty_short_build(self):
        """Return the build number if name is empty."""
        name = ''
        build = '1984'
        actual = kubernetes_e2e.cluster_name(name, build)
        self.assertTrue(actual)
        self.assertIn(build, actual)

    def test_name_empty_long_build(self):
        """Return a short hash of a long build number if name is empty."""
        name = ''
        build = '0' * 63
        actual = kubernetes_e2e.cluster_name(name, build)
        self.assertTrue(actual)
        self.assertNotIn(build, actual)
        if len(actual) > 32:  # Some firewall names consume half the quota
            self.fail('Name should be short: %s' % actual)


class SetupExtractTest(unittest.TestCase):
    def check(self, extract, envs, args):
        actual_envs = []
        actual_args = []
        class FakeMode(object):
            @staticmethod
            def add_environment(env):
                actual_envs.append(env)
        kubernetes_e2e.setup_extract(extract, FakeMode, actual_args)
        self.assertEquals(envs, actual_envs)
        self.assertEquals(args, actual_args)

    def test_no_extract(self):
        """Do nothing when --extract=."""
        self.check(None, envs=[], args=[])

    def test_extract_local(self):
        """Set JENKINS_USE_LOCAL_BINARIES=y when --extract=local."""
        self.check('local', envs=['RAW_EXTRACT=y'], args=['--extract=local'])

    def test_extract_none(self):
        """Set RAW_EXTRACT=y when --extract=none but send nothing to kubetest."""
        self.check('none', envs=['RAW_EXTRACT=y'], args=[])

    def test_extract_other(self):
        """Set RAW_EXTRACT=y and send --extract to kubetest normally."""
        self.check('other', envs=['RAW_EXTRACT=y'], args=['--extract=other'])


class ScenarioTest(unittest.TestCase):
    """Test for e2e scenario."""
    callstack = []
    envs = {}

    def setUp(self):
        self.parser = kubernetes_e2e.create_parser()
        self.boiler = [
            Stub(kubernetes_e2e, 'check', self.fake_check),
            Stub(shutil, 'copy', fake_pass),
        ]

    def tearDown(self):
        for stub in self.boiler:
            with stub:  # Leaving with restores things
                pass
        self.callstack[:] = []
        self.envs.clear()

    def fake_check(self, *cmd):
        """Log the command."""
        self.callstack.append(string.join(cmd))

    def fake_check_env(self, env, *cmd):
        """Log the command with a specific env."""
        self.envs.update(env)
        self.callstack.append(string.join(cmd))

    def fake_output_work_status(self, *cmd):
        """fake a workstatus blob."""
        self.callstack.append(string.join(cmd))
        return FAKE_WORKSPACE_STATUS

    def fake_output_work_status_v1_6(self, *cmd):
        """fake a workstatus blob for v1.6."""
        self.callstack.append(string.join(cmd))
        return FAKE_WORKSPACE_STATUS_V1_6


class LocalTest(ScenarioTest):
    """Class for testing e2e scenario in local mode."""
    def test_local(self):
        """Make sure local mode is fine overall."""
        args = self.parser.parse_args(['--mode=local'])
        self.assertEqual(args.mode, 'local')
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            kubernetes_e2e.main(args)

        self.assertNotEqual(self.envs, {})
        for call in self.callstack:
            self.assertFalse(call.startswith('docker'))

    def test_updown(self):
        """Make sure local mode is fine overall."""
        args = self.parser.parse_args(['--mode=local', '--up=false'])
        self.assertEqual(args.mode, 'local')
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            kubernetes_e2e.main(args)

        lastcall = self.callstack[-1]
        self.assertNotIn('--up', lastcall)
        self.assertIn('--down', lastcall)

    def test_kubeadm_ci(self):
        """Make sure kubeadm ci mode is fine overall."""
        args = self.parser.parse_args(['--mode=local', '--kubeadm=ci'])
        self.assertEqual(args.mode, 'local')
        self.assertEqual(args.kubeadm, 'ci')
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            with Stub(kubernetes_e2e, 'check_output', self.fake_output_work_status):
                kubernetes_e2e.main(args)

        self.assertIn('E2E_OPT', self.envs)
        self.assertIn('--kubernetes-anywhere-kubeadm-version gs://kubernetes-release-dev/bazel/'
                      'v1.7.0-alpha.0.1320+599539dc0b9997/bin/linux/amd64/', self.envs['E2E_OPT'])
        called = False
        for call in self.callstack:
            self.assertFalse(call.startswith('docker'))
            if call == 'hack/print-workspace-status.sh':
                called = True
        self.assertTrue(called)

    def test_local_env(self):
        """
            Ensure that host variables (such as GOPATH) are included,
            and added envs/env files overwrite os environment.
        """
        mode = kubernetes_e2e.LocalMode('/orig-workspace')
        mode.add_environment(*('FOO=BAR', 'GOPATH=/go/path',
                               'WORKSPACE=/new/workspace'))
        mode.add_os_environment(*('USER=jenkins', 'FOO=BAZ', 'GOOS=linux'))
        with tempfile.NamedTemporaryFile() as temp:
            temp.write('USER=prow')
            temp.flush()
            mode.add_file(temp.name)
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            mode.start([])
        self.assertIn(('FOO', 'BAR'), self.envs.viewitems())
        self.assertIn(('WORKSPACE', '/new/workspace'), self.envs.viewitems())
        self.assertIn(('GOPATH', '/go/path'), self.envs.viewitems())
        self.assertIn(('USER', 'prow'), self.envs.viewitems())
        self.assertIn(('GOOS', 'linux'), self.envs.viewitems())
        self.assertNotIn(('USER', 'jenkins'), self.envs.viewitems())
        self.assertNotIn(('FOO', 'BAZ'), self.envs.viewitems())

    def test_kubeadm_periodic(self):
        """Make sure kubeadm periodic mode is fine overall."""
        args = self.parser.parse_args(['--mode=local', '--kubeadm=periodic'])
        self.assertEqual(args.mode, 'local')
        self.assertEqual(args.kubeadm, 'periodic')
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            with Stub(kubernetes_e2e, 'check_output', self.fake_output_work_status):
                kubernetes_e2e.main(args)

        self.assertIn('E2E_OPT', self.envs)
        self.assertIn('--kubernetes-anywhere-kubeadm-version gs://kubernetes-release-dev/bazel/'
                      'v1.7.0-alpha.0.1320+599539dc0b9997/bin/linux/amd64/', self.envs['E2E_OPT'])
        called = False
        for call in self.callstack:
            self.assertFalse(call.startswith('docker'))
            if call == 'hack/print-workspace-status.sh':
                called = True
        self.assertTrue(called)

    def test_kubeadm_periodic_v1_6(self):
        """Make sure kubeadm periodic mode has correct version on v1.6"""
        args = self.parser.parse_args(['--mode=local', '--kubeadm=periodic'])
        self.assertEqual(args.mode, 'local')
        self.assertEqual(args.kubeadm, 'periodic')
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            with Stub(kubernetes_e2e, 'check_output', self.fake_output_work_status_v1_6):
                kubernetes_e2e.main(args)

        self.assertIn('E2E_OPT', self.envs)
        self.assertIn('--kubernetes-anywhere-kubeadm-version gs://kubernetes-release-dev/bazel/'
                      'v1.6.4-beta.0.18+84febd4537dd19/build/debs/', self.envs['E2E_OPT'])
        called = False
        for call in self.callstack:
            self.assertFalse(call.startswith('docker'))
            if call == 'hack/print-workspace-status.sh':
                called = True
        self.assertTrue(called)

    def test_kubeadm_pull(self):
        """Make sure kubeadm pull mode is fine overall."""
        args = self.parser.parse_args(['--mode=local', '--kubeadm=pull'])
        self.assertEqual(args.mode, 'local')
        self.assertEqual(args.kubeadm, 'pull')
        fake_env = {'PULL_NUMBER': 1234, 'PULL_REFS': 'master:abcd'}
        with Stub(kubernetes_e2e, 'check_env', self.fake_check_env):
            with Stub(os, 'environ', fake_env):
                kubernetes_e2e.main(args)

        self.assertIn('E2E_OPT', self.envs)
        self.assertIn('--kubernetes-anywhere-kubeadm-version gs://kubernetes-release-dev/bazel/'
                      '1234/master:abcd/bin/linux/amd64/', self.envs['E2E_OPT'])

    def test_kubeadm_invalid(self):
        """Make sure kubeadm invalid mode exits unsuccessfully."""
        with self.assertRaises(SystemExit) as sysexit:
            self.parser.parse_args(['--mode=local', '--kubeadm=deploy'])

        self.assertEqual(sysexit.exception.code, 2)

class DockerTest(ScenarioTest):
    """Class for testing e2e scenario in docker mode."""
    def test_docker(self):
        """Make sure docker mode is fine overall."""
        args = self.parser.parse_args()
        self.assertEqual(args.mode, 'docker')
        with Stub(kubernetes_e2e, 'check_env', fake_bomb):
            kubernetes_e2e.main(args)

        self.assertEqual(self.envs, {})
        for call in self.callstack:
            self.assertTrue(call.startswith('docker'))

    def test_default_tag(self):
        """Ensure the default tag exists on gcr.io."""
        args = self.parser.parse_args()
        match = re.match('gcr.io/([^:]+):(.+)', kubernetes_e2e.kubekins(args.tag))
        self.assertIsNotNone(match)
        url = 'https://gcr.io/v2/%s/manifests/%s' % (match.group(1),
                                                     match.group(2))
        data = json.loads(urllib.urlopen(url).read())
        self.assertNotIn('errors', data)
        self.assertIn('name', data)

    def test_docker_env(self):
        """
            Ensure that host variables (such as GOPATH) are excluded,
            and OS envs are included.
        """
        mode = kubernetes_e2e.DockerMode(
            'fake-container', '/host-workspace', False, 'fake-tag', [])
        mode.add_environment(*('FOO=BAR', 'GOPATH=/something/else',
                               'WORKSPACE=/new/workspace'))
        mode.add_os_environment('USER=jenkins')
        self.assertIn('FOO=BAR', mode.cmd)
        self.assertIn('WORKSPACE=/workspace', mode.cmd)
        self.assertNotIn('GOPATH=/something/else', mode.cmd)
        self.assertIn('USER=jenkins', mode.cmd)

if __name__ == '__main__':
    unittest.main()
