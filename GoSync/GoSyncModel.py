# gosync is an open source Google Drive(TM) sync application for Linux
# modify it under the terms of the GNU General Public License
#
# Copyright (C) 2015 Himanshu Chauhan
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

import sys, os, wx, ntpath, defines, threading, hashlib, time, copy, io
import shutil
from os.path import expanduser
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from threading import Thread
from apiclient.errors import HttpError
from apiclient import errors
from apiclient.http import MediaFileUpload
from apiclient.http import MediaIoBaseDownload
import logging
from defines import *
from GoSyncEvents import *
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from GoSyncSync import SyncDown
from GoSyncConfigs import Configs
from GoSyncGDrive import GDrive
import json, pickle

class ClientSecretsNotFound(RuntimeError):
    """Client secrets file was not found"""
class GDriveConnectionFailed(RuntimeError):
    """Connection to Google Drive Failed"""
class FileNotFound(RuntimeError):
    """File was not found on google drive"""
class FolderNotFound(RuntimeError):
    """Folder on Google Drive was not found"""
class UnknownError(RuntimeError):
    """Unknown/Unexpected error happened"""
class MD5ChecksumCalculationFailed(RuntimeError):
    """Calculation of MD5 checksum on a given file failed"""
class RegularFileUploadFailed(RuntimeError):
    """Upload of a regular file failed"""
class RegularFileTrashFailed(RuntimeError):
    """Could not move file to trash"""
class FileListQueryFailed(RuntimeError):
    """The query of file list failed"""
class ConfigLoadFailed(RuntimeError):
    """Failed to load the GoSync configuration file"""

audio_file_mimelist = ['audio/mpeg', 'audio/x-mpeg-3', 'audio/mpeg3', 'audio/aiff', 'audio/x-aiff']
movie_file_mimelist = ['video/mp4', 'video/x-msvideo', 'video/mpeg', 'video/flv', 'video/quicktime']
image_file_mimelist = ['image/png', 'image/jpeg', 'image/jpg', 'image/tiff']
document_file_mimelist = ['application/powerpoint', 'applciation/mspowerpoint', \
                              'application/x-mspowerpoint', 'application/pdf', \
                              'application/x-dvi']
google_docs_mimelist = ['application/vnd.google-apps.spreadsheet', \
                            'application/vnd.google-apps.sites', \
                            'application/vnd.google-apps.script', \
                            'application/vnd.google-apps.presentation', \
                            'application/vnd.google-apps.fusiontable', \
                            'application/vnd.google-apps.form', \
                            'application/vnd.google-apps.drawing', \
                            'application/vnd.google-apps.document', \
                            'application/vnd.google-apps.map']

class GoSyncModel(object):
    def __init__(self):
        home_path = os.environ['HOME']
        self.calculatingDriveUsage = False
        self.fcount = 0
        self.updates_done = 0

        # Start Logging
        self.logger = self.initializeLogger(home_path, 'GoSync.log')

        self.logger.info("GoSyncModel - Initialize - Started")

        #Retrieve / Initialize Application Configurations Object 
        self.configs = Configs(home_path, self.logger)

        #Initialize Google Drive Object
        self.Drive = GDrive(self.configs.config_path, self.logger)
 
        #Update Configs once Connected
        self.configs.UpdateConfig(self.Drive.Account)
        self.Drive.Usage = self.configs.drive_usage_dict

        self.observer = Observer()
        
        self.logger.info("GoSyncModel - Initialize - Completed")

        # Test Class SyncDown
