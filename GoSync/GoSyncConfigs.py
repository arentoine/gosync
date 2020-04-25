# gosync is an open source Google Drive(TM) sync application for Linux
# modify it under the terms of the GNU General Public License
#
# Copyright (C) 2015 Himanshu Chauhan
# Copyright (C) 2020 Alain Robillard
# This program is free software; you can redistribute it and/or
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import sys, os, wx
import json, pickle
from GoSyncDriveTree import GoogleDriveTree

class ConfigLoadFailed(RuntimeError):
    """Failed to load the GoSync configuration file"""

class Configs(object):
    def __init__(self, Home_Path, Logger):
#	    object.__init__(self)
        self.home_path = Home_Path 
        self.logger = Logger
        self.logger.debug("Configs - Initialize - Started")

        self.config_path = os.path.join(self.home_path, ".gosync")       
        if not os.path.exists(self.config_path):
            os.mkdir(self.config_path, 0o0755)

        self.config_file = os.path.join(self.home_path, '.gosync', 'gosyncrc')
        self.driveTree = None
        self.tree_pickle_file = ''
        self.user_email = ''
        self.root_Id = ''

        self.base_mirror_directory = os.path.join(self.home_path, "Google Drive")
        if not os.path.exists(self.base_mirror_directory):
            os.mkdir(self.base_mirror_directory, 0o0755)

        self.user_mirror_directory = ''
        self.sync_selection = []
        self.config_dict = {}
        self.account_dict = {}
        self.drive_usage_dict = {}
        #experimental
        self.File_Status_Dict = {}
        self.logger.info("Configs - Initialize - Completed")

    def LoadConfigFile(self):
        self.logger.debug("Configs - LoadConfigFile - Started")
        config_json = None
        try:
            f = open(self.config_file, 'r')
            try:
                config_json = json.load(f)
                try:
                    self.user_email = config_json['user_email']
                    self.root_Id = config_json['root_id']
                    self.config_dict = config_json[self.user_email]
                    self.sync_selection = self.config_dict['Sync Selection']
                    try:
                        self.drive_usage_dict = self.config_dict['Drive Usage']
#                        self.logger.debug("Configs - LoadConfigFile - drive_usage_dict : %s" % self.drive_usage_dict)
                    except:
                        pass
                except:
                    pass

                f.close()
            except:
                raise ConfigLoadFailed()
        except:
            pass
#            raise ConfigLoadFailed()
        self.logger.debug("Configs - LoadConfigfile - Completed")

    def SaveConfigFile(self):
        self.logger.info("Configs - SaveConfigFile - Started")
        f = open(self.config_file, 'w')
        f.truncate()
        if not self.sync_selection:
            self.config_dict['Sync Selection'] = [['root', '']]

        self.account_dict['user_email'] = self.user_email
        self.account_dict['root_id'] = self.root_Id
        self.account_dict[self.user_email] = self.config_dict

        json.dump(self.account_dict, f)
        f.close()
        self.logger.debug("Configs - SaveConfigFile - Completed")

#    def CreateDefaultConfigFile(self):
#        f = open(self.config_file, 'w')
#        self.config_dict['Sync Selection'] = [['root', '']]
#        self.account_dict['user_email'] = self.user_email
#        self.account_dict[self.user_email] = self.config_dict
#        json.dump(self.account_dict, f)
#        f.close()

    def UpdateConfig(self, Account):
    #create subdir linked to active account
        self.logger.debug("Configs - UpdateConfig - Started")
        self.user_email = Account['user']['emailAddress']

#        self.logger.debug("Configs - UpdateConfig - tree_pickle_file - Started")
        self.tree_pickle_file = os.path.join(self.config_path, 'gtree-' + self.user_email + '.pick')
        if not os.path.exists(self.tree_pickle_file):
            self.driveTree = GoogleDriveTree()
        else:
            try:
                self.driveTree = pickle.load(open(self.tree_pickle_file, "rb"))
            except:
                self.driveTree = GoogleDriveTree()
#        self.logger.debug("Configs - UpdateConfig - tree_pickle_file - Completed")

#        self.logger.debug("Configs - UpdateConfig - user_mirror_directory - Started")
        self.user_mirror_directory = os.path.join(self.base_mirror_directory, self.user_email)
        if not os.path.exists(self.user_mirror_directory):
            os.mkdir(self.user_mirror_directory, 0o0755)
#        self.logger.debug("Configs - UpdateConfig - tree_pickle_file - Completed")

#        self.logger.debug("Configs - UpdateConfig - ConfigFile - Started")
        if not os.path.exists(self.config_file):
            self.SaveConfigFile()
#            self.CreateDefaultConfigFile()
        try:
            self.LoadConfigFile()
        except:
            raise
#        self.logger.debug("Configs - UpdateConfig - tree_pickle_file - Completed")
        self.logger.info("Configs - UpdateConfig - Completed")
