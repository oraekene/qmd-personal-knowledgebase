@echo off
if not defined QMD_ALLOWED_ORIGINS set QMD_ALLOWED_ORIGINS=*
node "%~dp0qmd-main\node_modules\tsx\dist\cli.mjs" "%~dp0qmd-main\src\cli\qmd.ts" %*
