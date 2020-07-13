#!/usr/bin/env python
#
# VM Backup extension
#
# Copyright 2015 Microsoft Corporation
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
#
# Requires Python 2.7+
#

from OSEncryptionState import OSEncryptionState


class PrereqState(OSEncryptionState):
    def __init__(self, context):
        super(PrereqState, self).__init__('PrereqState', context)

    def should_enter(self):
        self.context.logger.log("Verifying if machine should enter prereq state")

        if not super(PrereqState, self).should_enter():
            return False

        self.context.logger.log("Performing enter checks for prereq state")

        return True

    def enter(self):
        if not self.should_enter():
            return

        self.context.logger.log("Entering prereq state")

        distro_info = self.context.distro_patcher.distro_info
        self.context.logger.log("Distro info: {0}".format(distro_info))

        if ((distro_info[0] == 'redhat' and distro_info[1] == '8.1') or
           (distro_info[0] == 'redhat' and distro_info[1] == '8.2')):
            self.context.logger.log("Enabling OS volume encryption on {0} {1}".format(distro_info[0],
                                                                                      distro_info[1]))
        else:
            raise Exception("RHEL81EncryptionStateMachine called for distro {0} {1}".format(distro_info[0],
                                                                                            distro_info[1]))

        self.context.distro_patcher.install_extras()

        # if the detached header fix is not present we can't proceed:
        if not self._is_detached_header_fix():
            raise Exception("systemd-cryptsetup does not have support for the required kernel params 'rd.luks.data' and 'rd.luks.hdr'. Please update the package systemd-cryptsetup-udev")

    def should_exit(self):
        self.context.logger.log("Verifying if machine should exit prereq state")

        return super(PrereqState, self).should_exit()

    def _is_detached_header_fix(self):
        # TODO: We need to ask the redhat folks the best way to do this, for now I will just scan the man pages
        ret_code = self.command_executor.ExecuteInBash("man systemd-cryptsetup-generator | grep luks.hdr")
        return ret_code == 0
