@echo off
node "%~dp0qmd-main\node_modules\tsx\dist\cli.mjs" "%~dp0qmd-main\src\cli\qmd.ts" %*
