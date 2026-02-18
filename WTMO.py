#!/usr/bin/env python3
#
"""
Universal Mod Organizer Framework
A desktop application for organizing game mods with embedded web portal and exportable/importable modlists
"""

'''descriptions and notes'''
"""Info or improper notes..."""
#quick info and additional functions

import sys
import os
import json
import re
import zipfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QFrame, QSplitter, QScrollArea,
    QTextEdit, QProgressBar, QCheckBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont, QIcon
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

import requests
'''This Mod Organizer is a variant of the Universal Mod Organizer Framework, this variant is for: War Thunder'''
'''If you are a dev, please note that you may need to git pull PyQt6 when developmenting a fork of existing Mod Organizers'''
'''If you are a dev, please refer to the example organizers for War Thunder, Star Wars Battlefront 2 and Red Alert 3, for code references and starting points to build off of. Additionally refer to the github page for tutorials on getting started or what chunks to cutout/keep when making radical changes within the framework.'''
'''If you are a user and you either do not see this text or you paid for access to the Mod Organizer, you have been scammed, all information and example organizers exist for free for the benefit of the gaming community. Anyone who attempts to place a fork, variant, derivative or copy of this mod organizer or it's forks, variants, derivatives or copies, behind a paywall or requires purchasing of a key for use, is scamming you.'''
'''The Framework is built with the AI assistance of: note the following - ChatGPT 5, Qwen 3.0, Minimax 2.1, please bear in mind that current models cannot do all of the coding and bug testing for you, you will need to find solutions in existing example code, through trial and error or by asking the Python community. Current models can help you, just don't rely too heavily on them.'''
'''The Framework is built with the assistance of a long list of members of the Python Community, a list that continues to expand by the day. if interested in learning Python, a comfortable place to start is: https://www.reddit.com/r/learnpython/ and https://www.reddit.com/r/Python/. Some of the earliest mentions of the Framework and an early test setup can be found on these forums'''
'''Special thanks to dnbhladdict on Reddit for advising me to modify my def run chunk and making me recheck how missions are handled (or not handled) in my def unpack chunk which lead to several major fixes and the removal of mishandled mass loose file downloads. Thank you.'''

