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

"""Nodes in the JSON resource tree."""

__all__ = [
    'Channel',
    'Channels',
    'Index',
    ]


import json


class Index:
    def __init__(self, name, path):
        self.name = name
        self.path = path


class Channel:
    def __init__(self, name, indexes):
        self.name = name
        self.indexes = indexes


class Channels:
    def __init__(self, data):
        self.channels = {}
        mapping = json.loads(data)
        for channel_name, index_data in mapping.items():
            indexes = {}
            for index_name, path in index_data.items():
                index = Index(index_name, path)
                indexes[index_name] = index
            channel = Channel(channel_name, indexes)
            self.channels[channel_name] = channel