#        self.sync_download = SyncDown(self.drive)
#        self.logger.debug("Initialize - SyncDown Class")
#        self.page_token = self.sync_download.SyncInit()
#        self.logger.debug("Initialize - Received Initial Page Token")
#        self.page_token = self.sync_download.SyncNow(self.page_token)
#        self.logger.debug("Synchronize - Completed first Loop")

        #todo : confirm this is to monitor file changes
        self.iobserv_handle = self.observer.schedule(FileModificationNotifyHandler(self), self.configs.user_mirror_directory, recursive=True)
        self.sync_lock = threading.Lock()
        self.sync_thread = threading.Thread(target=self.run)
        self.usage_calc_thread = threading.Thread(target=self.calculateUsage)
        self.sync_thread.daemon = True
        self.usage_calc_thread.daemon = True
        self.syncRunning = threading.Event()
        self.syncRunning.clear()
        self.usageCalculateEvent = threading.Event()
        self.usageCalculateEvent.set()

    def initializeLogger(self, Logging_Path, Logging_FileName):
        logger = logging.getLogger(APP_NAME)
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(os.path.join(Logging_Path, Logging_FileName))
#        fh.setLevel(logging.INFO)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        return logger
 
 
    def SetTheBallRolling(self):
        self.sync_thread.start()
        self.usage_calc_thread.start()
        self.observer.start()

    def IsUserLoggedIn(self):
        return self.is_logged_in

    def HashOfFile(self, abs_filepath):
        data = open(abs_filepath, "r").read()
        return hashlib.md5(data).hexdigest()

    def DriveInfo(self):
        return self.Drive.Account

    def PathLeaf(self, path):
        head, tail = ntpath.split(path)
        return tail or ntpath.basename(head)


    def CreateDirectoryInParent(self, dirname, parent_id='root'):
        file_metadata = {'name': dirname,
                        'mimeType':'application/vnd.google-apps.folder'}
        file_metadata['parents'] = [parent_id]
        upfile = self.Drive.Session.files().create(body=file_metadata, fields='id').execute()
        self.logger.debug("create directory: %s in root\n" % dirname)

    def CreateDirectoryByPath(self, dirpath):
        self.logger.debug("create directory: %s\n" % dirpath)
        drivepath = dirpath.split(self.configs.user_mirror_directory+'/')[1]
        basepath = os.path.dirname(drivepath)
        dirname = self.PathLeaf(dirpath)

        try:
            f = self.LocateFolderOnDrive(drivepath)
            return
        except FolderNotFound:
            if basepath == '':
                self.CreateDirectoryInParent(dirname)
            else:
                try:
                    parent_folder = self.LocateFolderOnDrive(basepath)
                    self.CreateDirectoryInParent(dirname, parent_folder['id'])
                except:
                    errorMsg = "Failed to locate directory path %s on drive.\n" % basepath
                    self.logger.error(errorMsg)
                    dial = wx.MessageDialog(None, errorMsg, 'Directory Not Found',
                                            wx.ID_OK | wx.ICON_EXCLAMATION)
                    dial.ShowModal()
                    return
        except FileListQueryFailed:
            errorMsg = "Server Query Failed!\n"
            self.logger.error(errorMsg)
            dial = wx.MessageDialog(None, errorMsg, 'Directory Not Found',
                                    wx.ID_OK | wx.ICON_EXCLAMATION)
            dial.ShowModal()
            return

    def CreateRegularFile(self, file_path, parent='root', uploaded=False):
        self.logger.debug("Create file %s\n" % file_path)
        filename = self.PathLeaf(file_path)
        file_metadata = {'name': filename}
        file_metadata['parents'] = [parent]
        media = MediaFileUpload(file_path, resumable=True)
        upfile = self.Drive.Session.files().create(body=file_metadata,
                                    media_body=media,
                                    fields='id').execute()
    def UploadFile(self, file_path):
        if os.path.isfile(file_path):
            drivepath = file_path.split(self.configs.user_mirror_directory+'/')[1]
            self.logger.debug("file: %s drivepath is %s\n" % (file_path, drivepath))
            try:
                f = self.LocateFileOnDrive(drivepath)
