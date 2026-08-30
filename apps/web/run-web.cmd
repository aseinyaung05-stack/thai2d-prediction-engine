@echo off
cd /d "%~dp0"
set NEXT_PUBLIC_API_URL=http://localhost:4000
"C:\Program Files\nodejs\node.exe" "C:\Users\Khun Myoe Oo\OneDrive\Documents\Default Project\node_modules\next\dist\bin\next" dev -p 3000 > "C:\Users\Khun Myoe Oo\OneDrive\Documents\Default Project\web-server.log" 2>&1
