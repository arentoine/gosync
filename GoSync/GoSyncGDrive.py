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
import shutil
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json, pickle

class ClientSecretsNotFound(RuntimeError):
    """Client secrets file was not found"""
class GDriveConnectionFailed(RuntimeError):
    """Connection to Google Drive Failed"""

class GDrive(object):
    def __init__(self,Config_Path, Logger):
#	    object.__init__(self)
        self.logger = Logger
        self.logger.debug("GDrive - Initialize - Started")

        self.is_logged_in = False
        self.credential_file = os.path.join(Config_Path, "credentials.json")
        self.client_pickle = os.path.join(Config_Path, "token.pickle")
        self.PageTokenFile = os.path.join(Config_Path, "page.token")
        # "Usage": {"Document Size": 220972, "Movies Size": 0, "Audio Size": 0, "Total Files": 15, "Others Size": 1801790, "Total Size": 16106127360, "Photo Size": 0}
        self.Usage = {}
        # "Account": {u'storageQuota': {u'usage': u'2943663', u'usageInDrive': u'2943663', u'usageInDriveTrash': u'920746', u'limit': u'16106127360'}, u'user': {u'me': True, u'emailAddress': u'testgosynch@gmail.com', u'kind': u'drive#user', u'displayName': u'Alain Robillard', u'permissionId': u'17558265559848359847'}}
        self.Account = {}
        # Active Google Drive Session 
        self.Session = ''

        self.ResetUsage()
        self.Connect()
        # Last Good Next Sync PagenToken
        self.LoadPageToken()
        self.FetchChanges()
        self.logger.info("GDrive - Initialize - Completed")
        
    def ResetUsage(self):
        # Resets to 0 all Disk Usage Stats
        self.Usage['Total Files'] = 0
        self.Usage['Total Size'] = 0
        self.Usage['Audio Size'] = 0
        self.Usage['Movies Size'] = 0
        self.Usage['Document Size'] = 0
        self.Usage['Photo Size'] = 0
        self.Usage['Others Size'] = 0

    def GetAudioUsage(self):
        return self.Usage['Audio Size']

    def GetMovieUsage(self):
        return self.Usage['Movies Size']

    def GetDocumentUsage(self):
        return self.Usage['Document Size']

    def GetOthersUsage(self):
        return self.Usage['Others Size']

    def GetPhotoUsage(self):
        return self.Usage['Photo Size']

    def Connect(self):
        self.logger.debug("GDrive - Connect - Started")
        if (not self.CredentialFileExists()) :
            self.logger.error("GDrive - Connect - Missing Credential File")
            raise ClientSecretsNotFound()
#        self.logger.debug("GDrive - Connect - Found Credential File")
        if (not self.DoAuthenticate()) : 
            self.logger.error("GDrive - Connect - Failed to Connect")
            raise GDriveConnectionFailed()
        self.Account = self.Session.about().get(fields='user, storageQuota').execute()
        self.logger.info("GDrive - Connect - Completed")

    def AskChooseCredentialsFile(self):
        dial = wx.MessageDialog(None, 'No Credentials file was found!\n\nDo you want to load one?\n',
                                'Error', wx.YES_NO | wx.ICON_EXCLAMATION)
        res = dial.ShowModal()
        if res == wx.ID_YES:
            return True
        else:
            return False

    def CredentialFileExists(self) :
        self.logger.debug("GDrive - CredentialFileExists - Started")
        Return_Code = True
        if not os.path.exists(self.credential_file):
        #check if Credentials.json file exists
            self.logger.debug("GDrive - CredentialFileExists - Missing Credentials File")
            if (self.AskChooseCredentialsFile()):
                self.logger.debug("GDrive - CredentialFileExists - Requesting Location of Credentials File")    
                if (self.getCredentialFile() == False) :
                    self.logger.error("GDrive - CredentialFileExists - Failed to load Credentials File")   
                    Return_Code = False 
#                    raise ClientSecretsNotFound()
            else:
                self.logger.debug("GDrive - CredentialFileExists - Declined to Locate Credentials File")    
                Return_Code = False
#                raise ClientSecretsNotFound()
        self.logger.debug("GDrive - CredentialFileExists - Completed")
        return Return_Code

    def getCredentialFile(self):
        # ask for the Credential file and save it in Config directory then return True
#        defDir, defFile = '', ''
        dlg = wx.FileDialog(None,
               'Load Credential File',
                 '~', 'Credentials.json',
                 'json files (*.json)|*.json',
                 wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_CANCEL:
            return False
        try:
            shutil.copy(dlg.GetPath(), self.credential_file)
            return True
        except:
            return False

    def DoAuthenticate(self):
        self.logger.debug("GDrive - DoAuthenticate - Started")
        try:
            # If modifying these scopes, delete the file token.pickle.
            SCOPES = ['https://www.googleapis.com/auth/drive']
            creds = None
            # The file token.pickle stores the user's access and refresh tokens, and is
            # created automatically when the authorization flow completes for the first
            # time.
            if os.path.exists(self.client_pickle):
                with open(self.client_pickle, 'rb') as token:
                    creds = pickle.load(token)
            # If there are no (valid) credentials available, let the user log in.
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(self.credential_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open(self.client_pickle, 'wb') as token:
                    pickle.dump(creds, token)

            service = build('drive', 'v3', credentials=creds)
            self.Session = service
            self.is_logged_in = True
            return service
        except:
            dial = wx.MessageDialog(None, "Authentication Rejected!\n",
                                    'Information', wx.ID_OK | wx.ICON_EXCLAMATION)
            dial.ShowModal()
            self.is_logged_in = False
            self.logger.debug("GDrive - DoAuthenticate - Failed")
            pass
        self.logger.debug("GDrive - DoAuthenticate - Completed")

    def DoUnAuthenticate(self):
            self.do_sync = False
            self.observer.unschedule(self.iobserv_handle)
            self.iobserv_handle = None
            os.remove(self.configs.credential_file)
            self.is_logged_in = False

    def LoadPageToken(self):
        self.logger.debug("GDrive - LoadPageToken - Started")
        PageToken_json = None
        try:
            f = open(self.PageTokenFile, 'r')
            PageToken_json = json.load(f)
            self.PageToken = PageToken_json['Page_Token']
            f.close()
        except:
            response = self.Session.changes().getStartPageToken().execute()
            self.PageToken = response.get('startPageToken')
            print('Token : %s' % self.PageToken)
            self.SavePageToken()
#            raise ConfigLoadFailed()
        self.logger.debug("GDrive - LoadPageToken - Completed")

    def SavePageToken(self):
        self.logger.debug("GDrive - SavePageToken - Started")
        PageToken_json = {}
        f = open(self.PageTokenFile, 'w')
        f.truncate()
        PageToken_json['Page_Token'] = self.PageToken
        json.dump(PageToken_json, f)
        f.close()
        self.logger.debug("Configs - SaveConfigFile - Completed")

    # Begin with our last saved start token for this user or the
    # current token from getStartPageToken()
    def FetchChanges(self):
        self.logger.debug("GDrive - FetchChanges - Started")
        page_token = self.PageToken
        print('Token : %s' % page_token)
        while page_token is not None:
            response = self.Session.changes().list(pageToken=page_token, spaces='drive').execute()
            for change in response.get('changes'):
                # Process change
                print 'Change found for file: %s' % change
            if 'newStartPageToken' in response:
                # Last page, save this token for the next polling interval
                self.PageToken = response.get('newStartPageToken')
            page_token = response.get('nextPageToken')
        self.SavePageToken()
        self.logger.debug("Configs - FetchChanges - Completed")