#Migration V3 API
#                self.logger.debug('Found file %s on remote (dpath: %s)\n' % (f['title'], drivepath))
                self.logger.debug('Found file %s on remote (dpath: %s)\n' % (f['name'], drivepath))
                newfile = False
                self.logger.debug('Checking if they are same... ')
                if f['md5Checksum'] == self.HashOfFile(file_path):
                    self.logger.debug('yes\n')
                    return
                else:
                    self.logger.debug('no\n')
            except (FileNotFound, FolderNotFound):	
                self.logger.debug("A new file!\n")
                newfile = True

            dirpath = os.path.dirname(drivepath)
            if dirpath == '':
                self.logger.debug('Creating %s file in root\n' % file_path)
                self.CreateRegularFile(file_path, 'root', newfile)
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_UPDATE, {'UpLoading %s' % file_path})
            else:
                try:
                    f = self.LocateFolderOnDrive(dirpath)
                    self.CreateRegularFile(file_path, f['id'], newfile)
                except FolderNotFound:
                    # We are coming from premise that upload comes as part
                    # of observer. So before notification of this file's
                    # creation happens, a notification of its parent directory
                    # must have come first.
                    # So,
                    # Folder not found? That cannot happen. Can it?
                    raise RegularFileUploadFailed()
        else:
            self.CreateDirectoryByPath(file_path)

    def UploadObservedFile(self, file_path):
        self.sync_lock.acquire()
        self.UploadFile(file_path)
        self.sync_lock.release()
##        GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_UPDATE, {''})

    def RenameFile(self, file_object, new_title):
        try:
            file = {'name': new_title}

            updated_file = self.Drive.Session.files().update( body= file,
                                                         fileId=file_object['id'],
                                                         fields='id, appProperties').execute()
            return updated_file
        except errors.HttpError, error:
            self.logger.error('An error occurred while renaming file: %s' % error)
            return None
        except:
            self.logger.exception('An unknown error occurred file renaming file\n')
            return None

    def RenameObservedFile(self, file_path, new_name):
        self.sync_lock.acquire()
        drive_path = file_path.split(self.configs.user_mirror_directory+'/')[1]
        self.logger.debug("RenameObservedFile: Rename %s to new name %s\n"
                          % (file_path, new_name))
        try:
            ftd = self.LocateFileOnDrive(drive_path)
            nftd = self.RenameFile(ftd, new_name)
            if not nftd:
                self.logger.error("File rename failed\n")
        except:
            self.logger.exception("Could not locate file on drive.\n")

        self.sync_lock.release()

    def TrashFile(self, file_object):
        try:
            file_metadata = {'trashed':True}
            self.Drive.Session.files().update(body=file_metadata,fileId=file_object['id']).execute()
            self.logger.info({"TRASH_FILE: File %s deleted successfully.\n" % file_object['name']})
        except errors.HttpError, error:
            self.logger.error("TRASH_FILE: HTTP Error\n")
            raise RegularFileTrashFailed()

    def TrashObservedFile(self, file_path):
        self.sync_lock.acquire()
        drive_path = file_path.split(self.configs.user_mirror_directory+'/')[1]
        self.logger.debug({"TRASH_FILE: dirpath to delete: %s\n" % drive_path})
        try:
            ftd = self.LocateFileOnDrive(drive_path)
            try:
                self.TrashFile(ftd)
            except RegularFileTrashFailed:
                self.logger.error({"TRASH_FILE: Failed to move file %s to trash\n" % drive_path})
                raise
            except:
                raise
        except (FileNotFound, FileListQueryFailed, FolderNotFound):
            self.logger.error({"TRASH_FILE: Failed to locate %s file on drive\n" % drive_path})
            pass

        self.sync_lock.release()

    def MoveFile(self, src_file, dst_folder='root', src_folder='root'):
        try:
            if dst_folder != 'root':
                did = dst_folder['id']
            else:
                did = 'root'

            if src_folder != 'root':
                sid = src_folder['id']
            else:
                sid = 'root'

            updated_file = self.Drive.Session.files().update(fileId=src_file['id'],
                                    addParents=did,
                                    removeParents=sid,
                                    fields='id, parents').execute()

        except:
            self.logger.exception("move failed\n")

    def MoveObservedFile(self, src_path, dest_path):
	from_drive_path = src_path.split(self.configs.user_mirror_directory+'/')[1]
	to_drive_path = os.path.dirname(dest_path.split(self.configs.user_mirror_directory+'/')[1])

        self.logger.debug("Moving file %s to %s\n" % (from_drive_path, to_drive_path))

	try:
	    ftm = self.LocateFileOnDrive(from_drive_path)
            self.logger.debug("MoveObservedFile: Found source file on drive\n")
            if os.path.dirname(from_drive_path) == '':
                sf = 'root'
            else:
                sf = self.LocateFolderOnDrive(os.path.dirname(from_drive_path))
            self.logger.debug("MoveObservedFile: Found source folder on drive\n")
            try:
                if to_drive_path == '':
                    df = 'root'
                else:
                    df = self.LocateFolderOnDrive(to_drive_path)
                self.logger.debug("MoveObservedFile: Found destination folder on drive\n")
                try:
                    self.logger.debug("MovingFile() ")
                    self.MoveFile(ftm, df, sf)
                    self.logger.debug("done\n")
                except (Unkownerror, FileMoveFailed):
                    self.logger.error("MovedObservedFile: Failed\n")
                    return
                except:
                    self.logger.error("?????\n")
                    return
            except FolderNotFound:
                self.logger.error("MoveObservedFile: Couldn't locate destination folder on drive.\n")
                return
            except:
                self.logger.error("MoveObservedFile: Unknown error while locating destination folder on drive.\n")
                return
	except FileNotFound:
            self.logger.error("MoveObservedFile: Couldn't locate file on drive.\n")
            return
	except FileListQueryFailed:
	    self.logger.error("MoveObservedFile: File Query failed. aborting.\n")
	    return
	except FolderNotFound:
	    self.logger.error("MoveObservedFile: Folder not found\n")
	    return
	except:
	    self.logger.error("MoveObservedFile: Unknown error while moving file.\n")
	    return

    def HandleMovedFile(self, src_path, dest_path):
        drive_path1 = os.path.dirname(src_path.split(self.configs.user_mirror_directory+'/')[1])
	drive_path2 = os.path.dirname(dest_path.split(self.configs.user_mirror_directory+'/')[1])

	if drive_path1 == drive_path2:
            self.logger.debug("Rename file\n")
	    self.RenameObservedFile(src_path, self.PathLeaf(dest_path))
	else:
            self.logger.debug("Move file\n")
	    self.MoveObservedFile(src_path, dest_path)

    #################################################
    ####### DOWNLOAD SECTION (Syncing local) #######
    #################################################


