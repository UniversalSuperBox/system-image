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

"""Test helpers."""

__all__ = [
    'copy',
    'get_channels',
    'get_index',
    'make_http_server',
    'makedirs',
    'setup_keyrings',
    'setup_remote_keyring',
    'sign',
    'test_data_path',
    'testable_configuration',
    ]


import os
import ssl
import json
import gnupg
import shutil
import tarfile
import tempfile

from contextlib import ExitStack, contextmanager
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pkg_resources import resource_filename, resource_string as resource_bytes
from resolver.channel import Channels
from resolver.config import Configuration, config
from resolver.helpers import atomic, temporary_directory
from resolver.index import Index
from threading import Thread
from unittest.mock import patch
from urllib.request import urlopen


def get_index(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Index.from_json(json_bytes.decode('utf-8'))


def get_channels(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Channels.from_json(json_bytes.decode('utf-8'))


def test_data_path(filename):
    return os.path.abspath(resource_filename('resolver.tests.data', filename))


def make_http_server(directory, port, certpem=None, keypem=None,
                     *, selfsign=True):
    """Create an HTTP/S server to vend from the file system.

    :param directory: The file system directory to vend files from.
    :param port: The port to listen on for the server.
    :param certpem: For HTTPS servers, the path to the certificate PEM file.
        If the file name does not start with a slash, it is considered
        relative to the test data directory.
    :param keypem: For HTTPS servers, the path to the key PEM file.  If the
        file name does not start with a slash, it is considered relative to
        the test data directory.
    :param selfsign: Flag indicating whether or not `urlopen()` should be
        patched to accept the self-signed certificate in certpem.
    :return: A context manager that when closed, stops the server.
    """
    # We need an HTTP/S server to vend the file system, or at least parts of
    # it, that we want to test.  Since all the files are static, and we're
    # only going to GET files, this makes our lives much easier.  We'll just
    # vend all the files in the directory.
    class RequestHandler(SimpleHTTPRequestHandler):
        # The base class hardcodes the use of os.getcwd() to vend the
        # files from, but we want to be able to pass in any directory.  I
        # suppose we could chdir in the server thread, but let's hack the
        # path instead.
        def translate_path(self, path):
            with patch('http.server.os.getcwd', return_value=directory):
                return super().translate_path(path)

        def log_message(self, *args, **kws):
            # Please shut up.
            pass
    # Create the server in the main thread, but start it in the sub-thread.
    # This lets the main thread call .shutdown() to stop everything.  Return
    # just the shutdown method to the caller.
    RequestHandler.directory = directory
    # Wrap the socket in the SSL context if given.
    ssl_context = None
    if certpem is not None and keypem is not None:
        data_dir = os.path.dirname(test_data_path('__init__.py'))
        if not os.path.isabs(certpem):
            certpem = os.path.join(data_dir, certpem)
        if not os.path.isabs(keypem):
            keypem = os.path.join(data_dir, keypem)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_context.load_cert_chain(certfile=certpem, keyfile=keypem)
    # Define a small class with a method that arranges for the self-signed
    # certificates to be valid in the client.
    with ExitStack() as stack:
        server = HTTPServer(('localhost', port), RequestHandler)
        server.allow_reuse_address = True
        stack.callback(server.server_close)
        if ssl_context is not None:
            server.socket = ssl_context.wrap_socket(
                server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.daemon = True
        def shutdown():
            server.shutdown()
            thread.join()
        stack.callback(shutdown)
        thread.start()
        if selfsign and ssl_context is not None:
            stack.enter_context(patch('resolver.download.urlopen',
                                      partial(urlopen, cafile=certpem)))
        # Everything succeeded, so transfer the resource management to a new
        # ExitStack().  This way, when the with statement above completes, the
        # server will still be running and urlopen() will still be patched.
        # The caller is responsible for closing the new ExitStack.
        return stack.pop_all()


def testable_configuration(function):
    """Decorator that produces a temporary configuration for testing.

    The config_00.ini template is copied to a temporary file and the
    [system]tempdir variable is filled in with the location for a, er,
    temporary temporary directory.  This temporary configuration file is
    loaded up and the global configuration object is patched so that all
    other code will see it instead of the default global configuration
    object.

    Everything is properly cleaned up after the test method exits.
    """
    def wrapper(*args, **kws):
        with ExitStack() as stack:
            fd, ini_file = tempfile.mkstemp(suffix='.ini')
            os.close(fd)
            stack.callback(os.remove, ini_file)
            temp_tmpdir = stack.enter_context(temporary_directory())
            temp_vardir = stack.enter_context(temporary_directory())
            template = resource_bytes(
                'resolver.tests.data', 'config_00.ini').decode('utf-8')
            with atomic(ini_file) as fp:
                print(template.format(tmpdir=temp_tmpdir,
                                      vardir=temp_vardir), file=fp)
            config = Configuration()
            config.load(ini_file)
            stack.enter_context(patch('resolver.config._config', config))
            return function(*args, **kws)
    return wrapper


def sign(filename, pubkey_ring):
    """GPG sign the given file, producing an armored detached signature.

    :param filename: The path to the file to sign.
    :param pubkey_ring: The public keyring containing the key to sign the file
        with.  This keyring must contain only one key, and its key id must
        exist in the master secret keyring.
    """
    with ExitStack() as stack:
        home = stack.enter_context(temporary_directory())
        secring = test_data_path('master-secring.gpg')
        pubring = test_data_path(pubkey_ring)
        ctx = gnupg.GPG(gnupghome=home, keyring=pubring,
                        #verbose=True,
                        secret_keyring=secring)
        public_keys = ctx.list_keys()
        assert len(public_keys) != 0, 'No keys found'
        assert len(public_keys) == 1, 'Too many keys'
        key_id = public_keys[0]['keyid']
        dfp = stack.enter_context(open(filename, 'rb'))
        signed_data = ctx.sign_file(dfp, keyid=key_id, detach=True)
        sfp = stack.enter_context(open(filename + '.asc', 'wb'))
        sfp.write(signed_data.data)


def makedirs(dir):
    try:
        os.makedirs(dir, exist_ok=True)
    except FileExistsError:
        pass


def copy(filename, todir, dst=None):
    src = test_data_path(filename)
    dst = os.path.join(todir, filename if dst is None else dst)
    makedirs(os.path.dirname(dst))
    shutil.copy(src, dst)


def setup_keyrings():
    copy('archive-master.gpg', os.path.dirname(config.gpg.archive_master))
    copy('image-master.gpg', os.path.dirname(config.gpg.image_master))
    copy('image-signing.gpg', os.path.dirname(config.gpg.image_signing))
    copy('vendor-signing.gpg', os.path.dirname(config.gpg.vendor_signing))


def setup_remote_keyring(keyring_src, signing_keyring, json_data, dst):
    """Set up remote keyrings, e.g. in a server's vending directory.

    The source keyring and json data is used to create a .tar.xz file and an
    associated .asc signature file.  These are then copied to the given
    destination path name.

    :param keyring_src: The source keyring (i.e. .gpg file).
    :param signing_keyring: The name of the keyring to sign the resulting
        tarball with.
    :param json_data: The JSON data dictionary.
    :param dst: The destination path of the .tar.xz file.  For the resulting
        signature file, the .asc suffix will be automatically appended.
    """
    with temporary_directory() as tmpdir:
        copy(keyring_src, tmpdir, 'keyring.gpg')
        json_path = os.path.join(tmpdir, 'keyring.json')
        with open(json_path, 'w', encoding='utf-8') as fp:
            json.dump(json_data, fp)
        # Tar up the .gpg and .json files into a .tar.xz file.
        tarxz_path = os.path.join(tmpdir, 'keyring.tar.xz')
        with tarfile.open(tarxz_path, 'w:xz') as tf:
            tf.add(os.path.join(tmpdir, 'keyring.gpg'), 'keyring.gpg')
            tf.add(json_path, 'keyring.json')
        sign(tarxz_path, signing_keyring)
        # Copy the .tar.xz and .asc files to the proper directory under
        # the path the https server is vending them from.
        makedirs(os.path.dirname(dst))
        shutil.copy(tarxz_path, dst)
        shutil.copy(tarxz_path + '.asc', dst + '.asc')
