import os
import sys
import re
import time
import yt_dlp
import json
import math
import requests
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
                            QComboBox, QProgressBar, QCheckBox, QTabWidget, QMessageBox,
                            QGroupBox, QGridLayout, QSizePolicy, QFrame, QFileDialog,
                            QDialog, QDesktopWidget, QSplitter, QTextEdit, QAbstractItemView)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QObject
from PyQt5.QtGui import QFont, QIcon, QPixmap, QColor, QImage, QPalette

# Global constants
COOKIE_PATH = r"C:\Users\meet\Desktop\Some_randon_shi\youtube.com_cookies.txt"
THUMBNAIL_CACHE = {}

def format_size(size_bytes):
    """Format size in bytes to human-readable format"""
    if size_bytes is None:
        return "Unknown size"
    
    if size_bytes == 0:
        return "0B"
    
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

class DownloadWorker(QThread):
    progress = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str, str)
    status = pyqtSignal(str)

    def __init__(self, item, download_dir, cookies):
        super().__init__()
        self.item = item
        self.download_dir = download_dir
        self.cookies = cookies
        self.cancelled = False

    def run(self):
        url = self.item['url']
        title = self.item['title'].replace('/', '_').replace('\\', '_')[:100]
        
        if 'audio_only' in self.item:
            format_spec = f"bestaudio[abr>={self.item['audio_format']['abr']}]"
            ydl_opts = {
                'quiet': True,
                'cookiefile': self.cookies if os.path.exists(self.cookies) else None,
                'outtmpl': os.path.join(self.download_dir, f"{title}.mp3"),
                'format': format_spec,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
                'ignoreerrors': True,
                'noprogress': False,
                'progress_hooks': [self.progress_hook],
                'no_warnings': True
            }
        else:
            video_selector = f"bestvideo[height={self.item['video_res']}][vcodec^={self.item['video_codec']}]"
            audio_selector = f"bestaudio[abr>={self.item['audio_abr']}]"
            format_spec = f"{video_selector}+{audio_selector}/best"
            ydl_opts = {
                'quiet': True,
                'cookiefile': self.cookies if os.path.exists(self.cookies) else None,
                'outtmpl': os.path.join(self.download_dir, f"{title}.mp4"),
                'format': format_spec,
                'merge_output_format': 'mp4',
                'postprocessors': [{'key': 'FFmpegMerger'}],
                'ignoreerrors': True,
                'noprogress': False,
                'progress_hooks': [self.progress_hook],
                'no_warnings': True
            }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if not self.cancelled:
                self.completed.emit({"title": title, "path": ydl_opts['outtmpl']})
        except Exception as e:
            if not self.cancelled:
                self.failed.emit(title, str(e))

    def progress_hook(self, d):
        if self.cancelled:
            return
            
        if d['status'] == 'downloading':
            self.progress.emit(d)
        elif d['status'] == 'finished':
            self.status.emit("Merging formats...")

    def cancel(self):
        self.cancelled = True

class ThumbnailLoader(QThread):
    loaded = pyqtSignal(str, QPixmap)
    
    def __init__(self, url, video_id):
        super().__init__()
        self.url = url
        self.video_id = video_id
        
    def run(self):
        if self.video_id in THUMBNAIL_CACHE:
            self.loaded.emit(self.video_id, THUMBNAIL_CACHE[self.video_id])
            return
            
        try:
            response = requests.get(self.url, stream=True)
            if response.status_code == 200:
                image = QImage()
                image.loadFromData(response.content)
                pixmap = QPixmap.fromImage(image)
                THUMBNAIL_CACHE[self.video_id] = pixmap
                self.loaded.emit(self.video_id, pixmap)
        except Exception:
            placeholder = QPixmap(120, 90)
            placeholder.fill(QColor(60, 60, 60))
            THUMBNAIL_CACHE[self.video_id] = placeholder
            self.loaded.emit(self.video_id, placeholder)

