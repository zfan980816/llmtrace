reg query "HKLM\SOFTWARE\Docker Inc." 
reg rename "HKLM\SOFTWARE\Docker Inc.\Docker Desktop" "Docker Desktop.bak"
if errorlevel 1 reg copy "HKLM\SOFTWARE\Docker Inc.\Docker Desktop" "HKLM\SOFTWARE\Docker Inc.\Docker Desktop.bak" /f
reg delete "HKLM\SOFTWARE\Docker Inc.\Docker Desktop" /f
reg query "HKLM\SOFTWARE\Docker Inc."
timeout /t 4 >nul
