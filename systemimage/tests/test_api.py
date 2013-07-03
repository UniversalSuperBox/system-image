# Copyright (C) 2013 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test the DBus API mediator."""


__all__ = [
    'TestAPI',
    ]


import os
import unittest

from contextlib import ExitStack
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.tests.helpers import (
    copy, make_http_server, setup_index, setup_keyring_txz, setup_keyrings,
    sign, temporary_directory, testable_configuration)

class TestAPI(unittest.TestCase):

    def setUp(self):
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            # Start up both an HTTPS and HTTP server.  The data files are
            # vended over the latter, everything else, over the former.
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
            self._stack.push(make_http_server(self._serverdir, 8980))
            # Set up the server files.
            copy('channels_06.json', self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            self.index_path = os.path.join(
                self._serverdir, 'stable', 'nexus7', 'index.json')
            head, tail = os.path.split(self.index_path)
            copy('index_13.json', head, tail)
            sign(self.index_path, 'device-signing.gpg')
            setup_index('index_13.json', self._serverdir, 'device-signing.gpg')
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    def _setup_keyrings(self):
        # Only the archive-master key is pre-loaded.  All the other keys
        # are downloaded and there will be both a blacklist and device
        # keyring.  The four signed keyring tar.xz files and their
        # signatures end up in the proper location after the state machine
        # runs to completion.
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7',
                         'device-signing.tar.xz'))

    @testable_configuration
    def test_update_available(self):
        # Because our build number is lower than the latest available in the
        # index file, there is an update available.
        self._setup_keyrings()
        mediator = Mediator()
        self.assertTrue(mediator.check_for_update())

    @testable_configuration
    def test_no_update_available_at_latest(self):
        # Because our build number is equal to the latest available in the
        # index file, there is no update available.
        self._setup_keyrings()
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130600, file=fp)
        mediator = Mediator()
        self.assertFalse(mediator.check_for_update())

    @testable_configuration
    def test_no_update_available_newer(self):
        # Because our build number is higher than the latest available in the
        # index file, there is no update available.
        self._setup_keyrings()
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130700, file=fp)
        mediator = Mediator()
        self.assertFalse(mediator.check_for_update())

    @testable_configuration
    def test_get_details(self):
        # Get the details of an available update.
        self._setup_keyrings()
        # Index 14 has a more interesting upgrade path, and will yield a
        # richer description set.
        head, tail = os.path.split(self.index_path)
        copy('index_14.json', head, tail)
        sign(self.index_path, 'device-signing.gpg')
        setup_index('index_14.json', self._serverdir, 'device-signing.gpg')
        # Get the descriptions.
        mediator = Mediator()
        update = mediator.check_for_update()
        self.assertTrue(update)
        self.assertEqual(update.size, 180009)
        self.assertEqual(len(update.descriptions), 3)
        # The first contains the descriptions for the full update.
        self.assertEqual(update.descriptions[0], {
            'description': 'Full B',
            'description-en': 'The full B',
            })
        # The first delta.
        self.assertEqual(update.descriptions[1], {
            'description': 'Delta B.1',
            'description-en_US': 'This is the delta B.1',
            'description-xx': 'XX This is the delta B.1',
            'description-yy': 'YY This is the delta B.1',
            'description-yy_ZZ': 'YY-ZZ This is the delta B.1',
            })
        # The second delta.
        self.assertEqual(update.descriptions[2], {
            'description': 'Delta B.2',
            'description-xx': 'Oh delta, my delta',
            'description-xx_CC': 'This hyar is the delta B.2',
            })
