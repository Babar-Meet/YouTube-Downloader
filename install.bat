@echo off
REM Install required packages
pip install PyQt5 yt-dlp requests

REM Add to system PATH
setx PATH "%PATH%;%~dp0dist"

echo Installation complete! Use 'VideoDownloader' command to run.
pause