class PlaylistProcessor(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, playlist_entries, selected_indices, cookies):
        super().__init__()
        self.playlist_entries = playlist_entries
        self.selected_indices = selected_indices
        self.cookies = cookies
        self.download_items = []
        self.cancelled = False

    def run(self):
        total = len(self.selected_indices)
        added_count = 0
        total_size = 0
        
        for i, idx in enumerate(self.selected_indices):
            if self.cancelled:
                return
                
            entry = self.playlist_entries[idx-1]
            url = entry.get('url')
            if not url:
                continue
                
            self.progress.emit(i+1, total, f"Processing video {idx}/{len(self.playlist_entries)}")
            
            try:
                ydl_opts = {
                    'quiet': True,
                    'cookiefile': self.cookies if os.path.exists(self.cookies) else None,
                    'no_warnings': True,
                    'ignoreerrors': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                        
                    formats = info.get('formats', [])
                    original_language = info.get('language')
                    
                    h264_videos = [
                        f for f in formats 
                        if f.get('vcodec', '').startswith('avc1') 
                        and f.get('acodec') == 'none'
                        and f.get('height') is not None
                    ]
                    if not h264_videos:
                        vp9_videos = [
                            f for f in formats 
                            if f.get('vcodec', '').startswith('vp09') 
                            and f.get('acodec') == 'none'
                            and f.get('height') is not None
                        ]
                        if not vp9_videos:
                            continue
                        best_video = max(vp9_videos, key=lambda x: x.get('height', 0))
                    else:
                        best_video = max(h264_videos, key=lambda x: x.get('height', 0))
                        
                    best_audio = self.select_best_audio(formats, original_language)
                    if not best_audio:
                        continue
                        
                    video_size = best_video.get('filesize') or best_video.get('filesize_approx') or 0
                    audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0
                    total_size += (video_size + audio_size)
                    
                    self.download_items.append({
                        'url': url,
                        'video_res': best_video['height'],
                        'video_codec': 'avc1' if 'avc1' in best_video['vcodec'] else 'vp9',
                        'audio_abr': best_audio['abr'],
                        'title': info.get('title', f"Video {idx}"),
                        'thumbnail': info.get('thumbnail', ''),
                        'video_id': info.get('id', f'vid_{idx}')
                    })
                    added_count += 1
            except Exception as e:
                self.error.emit(f"Error processing video {idx}: {str(e)}")
        
        self.progress.emit(total, total, f"Added {added_count} videos to queue")
        self.completed.emit()

    def select_best_audio(self, formats, original_language=None):
        if original_language:
            candidates = [
                f for f in formats
                if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
                and f.get('vcodec') == 'none'
                and f.get('language') == original_language
            ]
            if candidates:
                return max(candidates, key=lambda a: a.get('abr', 0))
        
        candidates = [
            f for f in formats
            if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
            and f.get('vcodec') == 'none'
        ]
        return max(candidates, key=lambda a: a.get('abr', 0)) if candidates else None

    def cancel(self):
        self.cancelled = True

class VideoInfoFetcher(QThread):
    info_fetched = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url, cookies):
        super().__init__()
        self.url = url
        self.cookies = cookies

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'cookiefile': self.cookies if os.path.exists(self.cookies) else None,
                'no_warnings': True,
                'ignoreerrors': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.info_fetched.emit(info)
        except Exception as e:
            self.error.emit(str(e))