#### LocateFileInFolder
    def LocateFileInFolder(self, filename, parent='root'):
        try:
            file_list = self.MakeFileListQuery("'%s' in parents and trashed=false" % parent)
            for f in file_list:
                if f['name'] == filename:
                    return f

            raise FileNotFound()
        except:
            raise FileNotFound()

#### LocateFileOnDrive
    def LocateFileOnDrive(self, abs_filepath):
        dirpath = os.path.dirname(abs_filepath)
        filename = self.PathLeaf(abs_filepath)

        if dirpath != '':
            try:
                f = self.LocateFolderOnDrive(dirpath)
                try:
                    fil = self.LocateFileInFolder(filename, f['id'])
                    return fil
                except FileNotFound:
                    self.logger.debug("LocateFileOnDrive: Local File (%s) not in remote." % filename)
                    raise
                except FileListQueryFailed:
                    self.logger.debug("LocateFileOnDrive: Locate File (%s) list query failed" % filename)
                    raise
            except FolderNotFound:
                self.logger.debug("LocateFileOnDrive: Local Folder (%s) not in remote" % dirpath)
                raise
            except FileListQueryFailed:
                self.logger.debug("LocateFileOnDrive: Locate Folder (%s) list query failed" % dirpath)
                raise
        else:
            try:
                fil = self.LocateFileInFolder(filename)
                return fil
            except FileNotFound:
                self.logger.debug("LocateFileOnDrive: Local File (%s) not in remote." % filename)
                raise
            except FileListQueryFailed:
                self.logger.debug("LocateFileOnDrive: File (%s) list query failed." % filename)
                raise
            except:
                self.logger.error("LocateFileOnDrive: Unknown error in locating file (%s) in local folder (root)" % filename)
                raise