class DownloadThread(QThread):
    """Thread for downloading mods without blocking the UI.""" '''UI getting freaky was an issue in an older test setup'''
    progress = pyqtSignal(str, int, int)  # mod_name, current, total
    finished_download = pyqtSignal(str, bool, str)  # url, success, message
    all_done = pyqtSignal()

    def __init__(self, mods: List[Dict], root_folder: str):
        super().__init__()
        self.mods = mods  # [{url, target, category}]
        self.root_folder = root_folder
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        for i, mod in enumerate(self.mods):
            if self._is_cancelled:
                break
            url = mod['url']
            target_folder = mod.get('target', self.root_folder)
            category = mod.get('category')
            
            try:
                self.progress.emit(f"Downloading {i+1}/{len(self.mods)}", i, len(self.mods))
                response = requests.get(url, stream=True, timeout=60)
                response.raise_for_status()
                
                # Get filename from headers or URL
                filename = self._get_filename(response, url)
                filepath = os.path.join(target_folder, filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            break
                        f.write(chunk)
                
                # Try to unpack if it's an archive
                if filepath.endswith(('.zip', '.rar', '.7z')):
                    self._unpack_archive(filepath, target_folder, category)

                elif filepath.endswith('.blk') and category == 'mission':
                    missions_dir = Path(self.root_folder) / "UserMissions"
                    missions_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(filepath, missions_dir / os.path.basename(filepath))
                    
                self.finished_download.emit(url, True, f"Downloaded: {filename}")
            except Exception as e:
                self.finished_download.emit(url, False, str(e))
        
        self.all_done.emit()

    def _get_filename(self, response, url: str) -> str:
        cd = response.headers.get('content-disposition', '')
        filename = None
        
        if cd and 'filename=' in cd:
            # Extract value after 'filename='
            raw_name = cd.split('filename=')[1]
            
            # Handle parameters that might follow (e.g., filename="name.zip"; size=123)
            if ';' in raw_name:
                raw_name = raw_name.split(';')[0]
                
            # Clean quotes and whitespace
            filename = raw_name.strip().strip('"\'')
            
            # Decode URL encoding if present (e.g., UTF-8''filename.zip)
            if filename:
                filename = unquote(filename)

        # 2. Validate Header Filename
        # If header exists but is generic, then fall through to URL parsing
        if filename and filename != 'mod_download.zip':
            return filename

        # 3. Fallback to the Actual Downloaded URL (response.url) 
        final_url = response.url if hasattr(response, 'url') else url
        parsed_path = urlparse(final_url).path
        url_filename = os.path.basename(parsed_path)

        # 4. Parse File Type and Name from URL
        if url_filename:
            if '?' in url_filename:
                url_filename = url_filename.split('?')[0]
                
            if url_filename.endswith('.blk'):
                return url_filename
            # Return whatever extension was found (.zip, .rar, etc.)
            return url_filename

        # 5. Final Fallback
        return 'mod_download.zip'

    '''The unpack_archive system works by filtering mods by category AND by checking for file structure in their .zip files. This means mods with 
    loose .dds texture files get automatically placed inside of a folder rather than spilling out into the main UserSkins folder and it means that 
    the .blk's are found inside of zipped sight mods and placed in the all tanks folder though that will change as needed to match the best general 
    location for sights to be delivered. I will detail how to change this later on, use control+F and search for "all_tanks_change".'''

    def _unpack_archive(self, filepath: str, target_folder: str, category: Optional[str] = None):
        try:
            if filepath.endswith('.zip'):
                with zipfile.ZipFile(filepath, 'r') as zf:
                    # Get all file paths in the zip (excluding directory entries)
                    namelist = [name for name in zf.namelist() if not name.endswith('/')]
                    
                    if not namelist:
                        return False  # Empty zip

                    # Default extraction destination
                    extract_to = target_folder

                    # --- ONLY inspect structure for 'camo' category ---
                    if category == 'camouflage':
                        # Check if there's a folder structure inside
                        # If ANY file contains a '/', it implies a folder structure exists
                        has_folder_structure = any('/' in name for name in namelist)
                            
                        if not has_folder_structure:
                        # No folder structure: Create a folder based on zip filename
                            zip_name = os.path.splitext(os.path.basename(filepath))[0]
                            extract_to = os.path.join(target_folder, zip_name)
                            os.makedirs(extract_to, exist_ok=True)
                    # -------------------------------------------------

                    # Extract files based on category rules
                    if category == 'sight':
                        # For sights, extract only .blk files to the determined destination
                        for file_info in namelist:
                            if file_info.endswith('.blk'):
                                zf.extract(file_info, extract_to)
                    else:
                        # For camo (and others), extract all files to the determined destination
                        zf.extractall(extract_to)
                
                # Delete the zip after successful extraction
                os.remove(filepath)
                return True
                
            elif filepath.endswith('.rar'):
                # Handle rar if needed
                return True
                
        except Exception as e:
            # Keep the archive if unpacking fails (for debugging)
            print(f"Extraction failed, keeping archive: {e}")
            return False
        
        return False


'''current href reference, expandable as needed'''
class ModWebPage(QWebEnginePage):
    """Custom web page to handle download link detection."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Patterns for different mod sites
        self.download_patterns = [
            r'href=["\']?(https?://live\.warthunder\.com/dl/[^"\'>\s]+)',
            r'href=["\']?(/downloads/start/\d+)',
            r'href=["\']?(https?://[^"\'>\s]*download[^"\'>\s]*)',
        ]


# Category constants
CATEGORY_CAMO = "camouflage"
CATEGORY_MISSION = "mission"
CATEGORY_SIGHT = "sight"
VALID_CATEGORIES = {CATEGORY_CAMO, CATEGORY_MISSION, CATEGORY_SIGHT}


class ModOrganizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root_folder = ""  # Game root folder
        self.production_folder = ""  # Production folder for sights
        self.mod_list: List[Dict] = []  # [{url, name, checked, category}]
        self.master_list: List[str] = []
        self.download_thread: Optional[DownloadThread] = None
        self.has_sight_mods = False  # Track if sights were downloaded

        # Mod folder paths (set after root folder selection)
        self.user_skins_folder = ""
        self.user_missions_folder = ""
        self.user_sights_folder = ""
        self.all_tanks_folder = ""
        
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("War Thunder Mod Organizer")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # === TOP BAR ===
        top_bar = QHBoxLayout()
        
        self.btn_find_root = QPushButton("Find Root Folder")
        self.btn_find_root.setFixedHeight(35)
        self.btn_find_root.clicked.connect(self.find_root_folder)
        
        self.btn_export = QPushButton("Export")
        self.btn_export.setFixedHeight(35)
        self.btn_export.clicked.connect(self.export_modlist)
        
        self.btn_import = QPushButton("Import")
        self.btn_import.setFixedHeight(35)
        self.btn_import.clicked.connect(self.import_modlist)
        
        self.lbl_root_path = QLabel("No folder selected")
        self.lbl_root_path.setStyleSheet("color: gray; font-style: italic;")
        
        top_bar.addWidget(self.btn_find_root)
        top_bar.addWidget(self.btn_export)
        top_bar.addWidget(self.btn_import)
        top_bar.addWidget(self.lbl_root_path, 1)
        
        main_layout.addLayout(top_bar)
        ''' A small, now intentional issue, exists where the portal is smaller than it could be, this causes it to look slightly 
        off without harming function and entices investigation which will result in users learning they can move/hide the tabs '''
        # === MAIN CONTENT AREA ===
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # -- LEFT PANEL --
        left_panel = QWidget()
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        
        # Game Logo area
        self.logo_frame = QFrame()
        self.logo_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.logo_frame.setMinimumHeight(150)
        logo_layout = QVBoxLayout(self.logo_frame)
        self.logo_label = QLabel("Game Logo\nor Donation - exists for images or QR codes, no text")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setWordWrap(True)
        logo_layout.addWidget(self.logo_label)
        
        # Donation/Tools area
        self.tools_frame = QFrame()
        self.tools_frame.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        tools_layout = QVBoxLayout(self.tools_frame)
        self.tools_text = QTextEdit()
        self.tools_text.setPlaceholderText("Donation links, guides,\nor other tools... exists for text information, no images")
        self.tools_text.setReadOnly(True)
        tools_layout.addWidget(self.tools_text)
        
        left_layout.addWidget(self.logo_frame, 1)
        left_layout.addWidget(self.tools_frame, 2)
        
        # -- CENTER PANEL (Web Portal) --
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(5)
        
        # URL bar
        url_bar = QHBoxLayout()
        self.url_label = QLabel("URL:")
        from PyQt6.QtWidgets import QLineEdit
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://live.warthunder.com/feed/all/")
        self.url_input.returnPressed.connect(self.navigate_to_url)
        self.btn_go = QPushButton("Go")
        self.btn_go.clicked.connect(self.navigate_to_url)
        self.btn_add_mod = QPushButton("+ Add Mod")
        self.btn_add_mod.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_add_mod.clicked.connect(self.add_mod_from_page)
        
        url_bar.addWidget(self.url_label)
        url_bar.addWidget(self.url_input, 1)
        url_bar.addWidget(self.btn_go)
        url_bar.addWidget(self.btn_add_mod)
        
        center_layout.addLayout(url_bar)
        
        # Web View
        self.web_view = QWebEngineView()
        self.web_page = ModWebPage(self.web_view)
        self.web_view.setPage(self.web_page)
        self.web_view.setUrl(QUrl("https://live.warthunder.com/feed/all/"))
        self.web_view.urlChanged.connect(lambda url: self.url_input.setText(url.toString()))
        center_layout.addWidget(self.web_view, 1)
        
        # -- RIGHT PANEL (Download List) --
        right_panel = QWidget()
        right_panel.setFixedWidth(280)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        
        right_label = QLabel("Download List and Checklist")
        right_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.mod_listwidget = QListWidget()
        self.mod_listwidget.setAlternatingRowColors(True)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        right_layout.addWidget(right_label)
        right_layout.addWidget(self.mod_listwidget, 1)
        right_layout.addWidget(self.progress_bar)
        
        # Add panels to splitter
        content_splitter.addWidget(left_panel)
        content_splitter.addWidget(center_panel)
        content_splitter.addWidget(right_panel)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setStretchFactor(2, 0)
        
        main_layout.addWidget(content_splitter, 1)

        # === BOTTOM BAR ===
        bottom_bar = QHBoxLayout()
        
        self.btn_show_modlist = QPushButton("Show Full Modlist")
        self.btn_show_modlist.clicked.connect(self.show_full_modlist)
        
        self.btn_cancel = QPushButton("Cancel/Clear List")
        self.btn_cancel.setStyleSheet("background-color: #f44336; color: white;")
        self.btn_cancel.clicked.connect(self.cancel_clear_list)
        
        self.btn_download_all = QPushButton("Download All")
        self.btn_download_all.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.btn_download_all.clicked.connect(self.download_all)
        
        bottom_bar.addWidget(self.btn_show_modlist)
        bottom_bar.addWidget(self.btn_cancel)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_download_all)
        
        main_layout.addLayout(bottom_bar)


    def navigate_to_url(self):
        url = self.url_input.text().strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        self.web_view.setUrl(QUrl(url))
    ''' currently works but could be modified by other devs to just target a specific route 
    like if the game only exists on windows and has all it's mods saved in documents, stellaris 
    for example could work fine with a hard coded path, but it's case by case.
    Additionally: Create a hyperlink to github with a master list of folder routes for war thunder for users to reference when Gaijin changes things. Don't Forget!'''
    def find_root_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Game Root Folder")
        if folder:
            self.root_folder = folder
            
            # Create/find UserSkins folder
            self.user_skins_folder = os.path.join(folder, "UserSkins")
            os.makedirs(self.user_skins_folder, exist_ok=True)
            
            # Create/find UserMissions folder
            self.user_missions_folder = os.path.join(folder, "UserMissions")
            os.makedirs(self.user_missions_folder, exist_ok=True)
            
            self.lbl_root_path.setText(folder)
            self.lbl_root_path.setStyleSheet("color: green;")
            
            # Prompt for production folder (for sights)
            QMessageBox.information(self, "Production Folder", 
                "Now please select the 'production' folder for sight mods.\n"
                "This is typically in your documents->mygames->warthunder->saves->userid folder.")
            prod_folder = QFileDialog.getExistingDirectory(self, "Select Production Folder")
            '''all_tanks_change : As mentioned earlier the final destination folder for sights is the all_tanks folder by default but please change this to a
             different file name to match your needs, for example you can keep "UserSights" but make "all_tanks" into "my_presets" as is the case with my 
             own sights folder.'''
            if prod_folder:
                self.production_folder = prod_folder
                # Create/find UserSights and all_tanks subfolder
                self.user_sights_folder = os.path.join(prod_folder, "UserSights")
                os.makedirs(self.user_sights_folder, exist_ok=True)
                self.all_tanks_folder = os.path.join(self.user_sights_folder, "all_tanks")
                os.makedirs(self.all_tanks_folder, exist_ok=True)
            
            self.save_settings()
    ''' The download process does change based on the game, a simplified version of the setup exists for mod sites that lack mod categories or 
    only have one destination for mods to be deployed and thus categories loose relevance, please refer to github examples for different download 
    and installation setups or feel free to make your'''

    ''' Delete this - Current issues for note
    1. Mod organizer or MO grabs URL links but grabs them from the top of the page OR from the full screen post, MO needs to only grab from full screen posts: Fixed
    2. Need to find a way to categorize mods better, currently the MO only supports categories filtered by war thunder live tab: Fixed
    2B. Shorten Href setup, too clunky: Fixed
    3. Need to determine if a post is full screen or not, inspecting the websit more should reveal an answer: Fixed (Full screen posts change display block)
    4. Sights need to be deployed as pure .blk's to the all_tanks folder or use their own named folder for tank matching in game, currently working by chance due to 
    most sights being loose .blk's and others sights specific to certain tanks being properly labeled and foldered. Could be a way to make it more robust, might need to DM Magazine.
    5. Mission mods download and go to the correct location but the .blk file does not fully deploy, however the single use archive does show accurate file size and changes
    in coralation with the download of the mission mod(s): NOT FIXED
    6. Mission mods do not deploy even when misscategorized, could be an issue with the loose .blk's in general, might effect Sights: NOT FIXED (Update, issue persists regardless of category)
    7. Need to find a way to make loose camo mods install to a folder sharing the name of their zip folder, methods attempted result in unnescessary subfolders: NOT FIXED 
     - Delete this '''
    def add_mod_from_page(self):
        """Extract download links from current page and add to list."""
        self.web_page.toHtml(self._process_html_for_downloads)

    def _process_html_for_downloads(self, html: str):
        """Process HTML to find download links and detect category."""
        # Detect category from page
        category = None
        lightbox_match = re.search(
            r'<div id="clb".*?style="display:\s*block;".*?>(.*?)</div>\s*</div>',
            html,
            re.IGNORECASE | re.DOTALL
    )
        search_area = lightbox_match.group(1) if lightbox_match else html
        category_patterns = [
#            (r'class="category">added camouflage</a>', CATEGORY_CAMO),
#            (r'class="category">added mission</a>', CATEGORY_MISSION),
#            (r'class="category">added sight</a>', CATEGORY_SIGHT),
            (r'href="/feed/camouflages/"', CATEGORY_CAMO),
            (r'href="/feed/missions/"', CATEGORY_MISSION),
            (r'href="/feed/sights/"', CATEGORY_SIGHT),
#            (r'<a href="/feed/camouflages/" class="category">Added camouflage</a>', CATEGORY_CAMO),
#            (r'<a href="/feed/missions/" class="category">Added mission</a>', CATEGORY_MISSION),
#            (r'<a href="/feed/sights/" class="category">Added sight</a>', CATEGORY_SIGHT),
        ]

        for pattern, cat in category_patterns:
#            if re.search(pattern, html, re.IGNORECASE):
            if re.search(pattern, search_area, re.IGNORECASE):
                category = cat
                break
        
        # Check for unsupported categories
        if category is None:
#            other_category = re.search(r'<a href="/feed/>([^<]+)"</a>', html, re.IGNORECASE)
#            if other_category:
#                QMessageBox.warning(self, "Incorrect Mod Class", 
#                    "Incorrect Mod Class, Mod Organizer only handles Camouflage, Mission and Sight mods, sorry.")
            QMessageBox.warning(self, "Incorrect Mod Category",
                "Incorrect Mod Category, Mod Organizer only handles Camouflage, Mission, and Sight mods, sorry. Please click on a handled mod post then click add mod")
            return
        
        # Find download URLs
        download_patterns = [
            r'href=["\']?(https://live\.warthunder\.com/dl/[^"\'>\s]+)',
            r'href=["\']?(/downloads/start/\d+)',
        ]
        
        found_urls = []
        current_url = self.web_view.url().toString()
        base_url = f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}"
        
        for pattern in download_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                url = match if match.startswith('http') else base_url + match
                if url not in [m['url'] for m in self.mod_list]:
                    found_urls.append(url)
        
        if found_urls:
            for url in found_urls[:1]:
                self._add_mod_to_list(url, category)
            QMessageBox.information(self, "Mods Found", f"Added {len(found_urls[:1])} {category or 'unknown'} mod(s)")
        else:
            QMessageBox.warning(self, "No Downloads", "No download links found on this page.\nTry navigating to a mod's download page.")

    def _add_mod_to_list(self, url: str, category: Optional[str] = None):
        """Add a mod URL to the download list with category."""
        mod_name = urlparse(url).path.split('/')[-1] or f"Mod {len(self.mod_list)+1}"
        mod_entry = {'url': url, 'name': mod_name, 'checked': True, 'category': category}
        self.mod_list.append(mod_entry)
        
        # Category prefix for display
        cat_prefix = ""
        if category == CATEGORY_CAMO:
            cat_prefix = "[CAMO] "
        elif category == CATEGORY_MISSION:
            cat_prefix = "[MISSION] "
        elif category == CATEGORY_SIGHT:
            cat_prefix = "[SIGHT] "
        
        item = QListWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        display_name = cat_prefix + mod_name
        item.setText(display_name[:35] + "..." if len(display_name) > 35 else display_name)
        item.setToolTip(f"{url}\nCategory: {category or 'unknown'}")
        item.setData(Qt.ItemDataRole.UserRole, {'url': url, 'category': category})
        self.mod_listwidget.addItem(item)

    def cancel_clear_list(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()
            self.download_thread.wait()
        self.mod_list.clear()
        self.mod_listwidget.clear()
        self.progress_bar.setVisible(False)
    ''' Probably needd to make a popup later when first launching that forces the user to go through the folder process... maybe... '''
    def download_all(self):
        if not self.root_folder:
            QMessageBox.warning(self, "No Folder", "Please select a root mod folder first.")
            return
        
        # Collect mods with their target folders
        mods_to_download = []  # [{url, target_folder, category}]
        self.has_sight_mods = False
        
        for i in range(self.mod_listwidget.count()):
            item = self.mod_listwidget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                data = item.data(Qt.ItemDataRole.UserRole)
                url = data['url'] if isinstance(data, dict) else data
                category = data.get('category') if isinstance(data, dict) else None
                
                # Determine target folder based on category
                if category == CATEGORY_CAMO:
                    target = self.user_skins_folder
                elif category == CATEGORY_MISSION:
                    target = self.user_missions_folder
                elif category == CATEGORY_SIGHT:
                    target = self.all_tanks_folder
                    self.has_sight_mods = True
                else:
                    target = self.root_folder  # Fallback
                
                mods_to_download.append({'url': url, 'target': target, 'category': category})
        
        if not mods_to_download:
            QMessageBox.warning(self, "No Mods", "No mods selected for download.")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(mods_to_download))
        self.progress_bar.setValue(0)
        
        self.download_thread = DownloadThread(mods_to_download, self.root_folder)
        self.download_thread.progress.connect(self._on_download_progress)
        self.download_thread.finished_download.connect(self._on_download_finished)
        self.download_thread.all_done.connect(self._on_all_downloads_done)
        self.download_thread.start()

    def _on_download_progress(self, msg: str, current: int, total: int):
        self.progress_bar.setValue(current)
        self.statusBar().showMessage(msg)

    def _on_download_finished(self, url: str, success: bool, message: str):
        if success:
            self.master_list.append(url)
        self.progress_bar.setValue(self.progress_bar.value() + 1)
    '''Could be useful to swap this out with a click away popup rather than an okay-close popup'''
    def _on_all_downloads_done(self):
        self.progress_bar.setVisible(False)
        self.save_settings()
        QMessageBox.information(self, "Complete", "All downloads finished!")
        
        # Show sight warning if any sight mods were downloaded
        if self.has_sight_mods:
            QMessageBox.warning(self, "Sight Mods Notice",
                "Please note: sights are temperamental and may not work. "
                "Reloading the game can fix them, but their function cannot be guaranteed.")
    '''Modify all modlist code, the list needs to save the category AND the import function needs to be able to read the category, 
    methods attempted failed, keep current setup till solution is found. Using seperate lists could work but would be clunky.'''

    
    def show_full_modlist(self):
        if not self.master_list:
            QMessageBox.information(self, "Modlist", "No mods in master list yet.")
            return
        
        # Group for display
        camos, missions, sights = [], [], []
        for mod in self.master_list:
            url = mod['url'] if isinstance(mod, dict) else mod
            category = mod.get('category') if isinstance(mod, dict) else None
            if category == CATEGORY_CAMO:
                camos.append(url)
            elif category == CATEGORY_MISSION:
                missions.append(url)
            elif category == CATEGORY_SIGHT:
                sights.append(url)
        
        display = ""
        if camos:
            display += "[CAMO]\n" + "\n".join(camos) + "\n"
        if missions:
            display += "[MISSION]\n" + "\n".join(missions) + "\n"
        if sights:
            display += "[SIGHT]\n" + "\n".join(sights) + "\n"
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Full Modlist")
        msg.setText(f"Total mods downloaded: {len(self.master_list)}")
        msg.setDetailedText(display.strip())
        msg.exec()

    def export_modlist(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Export Modlist", "modlist.txt", "Text (*.txt)")
        if filepath:
            # Group mods by category
            camos = []
            missions = []
            sights = []
            
            for mod in self.master_list:
                url = mod['url'] if isinstance(mod, dict) else mod
                category = mod.get('category') if isinstance(mod, dict) else None
                
                if category == CATEGORY_CAMO:
                    camos.append(url)
                elif category == CATEGORY_MISSION:
                    missions.append(url)
                elif category == CATEGORY_SIGHT:
                    sights.append(url)
            
            # Write grouped format
            with open(filepath, 'w') as f:
                if camos:
                    f.write("[CAMO]\n")
                    for url in camos:
                        f.write(f"{url}\n")
                if missions:
                    f.write("[MISSION]\n")
                    for url in missions:
                        f.write(f"{url}\n")
                if sights:
                    f.write("[SIGHT]\n")
                    for url in sights:
                        f.write(f"{url}\n")
            
            QMessageBox.information(self, "Exported", f"Modlist exported to {filepath}")

    def import_modlist(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Modlist", "", "Text (*.txt);;JSON (*.json)")
        if filepath:
            try:
                imported_count = 0
                
                if filepath.endswith('.txt'):
                    # Parse grouped text format
                    with open(filepath, 'r') as f:
                        content = f.read()
                    
                    current_category = None
                    for line in content.strip().split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        if line == "[CAMO]":
                            current_category = CATEGORY_CAMO
                        elif line == "[MISSION]":
                            current_category = CATEGORY_MISSION
                        elif line == "[SIGHT]":
                            current_category = CATEGORY_SIGHT
                        elif line.startswith('http'):
                            if line not in [m['url'] for m in self.mod_list]:
                                self._add_mod_to_list(line, current_category)
                                imported_count += 1
                else:
                    # Legacy JSON format
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    for mod in data.get('mods', []):
                        url = mod['url'] if isinstance(mod, dict) else mod
                        category = mod.get('category') if isinstance(mod, dict) else None
                        if url not in [m['url'] for m in self.mod_list]:
                            self._add_mod_to_list(url, category)
                            imported_count += 1
                
                QMessageBox.information(self, "Imported", f"Imported {imported_count} mods")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import: {e}")
    '''If you have additional folders that need to be saved I would recommend adding to the list below so they are added to the .json settings file'''
    def save_settings(self):
        settings = {
            'root_folder': self.root_folder,
            'production_folder': self.production_folder,
            'master_list': self.master_list
        }
        settings_path = Path.home() / '.mod_organizer_settings.json'
        with open(settings_path, 'w') as f:
            json.dump(settings, f)
        '''note the path is likely going to be your C: / Users / USERNAME location, it'll be a .json file sitting in the main folder, 
        you will also see folders for your desktop, onedrive, thunmbnails, save games, etc in here. If you Delete, Relocate or Modify 
        the file name, you will need to do the setup process over again.'''
    def save_settings(self):
        settings = {
            'root_folder': self.root_folder,
            'production_folder': self.production_folder,
            'master_list': self.master_list
        }
        settings_path = Path.home() / '.mod_organizer_settings.json'
        with open(settings_path, 'w') as f:
            json.dump(settings, f)

    def load_settings(self):
        settings_path = Path.home() / '.mod_organizer_settings.json'
        if settings_path.exists():
            try:
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                self.root_folder = settings.get('root_folder', '')
                self.production_folder = settings.get('production_folder', '')
                self.master_list = settings.get('master_list', [])
                '''folder location is displayed on the GUI, it'll be in green if paths are set.'''
                if self.root_folder:
                    self.lbl_root_path.setText(self.root_folder)
                    self.lbl_root_path.setStyleSheet("color: green;")
                    # Restore folder paths
                    self.user_skins_folder = os.path.join(self.root_folder, "UserSkins")
                    self.user_missions_folder = os.path.join(self.root_folder, "UserMissions")
                
                if self.production_folder:
                    self.user_sights_folder = os.path.join(self.production_folder, "UserSights")
                    self.all_tanks_folder = os.path.join(self.user_sights_folder, "all_tanks")
            except Exception:
                pass
    ''' with the benefit of hindsight, finishing the artwork before making the MO was not the best idea... a 2560 by 1600 logo is a bit excessive. Edit logo size later'''
    
    def load_logo(self, image_path: str):
        """Load a custom logo image (4:3 or 1:1 aspect ratio)."""
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            self.logo_label.setPixmap(pixmap.scaled(
                180, 150, Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            ))

    def set_tools_content(self, content: str):
        """Set the donation/tools area content."""
        self.tools_text.setText(content)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = ModOrganizer()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