class BatchDownloader(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, urls, cookies):
        super().__init__()
        self.urls = urls
        self.cookies = cookies
        self.download_items = []

    def run(self):
        total = len(self.urls)
        for i, url in enumerate(self.urls):
            try:
                ydl_opts = {
                    'quiet': True,
                    'cookiefile': self.cookies if os.path.exists(self.cookies) else None,
                    'no_warnings': True,
                    'ignoreerrors': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue

                    formats = info.get('formats', [])
                    original_language = info.get('language')

                    h264_videos = [
                        f for f in formats 
                        if f.get('vcodec', '').startswith('avc1') 
                        and f.get('acodec') == 'none'
                        and f.get('height') is not None
                    ]
                    if not h264_videos:
                        vp9_videos = [
                            f for f in formats 
                            if f.get('vcodec', '').startswith('vp09') 
                            and f.get('acodec') == 'none'
                            and f.get('height') is not None
                        ]
                        if not vp9_videos:
                            continue
                        best_video = max(vp9_videos, key=lambda x: x.get('height', 0))
                    else:
                        best_video = max(h264_videos, key=lambda x: x.get('height', 0))

                    best_audio = self.select_best_audio(formats, original_language)
                    if not best_audio:
                        continue

                    download_item = {
                        'url': url,
                        'video_res': best_video['height'],
                        'video_codec': 'avc1' if 'avc1' in best_video['vcodec'] else 'vp9',
                        'audio_abr': best_audio['abr'],
                        'title': info.get('title', f"Video {i+1}"),
                        'thumbnail': info.get('thumbnail', ''),
                        'video_id': info.get('id', f'vid_{i+1}')
                    }
                    self.download_items.append(download_item)
                    self.progress.emit(i+1, total, f"Processed {i+1}/{total} videos")
            except Exception as e:
                self.error.emit(str(e))
        self.completed.emit(self.download_items)

    def select_best_audio(self, formats, original_language=None):
        if original_language:
            candidates = [
                f for f in formats
                if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
                and f.get('vcodec') == 'none'
                and f.get('language') == original_language
            ]
            if candidates:
                return max(candidates, key=lambda a: a.get('abr', 0))
        
        candidates = [
            f for f in formats
            if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
            and f.get('vcodec') == 'none'
        ]
        return max(candidates, key=lambda a: a.get('abr', 0)) if candidates else None

class YouTubeDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader hehehehe!")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(900, 600)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2D2D30;
            }
            QWidget {
                background-color: #2D2D30;
                color: #FFFFFF;
                font-family: 'Segoe UI';
            }
            QLabel {
                color: #DCDCDC;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: #3E3E42;
                border: 1px solid #3E3E42;
                border-radius: 3px;
                padding: 5px;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1C97EA;
            }
            QPushButton:disabled {
                background-color: #505050;
            }
            QListWidget {
                background-color: #252526;
                border: 1px solid #3E3E42;
                border-radius: 3px;
            }
            QProgressBar {
                border: 1px solid #3E3E42;
                border-radius: 3px;
                text-align: center;
                background-color: #1E1E1E;
            }
            QProgressBar::chunk {
                background-color: #007ACC;
                width: 10px;
            }
            QGroupBox {
                border: 1px solid #3E3E42;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
            }
            QTabWidget::pane {
                border: 1px solid #3E3E42;
                border-radius: 3px;
            }
            QTabBar::tab {
                background: #3E3E42;
                color: #DCDCDC;
                padding: 8px 15px;
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            QTabBar::tab:selected {
                background: #007ACC;
            }
            QSplitter::handle {
                background-color: #3E3E42;
            }
        """)
        
        self.download_workers = {}
        self.base_download_dir = os.path.join(os.getcwd(), 'download')
        self.current_date = datetime.now().date()
        self.download_dir = self.get_download_dir()
        self.cookies = COOKIE_PATH
        self.current_thumbnail = None
        self.thumbnail_loaders = []
        self.playlist_processor = None
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        header_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_pixmap = QPixmap().scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(logo_pixmap)
        header_layout.addWidget(logo_label)
        
        title_label = QLabel("YouTube Downloader hehehehe!")
        title_font = QFont("Segoe UI", 16, QFont.Bold)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        stats_layout = QHBoxLayout()
        self.queue_label = QLabel("Queue: 0 items")
        self.size_label = QLabel("Estimated Size: 0 MB")
        self.time_label = QLabel("Estimated Time: 0 min")
        stats_layout.addWidget(self.queue_label)
        stats_layout.addWidget(self.size_label)
        stats_layout.addWidget(self.time_label)
        stats_layout.addStretch()
        
        main_layout.addLayout(header_layout)
        main_layout.addLayout(stats_layout)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont("Segoe UI", 10))
        
        self.single_tab = self.create_single_tab()
        self.batch_tab = self.create_batch_tab()
        self.playlist_tab = self.create_playlist_tab()
        self.queue_tab = self.create_queue_tab()
        self.progress_tab = self.create_progress_tab()
        self.settings_tab = self.create_settings_tab()
        
        self.tab_widget.addTab(self.single_tab, "Single Video")
        self.tab_widget.addTab(self.batch_tab, "Batch Download")
        self.tab_widget.addTab(self.playlist_tab, "Playlist")
        self.tab_widget.addTab(self.queue_tab, "Download Queue")
        self.tab_widget.addTab(self.progress_tab, "Progress")
        self.tab_widget.addTab(self.settings_tab, "Settings")
        
        main_layout.addWidget(self.tab_widget)
        
        self.setWindowIcon(QIcon("icon.png"))
        
        self.statusBar().showMessage("Ready")
        
        self.update_stats()
        
    def create_single_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        layout.addWidget(QLabel("YouTube URL:"), 0, 0)
        self.single_url_input = QLineEdit()
        self.single_url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        layout.addWidget(self.single_url_input, 0, 1, 1, 2)
        
        self.single_thumbnail_label = QLabel()
        self.single_thumbnail_label.setFixedSize(320, 180)
        self.single_thumbnail_label.setAlignment(Qt.AlignCenter)
        self.single_thumbnail_label.setStyleSheet("background-color: #252526; border: 1px solid #3E3E42;")
        self.single_thumbnail_label.setText("Thumbnail will appear here (Maybe Chill sir)")
        layout.addWidget(self.single_thumbnail_label, 1, 0, 1, 3)
        
        layout.addWidget(QLabel("Quality:"), 2, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.setEnabled(False)
        layout.addWidget(self.quality_combo, 2, 1)
        
        self.get_info_btn = QPushButton("Get Video Info")
        self.get_info_btn.clicked.connect(self.get_video_info)
        layout.addWidget(self.get_info_btn, 2, 2)
        
        self.audio_only_checkbox = QCheckBox("Audio only (best quality)")
        layout.addWidget(self.audio_only_checkbox, 3, 0)
        
        self.add_single_btn = QPushButton("Add to Queue")
        self.add_single_btn.clicked.connect(self.add_single_download)
        self.add_single_btn.setEnabled(False)
        layout.addWidget(self.add_single_btn, 3, 1, 1, 2)
        
        self.video_info_label = QLabel()
        self.video_info_label.setWordWrap(True)
        self.video_info_label.setAlignment(Qt.AlignCenter)
        self.video_info_label.setStyleSheet("padding: 15px; background-color: #252526; border-radius: 5px;")
        layout.addWidget(self.video_info_label, 4, 0, 1, 3)
        
        self.size_info_label = QLabel("Size information will appear here")
        self.size_info_label.setWordWrap(True)
        self.size_info_label.setStyleSheet("color: #AAAAAA; font-size: 12px; padding: 5px;")
        layout.addWidget(self.size_info_label, 5, 0, 1, 3)
        
        layout.setRowStretch(5, 1)
        return tab
    
    def create_batch_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("YouTube URLs:"))
        self.batch_urls_input = QLineEdit()
        self.batch_urls_input.setPlaceholderText("Separate URLs with commas, semicolons, or spaces")
        url_layout.addWidget(self.batch_urls_input, 1)
        layout.addLayout(url_layout)
        
        self.add_batch_btn = QPushButton("Add to Queue")
        self.add_batch_btn.clicked.connect(self.add_batch_download)
        layout.addWidget(self.add_batch_btn)
        
        self.batch_status_label = QLabel()
        self.batch_status_label.setWordWrap(True)
        self.batch_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.batch_status_label)
        
        return tab
    
    def create_playlist_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Playlist URL:"))
        self.playlist_url_input = QLineEdit()
        self.playlist_url_input.setPlaceholderText("https://www.youtube.com/playlist?list=...")
        url_layout.addWidget(self.playlist_url_input, 1)
        layout.addLayout(url_layout)
        
        self.get_playlist_btn = QPushButton("Get Playlist Info")
        self.get_playlist_btn.clicked.connect(self.get_playlist_info)
        layout.addWidget(self.get_playlist_btn)
        
        playlist_info_layout = QHBoxLayout()
        playlist_info_layout.addWidget(QLabel("Videos in playlist:"))
        self.playlist_count_label = QLabel("0")
        playlist_info_layout.addWidget(self.playlist_count_label)
        playlist_info_layout.addStretch()
        layout.addLayout(playlist_info_layout)
        
        layout.addWidget(QLabel("Select videos to download:"))
        self.video_selection_input = QLineEdit()
        self.video_selection_input.setPlaceholderText("e.g., 1-10, 15, 20-25 or 'all' for entire playlist")
        layout.addWidget(self.video_selection_input)
        
        self.add_playlist_btn = QPushButton("Add Selected Videos to Queue")
        self.add_playlist_btn.clicked.connect(self.add_playlist_download)
        self.add_playlist_btn.setEnabled(False)
        layout.addWidget(self.add_playlist_btn)
        
        self.playlist_progress_bar = QProgressBar()
        self.playlist_progress_bar.setRange(0, 100)
        self.playlist_progress_bar.setVisible(False)
        layout.addWidget(self.playlist_progress_bar)
        
        self.playlist_status_label = QLabel()
        self.playlist_status_label.setWordWrap(True)
        self.playlist_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.playlist_status_label)
        
        self.playlist_info_label = QLabel()
        self.playlist_info_label.setWordWrap(True)
        self.playlist_info_label.setAlignment(Qt.AlignCenter)
        self.playlist_info_label.setStyleSheet("padding: 15px; background-color: #252526; border-radius: 5px;")
        layout.addWidget(self.playlist_info_label)
        
        self.playlist_size_label = QLabel("Total size will be calculated after selection")
        self.playlist_size_label.setWordWrap(True)
        self.playlist_size_label.setStyleSheet("color: #AAAAAA; font-size: 12px; padding: 5px;")
        layout.addWidget(self.playlist_size_label)
        
        layout.addStretch(1)
        return tab
    
    def create_queue_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        controls_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Download")
        self.start_btn.setIcon(QIcon.fromTheme("media-playback-start"))
        self.start_btn.clicked.connect(self.process_queue)
        self.start_btn.setEnabled(False)
        
        self.clear_btn = QPushButton("Clear Queue")
        self.clear_btn.setIcon(QIcon.fromTheme("edit-clear"))
        self.clear_btn.clicked.connect(self.clear_queue)
        self.clear_btn.setEnabled(False)
        
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.setIcon(QIcon.fromTheme("list-remove"))
        self.remove_btn.clicked.connect(self.remove_selected)
        self.remove_btn.setEnabled(False)
        
        controls_layout.addWidget(self.start_btn)
        controls_layout.addWidget(self.clear_btn)
        controls_layout.addWidget(self.remove_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        self.queue_list = QListWidget()
        self.queue_list.setIconSize(QSize(120, 90))
        self.queue_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.queue_list.setStyleSheet("""
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #3E3E42;
            }
            QListWidget::item:selected {
                background-color: #007ACC;
            }
        """)
        self.queue_list.itemSelectionChanged.connect(self.update_remove_button_state)
        layout.addWidget(self.queue_list)
        
        self.queue_size_label = QLabel("Total queue size: 0 MB")
        self.queue_size_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.queue_size_label)
        
        return tab
    
    def create_progress_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        current_group = QGroupBox("Current Download")
        current_layout = QVBoxLayout(current_group)
        
        thumb_layout = QHBoxLayout()
        self.progress_thumbnail_label = QLabel()
        self.progress_thumbnail_label.setFixedSize(240, 180)
        self.progress_thumbnail_label.setStyleSheet("background-color: #252526; border: 1px solid #3E3E42;")
        thumb_layout.addWidget(self.progress_thumbnail_label)
        
        info_layout = QVBoxLayout()
        self.current_title_label = QLabel("No active download")
        self.current_title_label.setWordWrap(True)
        self.current_title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.current_url_label = QLabel("URL will appear here")
        self.current_url_label.setWordWrap(True)
        self.current_url_label.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        self.current_url_label.setOpenExternalLinks(True)
        
        info_layout.addWidget(self.current_title_label)
        info_layout.addWidget(self.current_url_label)
        info_layout.addStretch()
        
        thumb_layout.addLayout(info_layout, 1)
        current_layout.addLayout(thumb_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Preparing...")
        current_layout.addWidget(self.progress_bar)
        
        details_layout = QGridLayout()
        
        details_layout.addWidget(QLabel("Status:"), 0, 0)
        self.status_label = QLabel("Idle")
        details_layout.addWidget(self.status_label, 0, 1)
        
        details_layout.addWidget(QLabel("Speed:"), 1, 0)
        self.speed_label = QLabel("0 MB/s")
        details_layout.addWidget(self.speed_label, 1, 1)
        
        details_layout.addWidget(QLabel("Downloaded:"), 2, 0)
        self.downloaded_label = QLabel("0 MB")
        details_layout.addWidget(self.downloaded_label, 2, 1)
        
        details_layout.addWidget(QLabel("ETA:"), 0, 2)
        self.eta_label = QLabel("Calculating...")
        details_layout.addWidget(self.eta_label, 0, 3)
        
        details_layout.addWidget(QLabel("Total Size:"), 1, 2)
        self.total_size_label = QLabel("0 MB")
        details_layout.addWidget(self.total_size_label, 1, 3)
        
        details_layout.addWidget(QLabel("Progress:"), 2, 2)
        self.percent_label = QLabel("0%")
        details_layout.addWidget(self.percent_label, 2, 3)
        
        current_layout.addLayout(details_layout)
        layout.addWidget(current_group)
        
        log_group = QGroupBox("Download Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #252526;")
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group, 1)
        
        return tab
    
    def create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Base Download Directory:"))
        self.dir_input = QLineEdit(self.base_download_dir)
        self.dir_input.setReadOnly(True)
        dir_layout.addWidget(self.dir_input)
        self.change_dir_btn = QPushButton("Change")
        self.change_dir_btn.clicked.connect(self.change_download_dir)
        dir_layout.addWidget(self.change_dir_btn)
        layout.addLayout(dir_layout)

        log_layout = QVBoxLayout()
        log_layout.addWidget(QLabel("Log:"))
        self.log_text_settings = QTextEdit()
        self.log_text_settings.setReadOnly(True)
        self.log_text_settings.setStyleSheet("background-color: #252526;")
        log_layout.addWidget(self.log_text_settings)
        self.open_log_btn = QPushButton("Open Log File")
        self.open_log_btn.clicked.connect(self.open_log_file)
        log_layout.addWidget(self.open_log_btn)
        layout.addLayout(log_layout)

        return tab
    
    def change_download_dir(self):
        new_dir = QFileDialog.getExistingDirectory(self, "Select Base Download Directory", self.base_download_dir)
        if new_dir:
            self.base_download_dir = new_dir
            self.download_dir = self.get_download_dir()
            self.dir_input.setText(self.base_download_dir)

    def open_log_file(self):
        log_file = os.path.join(self.download_dir, "download.log")
        if os.path.exists(log_file):
            os.startfile(log_file)
        else:
            QMessageBox.warning(self, "Log File Not Found", "Log file does not exist yet.")

    def get_download_dir(self):
        today = datetime.now().strftime('%Y-%m-%d')
        download_dir = os.path.join(self.base_download_dir, today)
        os.makedirs(download_dir, exist_ok=True)
        return download_dir
    
    def get_video_info(self):
        url = self.single_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a YouTube URL")
            return

        self.get_info_btn.setEnabled(False)
        self.get_info_btn.setText("Fetching...")
        self.size_info_label.setText("Calculating sizes...")

        self.single_thumbnail_label.clear()
        self.single_thumbnail_label.setText("Loading thumbnail...")

        self.video_info_fetcher = VideoInfoFetcher(url, self.cookies)
        self.video_info_fetcher.info_fetched.connect(self.on_video_info_fetched)
        self.video_info_fetcher.error.connect(self.on_video_info_error)
        self.video_info_fetcher.start()

    def on_video_info_fetched(self, info):
        formats = info.get('formats', [])
        original_language = info.get('language')
        video_id = info.get('id', '')
        thumbnail_url = info.get('thumbnail', '')
        title = info.get('title', 'Untitled Video')
        duration = info.get('duration', 0)
        minutes, seconds = divmod(duration, 60)
        views = info.get('view_count', 0)
        uploader = info.get('uploader', 'Unknown')

        info_text = f"<b>{title}</b><br>"
        info_text += f"By: {uploader} | Views: {views:,} | Duration: {minutes}:{seconds:02d}"
        self.video_info_label.setText(info_text)

        self.quality_combo.clear()
        video_options = {}
        for f in formats:
            vcodec = f.get('vcodec', '')
            if vcodec.startswith('avc1') or vcodec.startswith('vp09'):
                height = f.get('height')
                if not height:
                    continue
                key = f"{height}p"

                filesize = f.get('filesize') or f.get('filesize_approx')
                size_text = format_size(filesize) if filesize else "Unknown size"

                label = f"{key} - {size_text}"

                if key not in video_options:
                    video_options[key] = {'format': f, 'label': label, 'size': size_text}

        sorted_options = sorted(video_options.items(), key=lambda x: int(x[0][:-1]), reverse=True)
        for res, data in sorted_options:
            self.quality_combo.addItem(data['label'], data['format'])

        size_info = ""
        for res, data in sorted_options:
            size_info += f"{res}: {data['size']}\n"
        self.size_info_label.setText(f"<b>Available resolutions(if unknown then dont worry ):</b>\n{size_info}")

        self.quality_combo.setEnabled(True)
        self.add_single_btn.setEnabled(True)
        self.video_info = {
            'formats': formats,
            'original_language': original_language,
            'title': title,
            'thumbnail': thumbnail_url,
            'url': self.single_url_input.text().strip(),
            'video_id': video_id
        }

        if thumbnail_url:
            loader = ThumbnailLoader(thumbnail_url, video_id)
            loader.loaded.connect(self.update_single_thumbnail)
            self.thumbnail_loaders.append(loader)
            loader.start()

        self.get_info_btn.setEnabled(True)
        self.get_info_btn.setText("Get Video Info")

    def on_video_info_error(self, error):
        QMessageBox.critical(self, "Error", f"Failed to get video info: {error}")
        self.size_info_label.setText("Size information unavailable")
        self.single_thumbnail_label.setText("Thumbnail unavailable")
        self.get_info_btn.setEnabled(True)
        self.get_info_btn.setText("Get Video Info")

    def update_single_thumbnail(self, video_id, pixmap):
        if hasattr(self, 'video_info') and self.video_info.get('video_id') == video_id:
            scaled_pix = pixmap.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.single_thumbnail_label.setPixmap(scaled_pix)

    def add_single_download(self):
        if self.audio_only_checkbox.isChecked():
            best_audio = self.select_best_audio(self.video_info['formats'], self.video_info['original_language'])
            if not best_audio:
                QMessageBox.warning(self, "Audio Error", "No suitable audio track found")
                return
            download_item = {
                'url': self.video_info['url'],
                'audio_only': True,
                'audio_format': best_audio,
                'title': self.video_info['title'],
                'thumbnail': self.video_info['thumbnail'],
                'video_id': self.video_info['video_id']
            }
        else:
            if self.quality_combo.currentIndex() == -1:
                QMessageBox.warning(self, "Selection Error", "Please select a video quality")
                return
            selected_format = self.quality_combo.currentData()
            best_audio = self.select_best_audio(self.video_info['formats'], self.video_info['original_language'])
            if not best_audio:
                QMessageBox.warning(self, "Audio Error", "No suitable audio track found")
                return
            download_item = {
                'url': self.video_info['url'],
                'video_res': selected_format['height'],
                'video_codec': 'avc1' if 'avc1' in selected_format['vcodec'] else 'vp9',
                'audio_abr': best_audio['abr'],
                'title': self.video_info['title'],
                'thumbnail': self.video_info['thumbnail'],
                'video_id': self.video_info['video_id']
            }
        self.add_to_queue_list(download_item)
        self.update_stats()
        self.statusBar().showMessage(f"Added '{download_item['title'][:30]}...' to queue")

        self.single_url_input.clear()
        self.quality_combo.clear()
        self.quality_combo.setEnabled(False)
        self.add_single_btn.setEnabled(False)
        self.video_info_label.clear()
        self.size_info_label.setText("Size information will appear here")
        self.single_thumbnail_label.clear()
        self.single_thumbnail_label.setText("Thumbnail will appear here")

    def add_batch_download(self):
        urls_input = self.batch_urls_input.text().strip()
        if not urls_input:
            QMessageBox.warning(self, "Input Error", "Please enter YouTube URLs")
            return

        urls = [url.strip() for url in re.split(r'[,;\s]+', urls_input) if url.strip()]
        self.batch_status_label.setText(f"Processing {len(urls)} URLs...")
        self.batch_status_label.setStyleSheet("color: #FFD700;")
        QApplication.processEvents()

        self.batch_downloader = BatchDownloader(urls, self.cookies)
        self.batch_downloader.progress.connect(self.update_batch_progress)
        self.batch_downloader.completed.connect(self.on_batch_completed)
        self.batch_downloader.error.connect(self.on_batch_error)
        self.batch_downloader.start()

    def update_batch_progress(self, current, total, status):
        self.batch_status_label.setText(status)

    def on_batch_completed(self, download_items):
        for item in download_items:
            self.add_to_queue_list(item)
        self.update_stats()
        self.batch_status_label.setText(f"Added {len(download_items)} videos to queue")
        self.batch_status_label.setStyleSheet("color: #7FFF00;")
        self.batch_urls_input.clear()

    def on_batch_error(self, error):
        self.batch_status_label.setText(f"Error: {error}")
        self.batch_status_label.setStyleSheet("color: #FF6347;")

    def get_playlist_info(self):
        url = self.playlist_url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a playlist URL")
            return

        self.get_playlist_btn.setEnabled(False)
        self.get_playlist_btn.setText("Fetching...")
        self.playlist_info_label.setText("Fetching playlist info...")
        QApplication.processEvents()

        try:
            cookies = self.cookies if os.path.exists(self.cookies) else None
            ydl_opts = {
                'quiet': True, 
                'cookiefile': cookies, 
                'extract_flat': True,
                'no_warnings': True,
                'ignoreerrors': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                playlist_info = ydl.extract_info(url, download=False)
                if not playlist_info or 'entries' not in playlist_info:
                    QMessageBox.warning(self, "Playlist Error", "Invalid playlist or no videos found")
                    return

                self.video_entries = playlist_info['entries']
                self.playlist_count_label.setText(str(len(self.video_entries)))

                title = playlist_info.get('title', 'Untitled Playlist')
                uploader = playlist_info.get('uploader', 'Unknown')
                info_text = f"<b>{title}</b><br>By: {uploader}<br>Videos: {len(self.video_entries)}"
                self.playlist_info_label.setText(info_text)

                self.add_playlist_btn.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to get playlist info: {str(e)}")
        finally:
            self.get_playlist_btn.setEnabled(True)
            self.get_playlist_btn.setText("Get Playlist Info")

    def add_playlist_download(self):
        if not hasattr(self, 'video_entries') or not self.video_entries:
            QMessageBox.warning(self, "Playlist Error", "No playlist data available")
            return

        selection = self.video_selection_input.text().strip()
        if not selection:
            QMessageBox.warning(self, "Selection Error", "Please enter video selection")
            return

        if selection.lower() == 'all':
            selected_indices = range(1, len(self.video_entries)+1)
        else:
            selected_indices = self.parse_range_selection(selection, len(self.video_entries))

        if not selected_indices:
            QMessageBox.warning(self, "Selection Error", "No valid videos selected")
            return

        self.playlist_url_input.setEnabled(False)
        self.get_playlist_btn.setEnabled(False)
        self.video_selection_input.setEnabled(False)
        self.add_playlist_btn.setEnabled(False)

        self.playlist_progress_bar.setVisible(True)
        self.playlist_progress_bar.setRange(0, len(selected_indices))
        self.playlist_progress_bar.setValue(0)
        self.playlist_status_label.setText(f"Processing 0 of {len(selected_indices)} videos...")
        self.playlist_status_label.setStyleSheet("color: #FFD700;")

        self.playlist_processor = PlaylistProcessor(
            self.video_entries, 
            selected_indices, 
            self.cookies
        )
        self.playlist_processor.progress.connect(self.update_playlist_progress)
        self.playlist_processor.completed.connect(self.playlist_processing_completed)
        self.playlist_processor.error.connect(self.playlist_processing_error)
        self.playlist_processor.start()

    def update_playlist_progress(self, current, total, status):
        self.playlist_progress_bar.setValue(current)
        self.playlist_status_label.setText(status)
        QApplication.processEvents()

    def playlist_processing_completed(self):
        for item in self.playlist_processor.download_items:
            self.add_to_queue_list(item)

        self.update_stats()
        self.playlist_status_label.setText(f"Added {len(self.playlist_processor.download_items)} videos to queue")
        self.playlist_status_label.setStyleSheet("color: #7FFF00;")

        self.playlist_progress_bar.setVisible(False)
        self.playlist_url_input.setEnabled(True)
        self.get_playlist_btn.setEnabled(True)
        self.video_selection_input.setEnabled(True)
        self.add_playlist_btn.setEnabled(True)
        self.video_selection_input.clear()

        total_size = sum(
            item.get('video_size', 0) + item.get('audio_size', 0)
            for item in self.playlist_processor.download_items
        )   
        total_size_text = format_size(total_size)
        self.playlist_size_label.setText(f"<b>Total estimated size:</b> {total_size_text}")

        self.statusBar().showMessage(f"Added {len(self.playlist_processor.download_items)} playlist videos to queue")
        self.playlist_processor = None

    def playlist_processing_error(self, error):
        self.playlist_status_label.setText(error)
        self.playlist_status_label.setStyleSheet("color: #FF6347;")
        self.playlist_url_input.setEnabled(True)
        self.get_playlist_btn.setEnabled(True)
        self.video_selection_input.setEnabled(True)
        self.add_playlist_btn.setEnabled(True)
        self.playlist_processor = None

    def parse_range_selection(self, selection, total_items):
        selected_indices = set()
        parts = selection.split(',')

        for part in parts:
            part = part.strip()
            if '-' in part:
                start, end = part.split('-')
                try:
                    start = int(start.strip())
                    end = int(end.strip())
                    if 1 <= start <= total_items and 1 <= end <= total_items:
                        selected_indices.update(range(min(start, end), max(start, end) + 1))
                except ValueError:
                    pass
            else:
                try:
                    index = int(part)
                    if 1 <= index <= total_items:
                        selected_indices.add(index)
                except ValueError:
                    pass

        return sorted(selected_indices)

    def select_best_audio(self, formats, original_language=None):
        if original_language:
            candidates = [
                f for f in formats
                if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
                and f.get('vcodec') == 'none'
                and f.get('language') == original_language
            ]
            if candidates:
                return max(candidates, key=lambda a: a.get('abr', 0))

        candidates = [
            f for f in formats
            if f.get('acodec', '').startswith(('mp4a.40.2', 'mp4a.40.5', 'aac'))
            and f.get('vcodec') == 'none'
        ]
        return max(candidates, key=lambda a: a.get('abr', 0)) if candidates else None

    def add_to_queue_list(self, download_item):
        title = download_item['title']
        if download_item.get('audio_only'):
            title += " (Audio Only)"
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, download_item)

        placeholder = QPixmap(120, 90)
        placeholder.fill(QColor(60, 60, 60))
        item.setIcon(QIcon(placeholder))

        self.queue_list.addItem(item)
        self.update_remove_button_state()

        if download_item['thumbnail']:
            loader = ThumbnailLoader(download_item['thumbnail'], download_item['video_id'])
            loader.loaded.connect(self.update_queue_thumbnail)
            self.thumbnail_loaders.append(loader)
            loader.start()

    def update_queue_thumbnail(self, video_id, pixmap):
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            data = item.data(Qt.UserRole)
            if data and data.get('video_id') == video_id:
                item.setIcon(QIcon(pixmap.scaled(120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def update_stats(self):
        queue_count = self.queue_list.count()
        self.queue_label.setText(f"Queue: {queue_count} items")

        total_size = queue_count * 100 * 1024 * 1024  # 100 MB per video as placeholder
        size_text = format_size(total_size)
        self.size_label.setText(f"Estimated Size: {size_text}")
        self.queue_size_label.setText(f"Total queue size: {size_text}")

        has_queue = queue_count > 0
        self.start_btn.setEnabled(has_queue)
        self.clear_btn.setEnabled(has_queue)

    def update_remove_button_state(self):
        self.remove_btn.setEnabled(bool(self.queue_list.selectedItems()))

    def remove_selected(self):
        selected_items = self.queue_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            self.queue_list.takeItem(self.queue_list.row(item))

        self.update_stats()

    def clear_queue(self):
        self.queue_list.clear()
        self.update_stats()

    def process_queue(self):
        if self.queue_list.count() == 0:
            return

        self.start_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)

        self.tab_widget.setCurrentIndex(4)

        self.process_next_download()

    def process_next_download(self):
        if self.queue_list.count() == 0:
            self.start_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("All downloads completed")
            self.current_title_label.setText("All downloads completed")
            self.current_url_label.setText("")
            self.status_label.setText("Completed")
            self.log_text.append("All downloads completed successfully!")
            self.log_text_settings.append("All downloads completed successfully!")
            return

        # Check if date has changed
        if datetime.now().date() != self.current_date:
            self.current_date = datetime.now().date()
            self.download_dir = self.get_download_dir()

        item_widget = self.queue_list.takeItem(0)
        item = item_widget.data(Qt.UserRole)
        self.update_stats()

        self.current_title_label.setText(item['title'])
        self.current_url_label.setText(f'<a href="{item["url"]}">{item["url"]}</a>')

        if item['video_id'] in THUMBNAIL_CACHE:
            pixmap = THUMBNAIL_CACHE[item['video_id']].scaled(240, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.progress_thumbnail_label.setPixmap(pixmap)
        else:
            placeholder = QPixmap(240, 180)
            placeholder.fill(QColor(60, 60, 60))
            self.progress_thumbnail_label.setPixmap(placeholder)

            if item['thumbnail']:
                loader = ThumbnailLoader(item['thumbnail'], item['video_id'])
                loader.loaded.connect(self.update_progress_thumbnail)
                self.thumbnail_loaders.append(loader)
                loader.start()

        worker = DownloadWorker(item, self.download_dir, self.cookies)
        self.download_workers[item['title']] = worker

        worker.progress.connect(self.update_progress)
        worker.completed.connect(self.download_completed)
        worker.failed.connect(self.download_failed)
        worker.status.connect(self.update_status)

        worker.start()

        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.status_label.setText("Starting download...")
        self.log_text.append(f"Starting download: {item['title']}")
        self.log_text_settings.append(f"Starting download: {item['title']}")

    def update_progress_thumbnail(self, video_id, pixmap):
        if self.current_title_label.text():
            current_item = self.queue_list.item(0)
            if current_item:
                current_id = current_item.data(Qt.UserRole).get('video_id', '')
                if video_id == current_id:
                    self.progress_thumbnail_label.setPixmap(pixmap.scaled(240, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def format_eta(self, seconds):
        if seconds is None:
            return "Calculating..."
        if seconds < 60:
            return f"{seconds} sec"
        elif seconds < 3600:
            minutes = seconds // 60
            seconds = seconds % 60
            return f"{minutes} min {seconds} sec"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            return f"{hours} hr {minutes} min {seconds} sec"

    def update_progress(self, progress_data):
        if 'downloaded_bytes' in progress_data and 'total_bytes' in progress_data:
            try:
                downloaded = progress_data['downloaded_bytes']
                total = progress_data['total_bytes']
                if total > 0:
                    percent = (downloaded / total) * 100
                    self.progress_bar.setValue(int(percent))
                    self.progress_bar.setFormat(f"{percent:.1f}%")
                    self.percent_label.setText(f"{percent:.1f}%")

                if 'speed' in progress_data:
                    speed = progress_data['speed']
                    if speed > 0:
                        speed_mb = speed / (1024 * 1024)
                        self.speed_label.setText(f"{speed_mb:.2f} MB/s")

                if 'eta' in progress_data:
                    eta = progress_data['eta']
                    self.eta_label.setText(self.format_eta(eta))

                if 'total_bytes' in progress_data:
                    total_bytes = progress_data['total_bytes']
                    if total_bytes:
                        self.total_size_label.setText(format_size(total_bytes))

                if 'downloaded_bytes' in progress_data:
                    downloaded_bytes = progress_data['downloaded_bytes']
                    if downloaded_bytes:
                        self.downloaded_label.setText(format_size(downloaded_bytes))

            except Exception as e:
                print(f"Progress update error: {e}")

    def update_status(self, status):
        self.status_label.setText(status)
        self.log_text.append(status)
        self.log_text_settings.append(status)

    def download_completed(self, result):
        title = result['title']
        path = result['path']

        if title in self.download_workers:
            del self.download_workers[title]

        self.log_text.append(f"Completed: {title}")
        self.log_text_settings.append(f"Completed: {title}")
        self.log_text.append(f"Saved to: {path}")
        self.log_text_settings.append(f"Saved to: {path}")
        self.statusBar().showMessage(f"Completed: {title}")

        self.process_next_download()

    def download_failed(self, title, error):
        if title in self.download_workers:
            del self.download_workers[title]

        self.progress_bar.setFormat("Failed")
        self.status_label.setText(f"Error: {error}")
        self.log_text.append(f"Failed: {title} - {error}")
        self.log_text_settings.append(f"Failed: {title} - {error}")
        self.statusBar().showMessage(f"Failed: {title}")

        self.process_next_download()

    def closeEvent(self, event):
        for worker in self.download_workers.values():
            worker.cancel()

        for loader in self.thumbnail_loaders:
            loader.quit()
            loader.wait(500)

        if self.playlist_processor and self.playlist_processor.isRunning():
            self.playlist_processor.cancel()
            self.playlist_processor.wait(1000)

        QApplication.processEvents()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = YouTubeDownloader()
    window.show()
    sys.exit(app.exec_())