#### LocateFolderOnDrive
    def LocateFolderOnDrive(self, folder_path):
        """
        Locate and return the directory in the path. The complete path
        is walked and the last directory is returned. An exception is raised
        if the path walking fails at any stage.
        """
        dir_list = folder_path.split(os.sep)
        croot = 'root'
        for dir1 in dir_list:
            try:
                folder = self.GetFolderOnDrive(dir1, croot)
                if not folder:
                    raise FolderNotFound()
            except:
                raise

            croot = folder['id']

        return folder

#### GetFolderOnDrive
    def GetFolderOnDrive(self, folder_name, parent='root'):
        """
        Return the folder with name in "folder_name" in the parent folder
        mentioned in parent.
        """
        self.logger.debug("GetFolderOnDrive: Checking Folder (%s) on (%s)" % (folder_name, parent))
        file_list = self.MakeFileListQuery("'%s' in parents and trashed=false"  % parent)
        for f in file_list:
            if f['name'] == folder_name and f['mimeType']=='application/vnd.google-apps.folder':
                self.logger.info("GetFolderOnDrive: Found Folder (%s) on (%s)" % (folder_name, parent))
                return f

        return None

#### SyncLocalDirectory
    def SyncLocalDirectory(self):
        self.logger.info("### SyncLocalDirectory: - Sync Started")
        for root, dirs, files in os.walk(self.configs.user_mirror_directory):
            for names in files:
                try:
                    dirpath = os.path.join(root, names)
                    drivepath = dirpath.split(self.configs.user_mirror_directory+'/')[1]
                    self.logger.debug("SyncLocalDirectory: Checking Local File (%s)" % drivepath)
                    f = self.LocateFileOnDrive(drivepath)
                    self.logger.info("SyncLocalDirectory: Skipping Local File (%s) same as Remote\n" % dirpath)
                except FileListQueryFailed:
                    # if the file list query failed, we can't delete the local file even if
                    # its gone in remote drive. Let the next sync come and take care of this
                    # Log the event though
                    self.logger.info("SyncLocalDirectory: Remote File (%s) Check Failed. Aborting.\n" % dirpath)
                    return
                except:
                    if os.path.exists(dirpath) and os.path.isfile(dirpath):
                        self.logger.info("SyncLocalDirectory: Deleting Local File (%s) - Not in Remote\n" % dirpath)
                        os.remove(dirpath)

            for names in dirs:
                try:
                    dirpath = os.path.join(root, names)
                    drivepath = dirpath.split(self.configs.user_mirror_directory+'/')[1]
                    f = self.LocateFileOnDrive(drivepath)
                except FileListQueryFailed:
                    # if the file list query failed, we can't delete the local file even if
                    # its gone in remote drive. Let the next sync come and take care of this
                    # Log the event though
                    self.logger.info("SyncLocalDirectory: Remote Folder (%s) Check Failed. Aborting.\n" % dirpath)
                    return
                except:
                    if os.path.exists(dirpath) and os.path.isdir(dirpath):
                        self.logger.info("SyncLocalDirectory: Deleting Local Folder (%s) - Not in Remote\n" % dirpath)
                        #to delete none empty directory recursively
#                        os.remove(dirpath)
                        shutil.rmtree(dirpath, ignore_errors=False, onerror=None)
        self.logger.info("### SyncLocalDirectory: - Sync Completed")


    #################################################
    ####### DOWNLOAD SECTION (Syncing remote) #######
    #################################################


    def MakeFileListQuery(self, query):
        try:
            page_token = None
            filelist = []
            while True:
                response = self.Drive.Session.files().list(q=query,
                                      spaces='drive',
                                      fields='nextPageToken, files(id, name, mimeType, size, md5Checksum)',
                                      pageToken=page_token).execute()
                filelist.extend(response.get('files',[]))
                page_token = response.get('nextPageToken', None)
                if page_token is None:
                    break
            return filelist
        except HttpError as error:
            if error.resp.reason in ['userRateLimitExceeded', 'quotaExceeded']:
                self.logger.error("MakeFileListQuery: User Rate Limit/Quota Exceeded. Will try later\n")
#            time.sleep((2**n) + random.random())
        except:
            self.logger.error("MakeFileListQuery: failed with reason %s\n" % error.resp.reason)
