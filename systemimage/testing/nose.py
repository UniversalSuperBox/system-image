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

"""Nose plugin for testing."""

__all__ = [
    'SystemImagePlugin',
    ]


import re
import sys

from dbus.mainloop.glib import DBusGMainLoop
from nose.plugins import Plugin
from systemimage.logging import initialize
from systemimage.testing.controller import Controller
from systemimage.testing.helpers import configuration


# Why are these tests set up like this?
#
# LP: #1205163 provides the impetus.  Here's the problem: we have to start a
# dbus-daemon child process which will create an isolated system bus on which
# the services we want to talk to will be started via dbus-activatiion.  This
# closely mimics how the real system starts up our services.
#
# We ask dbus-daemon to return us its pid and the dbus address it's listening
# on.  We need the address because we have to ensure that the dbus client,
# i.e. this foreground test process, can communicate with the isolated
# service.  To do this, the foreground process sets the environment variable
# DBUS_SYSTEM_BUS_ADDRESS to the address that dbus-daemon gave us.
#
# The problem is that the low-level dbus client library only consults that
# envar when it initializes, which it only does once per process.  There's no
# way to get the library to listen on a new DBUS_SYSTEM_BUS_ADDRESS later on.
#
# This means that our first approach, which involved killing the grandchild
# service processes, and the child dbus-daemon process, and then restarting a
# new dbus-daemon process on a new address, doesn't work.
#
# We need new service processes for many of our test cases because we have to
# start them up in different testing modes, and there's no way to do that
# without exiting them and restarting them.  The grandchild processes get
# started via different .service files with different commands.
#
# So, we have to restart the service process, but *not* the dbus-daemon
# process because for all of these tests, it must be listening on the same
# system bus.  Fortunately, dbus-daemon responds to SIGHUP, which tells it to
# re-read its configuration files, including its .service files.  So how this
# works is that at the end of each test class, we tell the dbus service to
# .Exit(), wait until it has, then write a new .service file with the new
# command, HUP the dbus-daemon, and now the next time it activates the
# service, it will do so with the correct (i.e. newly written) command.

class SystemImagePlugin(Plugin):
    enabled = True
    controller = None

    @configuration
    def begin(self):
        DBusGMainLoop(set_as_default=True)
        # Count verbosity.  There might be a better way to do this through
        # nose's command line option handling.
        verbosity = 0
        for arg in sys.argv[1:]:
            mo = re.match('^-(?P<verbose>v+)$', arg)
            if mo:
                verbosity += len(mo.group('verbose'))
        initialize(verbosity=verbosity)
        # We need to set up the dbus service controller, since all the tests
        # which use a custom address must continue to use the same address for
        # the duration of the test process.  We can kill and restart
        # individual services, and we can write new dbus configuration files
        # and HUP the dbus-launch to re-read them, but we cannot change bus
        # addresses after the initial one is set.
        SystemImagePlugin.controller = Controller()
        SystemImagePlugin.controller.start()

    def finalize(self, result):
        SystemImagePlugin.controller.stop()
        # Let other plugins continue printing.
        return None
