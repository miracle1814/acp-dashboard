@echo off
chcp 65001 >nul
:: ============================================================
:: ACP Dashboard 启动脚本（可移植：以脚本所在目录为根）
:: 放在 acp-dashboard 目录内即可，双击或计划任务调用。
:: ============================================================

echo [ACP] 启动可视化面板...

:: 1. 杀掉旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8083.*LISTENING" 2^>nul') do (
    taskkill /PID %%a /F 2>nul
)

:: 2. 等待端口释放
timeout /t 2 /nobreak >nul

:: 3. 启动 Dashboard（脚本所在目录）
cd /d "%~dp0"
start /B python app.py

:: 4. 确认启动
timeout /t 3 /nobreak >nul
curl -s -o nul -w "  Dashboard: HTTP %%{http_code}" http://localhost:8083/
echo.
echo [ACP] 启动完成