#        time.sleep((2**n) + random.random())
#    self.logger.error("Can't get the connection back after many retries. Bailing out\n")
        raise FileListQueryFailed

    def TotalFilesInFolder(self, parent='root'):
        file_count = 0
        try:
            file_list = self.MakeFileListQuery("'%s' in parents and trashed=false"  % parent)
            for f in file_list:
                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    file_count += self.TotalFilesInFolder(f['id'])
                    file_count += 1
                else:
                    file_count += 1

            return file_count
        except:
            raise

    def IsGoogleDocument(self, f):
        if any(f['mimeType'] in s for s in google_docs_mimelist):
            return True
        else:
            return False

    def TotalFilesInDrive(self):
        return self.TotalFilesInFolder()

#### DownloadFileByObject
    def DownloadFileByObject(self, file_obj, download_path):
        abs_filepath = os.path.join(download_path, file_obj['name'])
        if os.path.exists(abs_filepath):
            if self.HashOfFile(abs_filepath) == file_obj['md5Checksum']:
                self.logger.info('DownloadFileByObject: Skipping File (%s) - same as remote.\n' % abs_filepath)
                return
            else:
                self.logger.info("DownloadFileByObject: Skipping File (%s) - Local and Remote - Same Name but Different Content.\n" % abs_filepath)
        else:
            self.logger.debug('DownloadFileByObject: Download Started - File (%s)' % abs_filepath)
            fd = abs_filepath.split(self.configs.user_mirror_directory+'/')[1]
            GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_UPDATE,
                                              {'Downloading %s' % fd})
            request = self.Drive.Session.files().get_media(fileId=file_obj['id'])
            fh = io.FileIO(abs_filepath, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()            
            fh.close()
            self.updates_done = 1
            self.logger.info('DownloadFileByObject: Download Completed - File (%s)\n' % abs_filepath)

#### SyncRemoteDirectory
    def SyncRemoteDirectory(self, parent, pwd, recursive=True):
        self.logger.info("### SyncRemoteDirectory: - Sync Started - Remote Directory (%s) ... Recursive = %s\n" % (pwd, recursive))
        if not self.syncRunning.is_set():
            self.logger.debug("SyncRemoteDirectory: Sync has been paused. Aborting.\n")
            return

        if not os.path.exists(os.path.join(self.configs.user_mirror_directory, pwd)):
            os.makedirs(os.path.join(self.configs.user_mirror_directory, pwd))

        try:
            file_list = self.MakeFileListQuery("'%s' in parents and trashed=false" % parent)
            for f in file_list:
                if not self.syncRunning.is_set():
                    self.logger.debug("SyncRemoteDirectory: Sync has been paused. Aborting.\n")
                    return

                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    if not recursive:
                        continue

                    abs_dirpath = os.path.join(self.configs.user_mirror_directory, pwd, f['name'])
                    self.logger.debug("SyncRemoteDirectory: Checking directory (%s)" % f['name'])
                    if not os.path.exists(abs_dirpath):
                        self.logger.debug("SyncRemoteDirectory: Creating directory (%s)" % abs_dirpath)
                        os.makedirs(abs_dirpath)
                        self.logger.debug("SyncRemoteDirectory: Created directory (%s)" % abs_dirpath)
                    self.logger.debug("SyncRemoteDirectory: Syncing directory (%s)\n" % f['name'])
                    self.SyncRemoteDirectory(f['id'], os.path.join(pwd, f['name']))
                    if not self.syncRunning.is_set():
                        self.logger.debug("SyncRemoteDirectory: Sync has been paused. Aborting.\n")
                        return
                else:
                    self.logger.debug("SyncRemoteDirectory: Checking file (%s)" % f['name'])
                    if not self.IsGoogleDocument(f):
                        self.DownloadFileByObject(f, os.path.join(self.configs.user_mirror_directory, pwd))
                    else:
                        self.logger.info("SyncRemoteDirectory: Skipping file (%s) is a google document.\n" % f['name'])
        except:
            self.logger.error("SyncRemoteDirectory: Failed to sync directory (%s)" % f['name'])
            raise
        self.logger.info("### SyncRemoteDirectory: - Sync Completed - Remote Directory (%s) ... Recursive = %s\n" % (pwd, recursive))

#### validate_sync_settings
    def validate_sync_settings(self):
        for d in self.configs.sync_selection:
            if d[0] != 'root':
                try:
                    f = self.LocateFolderOnDrive(d[0])
                    if f['id'] != d[1]:
                        raise FolderNotFound()
                    break
                except FolderNotFound:
                    raise
                except:
                    raise FolderNotFound()
            else:
                if d[1] != '':
                    raise FolderNotFound()

#### run (Sync Local and Remote Directory)
    def run(self):
        while True:
            self.syncRunning.wait()

            self.sync_lock.acquire()

            try:
                self.validate_sync_settings()
            except:
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_INV_FOLDER, 0)
                self.syncRunning.clear()
                self.sync_lock.release()
                continue

            try:
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_STARTED, None)
                # test class sync
