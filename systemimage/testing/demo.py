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

"""A helper for demos."""

__all__ = [
    'DemoDevice',
    'DemoReboot',
    ]


from systemimage.device import BaseDevice
from systemimage.reboot import BaseReboot


class DemoReboot(BaseReboot):
    def reboot(self):
        print("If I was a phone, I'd be rebooting right about now.")


class DemoDevice(BaseDevice):
    def get_device(self):
        """Sure, why not be a grouper?"""
        return 'grouper'
