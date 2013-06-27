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

"""Handle GPG signature verification."""

__all__ = [
    'Context',
    'SignatureError',
    ]


import os
import gnupg
import shutil
import tarfile
import tempfile

from contextlib import ExitStack
from systemimage.config import config
from systemimage.helpers import temporary_directory


class SignatureError(Exception):
    """Exception raised when some signature fails to validate.

    Note that this exception isn't raised by Context.verify(); that method
    always returns a boolean.  This exception is used by other functions to
    signal that a .asc file did not match.
    """


class Context:
    def __init__(self, *keyrings, blacklist=None):
        self._ctx = None
        self._stack = ExitStack()
        self._keyrings = []
        # The keyrings must be .tar.xz files, which need to be unpacked and
        # the keyring.gpg files inside them cached, using their actual name
        # (based on the .tar.xz file name).  If we don't already have a cache
        # of the .gpg file, do the unpackaging and use the contained .gpg file
        # as the keyring.  Note that this class does *not* validate the
        # .tar.xz files.  That must be done elsewhere.
        for path in keyrings:
            base, dot, tarxz = os.path.basename(path).partition('.')
            assert dot == '.' and tarxz == 'tar.xz', (
                'Expected a .tar.xz path, got: {}'.format(path))
            keyring_path = os.path.join(
                config.system.tempdir, base + '.gpg')
            if not os.path.exists(keyring_path):
                with tarfile.open(path, 'r:xz') as tf:
                    tf.extract('keyring.gpg', config.system.tempdir)
                    os.rename(
                        os.path.join(config.system.tempdir, 'keyring.gpg'),
                        os.path.join(config.system.tempdir, keyring_path))
            self._keyrings.append(keyring_path)
        # Since python-gnupg doesn't do this for us, verify that all the
        # keyrings and blacklist files exist.  Yes, this introduces a race
        # condition, but I don't see any good way to eliminate this given
        # python-gnupg's behavior.
        for path in self._keyrings:
            if not os.path.exists(path):
                raise FileNotFoundError(path)
        if blacklist is not None:
            if not os.path.exists(blacklist):
                raise FileNotFoundError(blacklist)
            # Extract all the blacklisted fingerprints.
            with Context(blacklist) as ctx:
                self._blacklisted_fingerprints = ctx.fingerprints
        else:
            self._blacklisted_fingerprints = set()

    def __enter__(self):
        try:
            # Use a temporary directory for the $GNUPGHOME, but be sure to
            # arrange for the tempdir to be deleted no matter what.
            home = self._stack.enter_context(
                temporary_directory(prefix='.otaupdate'))
            self._ctx = gnupg.GPG(gnupghome=home, keyring=self._keyrings)
            self._stack.callback(setattr, self, '_ctx', None)
        except:
            # Restore all context and re-raise the exception.
            self._stack.close()
            raise
        else:
            return self

    def __exit__(self, *exc_details):
        self._stack.close()
        # Don't swallow exceptions.
        return False

    @property
    def keys(self):
        return self._ctx.list_keys()

    @property
    def fingerprints(self):
        return set(info['fingerprint'] for info in self._ctx.list_keys())

    @property
    def key_ids(self):
        return set(info['keyid'] for info in self._ctx.list_keys())

    def verify(self, signature_path, data_path):
        with open(signature_path, 'rb') as sig_fp:
            verified = self._ctx.verify_file(sig_fp, data_path)
        # If the file is properly signed, we'll be able to get back a set of
        # fingerprints that signed the file.   From here we do a set operation
        # to see if the fingerprints are in the list of keys from all the
        # loaded-up keyrings.  If so, the signature succeeds.
        return verified.fingerprint in (self.fingerprints -
                                        self._blacklisted_fingerprints)