#                self.page_token = self.sync_download.SyncNow(self.page_token)
#                self.logger.debug("Synchronize - Completed first Loop")
                #
                self.logger.info("###############################################")
                self.logger.info("Start - Syncing remote directory")
                self.logger.info("###############################################")
                for d in self.configs.sync_selection:
                    if d[0] != 'root':
                        #Root folder files are always synced (not recursive)
                        self.SyncRemoteDirectory('root', '', False)
                        #Then sync current folder (recursively)
                        self.SyncRemoteDirectory(d[1], d[0])
                    else:
                        #Sync Root folder (recursively)
                        self.SyncRemoteDirectory('root', '')
                self.logger.info("###############################################")
                self.logger.info("End - Syncing remote directory")
                self.logger.info("###############################################\n")
                self.logger.info("###############################################")
                self.logger.info("Start - Syncing local directory")
                self.logger.info("###############################################")
                self.SyncLocalDirectory()
                self.logger.info("###############################################")
                self.logger.info("End - Syncing local directory")
                self.logger.info("###############################################\n")
                if self.updates_done:
                    self.usageCalculateEvent.set()
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_DONE, 0)
            except:
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_DONE, -1)

            self.sync_lock.release()
            self.time_left = 600
#
#todo to review time to wait
            self.time_left = 600

            while (self.time_left):
                GoSyncEventController().PostEvent(GOSYNC_EVENT_SYNC_TIMER,
                                                  {'Sync starts in %02dm:%02ds' % ((self.time_left/60), (self.time_left % 60))})
                self.time_left -= 1
                self.syncRunning.wait()
                time.sleep(1)

#### GetFileSize
    def GetFileSize(self, f):
        try:
            size = f['size']
            return long(size)
        except:
            self.logger.error("Failed to get size of file %s (mime: %s)\n" % (f['name'], f['mimeType']))
            return 0

#### calculateUsageOfFolder
    def calculateUsageOfFolder(self, folder_id):
        driveAudioUsage = 0
        drivePhotoUsage = 0
        driveMoviesUsage = 0
        driveDocumentUsage = 0
        driveOthersUsage = 0
        try:
            file_list = self.MakeFileListQuery("'%s' in parents and trashed=false" % folder_id)
            for f in file_list:
                self.fcount += 1
                GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_UPDATE, self.fcount)
                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    self.configs.driveTree.AddFolder(folder_id, f['id'], f['name'], f)
                    self.calculateUsageOfFolder(f['id'])
                else:
                    if not self.IsGoogleDocument(f):
                        if any(f['mimeType'] in s for s in audio_file_mimelist):
                            driveAudioUsage += self.GetFileSize(f)
                        elif  any(f['mimeType'] in s for s in image_file_mimelist):
                            drivePhotoUsage += self.GetFileSize(f)
                        elif any(f['mimeType'] in s for s in movie_file_mimelist):
                            driveMoviesUsage += self.GetFileSize(f)
                        elif any(f['mimeType'] in s for s in document_file_mimelist):
                            driveDocumentUsage += self.GetFileSize(f)
                        else:
                            driveOthersUsage += self.GetFileSize(f)

        except:
            raise
        self.Drive.Usage['Audio Size'] = driveAudioUsage
        self.Drive.Usage['Photo Size'] = drivePhotoUsage
        self.Drive.Usage['Movies Size'] = driveMoviesUsage
        self.Drive.Usage['Document Size'] = driveDocumentUsage
        self.Drive.Usage['Others Size'] = driveOthersUsage

