@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "SRC=%~dp0humanoid_retarget"
set "COUNT=0"

if not exist "%SRC%\__init__.py" (
  echo 未找到插件目录：%SRC%
  goto :end
)

echo 正在安装 Humanoid Retarget
echo 来源：%SRC%
echo.

call :scan_appdata
call :scan_portable "H:\Blender"

if "%COUNT%"=="0" (
  echo 没有找到 Blender。
  echo 请先打开一次 Blender，让它生成用户配置目录。
  echo 便携版请放在 H:\Blender\版本号 下面，并带有 portable 目录。
  goto :end
)

echo.
echo 已安装到 %COUNT% 个 Blender。
echo.
echo 接下来请完全退出 Blender，再重新打开。
echo 菜单：编辑 - 偏好设置 - 插件，搜索 Humanoid Retarget，勾选启用。
echo 在 3D 视图按 N，侧栏里打开「重定向」。
goto :end

:scan_appdata
set "ROOT=%APPDATA%\Blender Foundation\Blender"
if not exist "%ROOT%" exit /b 0
for /d %%V in ("%ROOT%\*") do (
  call :copy_to "%%V\scripts\addons\humanoid_retarget" "用户配置 %%~nxV"
)
exit /b 0

:scan_portable
if not exist "%~1" exit /b 0
for /d %%B in ("%~1\*") do (
  if exist "%%B\portable" (
    call :copy_to "%%B\portable\scripts\addons\humanoid_retarget" "便携版 %%~nxB"
  )
)
exit /b 0

:copy_to
mkdir "%~1" 2>nul
robocopy "%SRC%" "%~1" /E /XD __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np >nul
if errorlevel 8 (
  echo 失败  %~2
  echo        %~1
  exit /b 0
)
echo 完成  %~2
echo        %~1
set /a COUNT+=1
exit /b 0

:end
if /I not "%~1"=="/nopause" pause
endlocal
