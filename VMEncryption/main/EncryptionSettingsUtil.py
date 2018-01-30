#!/usr/bin/env python
#
# Copyright (c) Microsoft Corporation
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

import httplib
import json
import os
import socket
import re

from shutil import copyfile
import uuid
from Common import CommonVariables
from HttpUtil import HttpUtil

class EncryptionSettingsUtil(object):
    """ Provides capability to update encryption settings via wire server """

    def __init__(self, logger):
        self.logger = logger

    def get_index(self):
        """get the integer value of the current index in the counter"""
        index = 0
        if os.path.isfile(CommonVariables.encryption_settings_counter_path):
            with open(CommonVariables.encryption_settings_counter_path, "r") as infile:
                index_string = infile.readline().strip()
            try:
                index = int(index_string)
            except ValueError:
                self.logger.log("counter file contents were invalid, returning index value 0")
        else:
            self.logger.log("encryption settings counter file not found, returning index value 0")
        return abs(index)

    def increment_index(self):
        """increment the internal counter used to index the encryption settings json file"""
        index = self.get_index()
        # specify buffering = 0 and then use os.fsync to flush
        # https://docs.python.org/2/library/functions.html#open
        # https://linux.die.net/man/2/fsync
        with open(CommonVariables.encryption_settings_counter_path, "w", 0) as outfile:
            outfile.write(str(index + 1) + "\n")
            os.fsync(outfile)
        return

    def get_new_protector_name(self):
        """get a new guid to use as the protector name to pass to host"""
        # https://docs.microsoft.com/en-us/powershell/module/azurerm.keyvault/add-azurekeyvaultkey
        # The name must be a string of 1 through 63 characters in length
        # that contains only 0-9, a-z, A-Z, and - (the dash symbol).
        return str(uuid.uuid4())

    def create_protector_file(self, protector_name):
        """create temporary protector file corresponding to protector name"""
        src = CommonVariables.encryption_key_mount_point + '/' + CommonVariables.encryption_key_file_name
        dst = CommonVariables.encryption_key_mount_point + '/' + protector_name
        copyfile(src, dst)
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.sync()
        return

    def remove_protector_file(self, protector_name):
        """remove temporary protector file corresponding to protector name parameter"""
        os.remove(CommonVariables.encryption_key_mount_point + '/' + protector_name)
        return

    def get_settings_file_path(self):
        """get the full path to the current encryption settings file"""
        return CommonVariables.encryption_key_mount_point + '/' + self.get_settings_file_name()

    def get_settings_file_name(self):
        """get the base file name of the current encryption settings file"""
        padded_index = str(self.get_index()).zfill(2)
        return CommonVariables.encryption_settings_file_name_pattern.format(padded_index)

    def check_url(self, test_url, message):
        """basic sanity check of the key vault url"""
        expected = "https://{keyvault-name}.{vault-endpoint}/{object-type}/{object-name}/{object-version}"
        if not (test_url and test_url.startswith('https://')):
            raise Exception('\n' + message + '\nActual: ' + test_url + '\nExpected: ' + expected + "\n")
        return

    def check_id(self, test_id, message):
        """basic sanity check of the key vault id"""
        # more strict checking would validate the full key vault id format
        expected = "/subscriptions/{subid}/resourceGroups/{rgname}/providers/Microsoft.KeyVault/vaults/{vaultname}"
        if not (test_id and test_id.startswith('/subscriptions/')):
            raise Exception('\n' + message + '\nActual: ' + test_id + '\nExpected: ' + expected + "\n")
        return

    def get_settings_data(self, protector_name, kv_url, kv_id, kek_url, kek_kv_id, kek_algorithm):
        """ returns encryption settings object in format required by wire server """

        # validate key vault parameters prior to creating the encryption settings object
        self.check_url(kv_url, "Key Vault URL is required, but was missing or invalid")
        self.check_id(kv_id, "Key Vault ID is required, but was missing or invalid")
        if kek_url:
            self.check_url(kek_url, "A KEK URL was specified, but was invalid")
            self.check_id(kek_kv_id, "A KEK URL was specified, but its KeyVault ID was invalid")
            if kek_algorithm not in CommonVariables.encryption_algorithms:
                if kek_algorithm:
                    raise Exception(
                        "The KEK encryption algorithm requested was not recognized")
                else:
                    kek_algorithm = CommonVariables.default_encryption_algorithm
                    self.logger.log(
                        "No KEK algorithm specified, defaulting to {0}".format(kek_algorithm))
        else:
            if kek_kv_id:
                raise Exception(
                    "The KEK KeyVault ID was specified but the KEK URL was missing")

        #create encryption settings object
        self.logger.log("Creating encryption settings object")
        
        #validate machine name string or use empty string
        machine_name = socket.gethostname()
        if re.match('^[\w-]+$', machine_name) is None:
            machine_name = ''

        data = {
            "DiskEncryptionDataVersion": "2.0",
            "DiskEncryptionOperation": "EnableEncryption",
            "KeyVaultUrl": kv_url,
            "KeyVaultResourceId": kv_id,
            "KekUrl": kek_url,
            "KekVaultResourceId": kek_kv_id,
            "KekAlgorithm": kek_algorithm,
            "Disks": [
                {
                    "ControllerType": "IDE",
                    "ControllerId": 0,
                    "SlotId": 0,
                    "Volumes": [
                        {
                            "VolumeType": "OsVolume",
                            "ProtectorFileName": protector_name,
                            "SecretTags": [
                                {
                                    "Name": "DiskEncryptionKeyFileName",
                                    "Value": CommonVariables.encryption_key_file_name
                                },
                                {
                                    "Name": "DiskEncryptionKeyEncryptionKeyURL",
                                    "Value": kek_url
                                },
                                {
                                    "Name": "DiskEncryptionKeyEncryptionAlgorithm",
                                    "Value": kek_algorithm
                                },
                                {
                                    "Name": "MachineName",
                                    "Value": machine_name
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        return data

    def write_settings_file(self, data):
        """ Dump encryption settings data to JSON formatted file on key volume """
        self.increment_index()
        with open(self.get_settings_file_path(), 'w', 0) as outfile:
            json.dump(data, outfile)
            os.fsync(outfile)
        return

    def post_to_wireserver(self):
        """ Request EnableEncryption operation on settings file via wire server """
        if not os.path.isfile(self.get_settings_file_path()):
            raise Exception(
                'Disk encryption settings file not found: ' + self.get_settings_file_path())

        http_util = HttpUtil(self.logger)
        result = http_util.Call(method='POST',
                                http_uri=CommonVariables.wireserver_endpoint,
                                headers=CommonVariables.wireprotocol_msg_headers,
                                data=CommonVariables.wireprotocol_msg_template_v2.format(
                                    settings_file_name=self.get_settings_file_name()),
                                use_https=False)

        if result is not None:
            self.logger.log("{0} {1}".format(result.status, result.getheaders()))

            result_content = result.read()
            self.logger.log("result_content is {0}".format(result_content))

            http_util.connection.close()
            if result.status != httplib.OK and result.status != httplib.ACCEPTED:
                raise Exception("encryption settings update request was not accepted")
            return
        else:
            raise Exception("no response from encryption settings update request")

    def clear_encryption_settings(self):
        """ Clear settings by calling DisableEncryption operation via wire server"""
        data = {"DiskEncryptionDataVersion": "2.0",
                "DiskEncryptionOperation": "DisableEncryption",
                "Disks": "",
                "KekAlgorithm": "",
                "KekUrl": "",
                "KekVaultResourceId": "",
                "KeyVaultResourceId": "",
                "KeyVaultUrl": ""}
        self.write_settings_file(data)
        self.post_to_wireserver()
        return