#### calculateUsage
    def calculateUsage(self):
        self.logger.debug("Started Folder Usage Calculation")
        while True:
            self.usageCalculateEvent.wait()
            self.usageCalculateEvent.clear()

            self.sync_lock.acquire()
            if self.configs.drive_usage_dict and not self.updates_done:
                GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_DONE, 0)
                self.sync_lock.release()
                continue
            
            self.logger.debug("Entered in Folder Usage Calculation")
            self.updates_done = 0
            self.calculatingDriveUsage = True
            self.Drive.ResetUsage()
            self.fcount = 0
            try:
                self.Drive.Usage['Total Files'] = self.TotalFilesInDrive()
                self.logger.info("Total files to check %d\n" % self.Drive.Usage['Total Files'])
                GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_STARTED, self.Drive.Usage['Total Files'])
                try:
                    self.calculateUsageOfFolder('root')
                    GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_DONE, 0)
                    self.Drive.Usage['Total Size'] = long(self.Drive.Account['storageQuota']['limit'])
                    self.configs.drive_usage_dict = self.Drive.Usage
                    pickle.dump(self.configs.driveTree, open(self.configs.tree_pickle_file, "wb"))
                    self.configs.config_dict['Drive Usage'] = self.configs.drive_usage_dict
                    self.configs.SaveConfigFile()
                except:
                    self.Drive.ResetUsage()
                    GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_DONE, -1)
                    self.logger.error("Failed Folder Usage Calculation\n")
            except:
                GoSyncEventController().PostEvent(GOSYNC_EVENT_CALCULATE_USAGE_DONE, -1)
                self.logger.error("Failed to get the total number of files in drive\n")

            self.calculatingDriveUsage = False
            self.sync_lock.release()
            self.logger.debug("Completed Folder Usage Calculation")

    def GetDriveDirectoryTree(self):
        self.sync_lock.acquire()
        ref_tree = copy.deepcopy(self.configs.driveTree)
        self.sync_lock.release()
        return ref_tree

    def IsCalculatingDriveUsage(self):
        return self.calculatingDriveUsage

    def StartSync(self):
        self.syncRunning.set()

    def StopSync(self):
        self.syncRunning.clear()

    def IsSyncEnabled(self):
        return self.syncRunning.is_set()

    def SetSyncSelection(self, folder):
        if folder == 'root':
            self.configs.sync_selection = [['root', '']]
        else:
            for d in self.configs.sync_selection:
                if d[0] == 'root':
                    self.configs.sync_selection = []
            for d in self.configs.sync_selection:
                if d[0] == folder.GetPath() and d[1] == folder.GetId():
                    return
            self.configs.sync_selection.append([folder.GetPath(), folder.GetId()])
        self.configs.config_dict['Sync Selection'] = self.configs.sync_selection
        self.configs.SaveConfigFile()

    def GetSyncList(self):
        return copy.deepcopy(self.configs.sync_selection)

class FileModificationNotifyHandler(PatternMatchingEventHandler):
    patterns = ["*"]

    def __init__(self, sync_handler):
        super(FileModificationNotifyHandler, self).__init__()
        self.sync_handler = sync_handler

    def on_created(self, evt):
        self.sync_handler.logger.debug("Observer: %s created\n" % evt.src_path)
        self.sync_handler.UploadObservedFile(evt.src_path)

    def on_moved(self, evt):
        self.sync_handler.logger.info("Observer: file %s moved to %s: Not supported yet!\n" % (evt.src_path, evt.dest_path))
        self.sync_handler.HandleMovedFile(evt.src_path, evt.dest_path)

    def on_deleted(self, evt):
        self.sync_handler.logger.info("Observer: file %s deleted on drive.\n" % evt.src_path)
        self.sync_handler.TrashObservedFile(evt.src_path)