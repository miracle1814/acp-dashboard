@echo off
chcp 65001 >nul
:: 健康检查 + 按需启动（可移植：以脚本所在目录为根）
curl -s -o nul -w "%%{http_code}" http://localhost:8083/ 2>nul | findstr "200" >nul
if %errorlevel% neq 0 (
    echo [ACP] 启动 Dashboard...
    cd /d "%~dp0"
    start /B python app.py
)
