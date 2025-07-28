@echo off
REM Install required packages
pip install PyQt5 yt-dlp requests

REM Add to system PATH
setx PATH "%PATH%;%~dp0dist"

pip install pyinstaller
pyinstaller --onefile --windowed ^
--add-data "youtube.com_cookies.txt;." ^
--name VideoDownloader ^
Vidoedownlaoder.py

echo Installation complete! Use 'VideoDownloader' command to run.
pause
