REM 先编译再启动：服务端是 TypeScript，跑的是 dist/ 里的编译产物。
REM   cd server && yarn install --frozen-lockfile && yarn build
set MAIN_JS=%~dp0\dist\account_server\app.js
set CONFIG=%~dp0\dist\configs_win.js
call node.exe %MAIN_JS% %CONFIG%
pause
