@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "COUNT=0"

call :install_one humanoid_retarget "Humanoid Retarget"
call :install_one shortcut_hint "Shortcut Hint"
call :install_one humanoid_mounts "Humanoid Mounts"
call :install_one spring_bone "Spring Bone"

if "%COUNT%"=="0" (
  echo 没有找到 Blender。
  echo 请先打开一次 Blender，让它生成用户配置目录。
  echo 便携版请放在 H:\Blender\版本号 下面，并带有 portable 目录。
  goto :end
)

echo.
echo 已安装到 %COUNT% 个位置。
echo.
echo 请先完全退出 Blender，然后重新打开。
echo 菜单：编辑 - 偏好设置 - 插件，搜索并勾选：
echo   Humanoid Retarget
echo   Shortcut Hint
echo   Humanoid Mounts
echo   Spring Bone
echo Humanoid Retarget：3D 视图按 N，侧栏打开「重定向」。
echo Shortcut Hint：鼠标停在视图右上角的导航按钮上，彩色快捷键显示在按钮下方。
goto :end

:install_one
set "SRC=%~dp0%~1"
if not exist "%SRC%\__init__.py" (
  echo 未找到插件目录：%SRC%
  exit /b 0
)
echo 正在安装 %~2
echo 来源：%SRC%
call :scan_appdata "%~1"
call :scan_portable "H:\Blender" "%~1"
echo.
exit /b 0

:scan_appdata
set "ROOT=%APPDATA%\Blender Foundation\Blender"
if not exist "%ROOT%" exit /b 0
for /d %%V in ("%ROOT%\*") do (
  call :copy_to "%~1" "%%V\scripts\addons\%~1" "用户配置 %%~nxV"
)
exit /b 0

:scan_portable
if not exist "%~1" exit /b 0
for /d %%B in ("%~1\*") do (
  if exist "%%B\portable" (
    call :copy_to "%~2" "%%B\portable\scripts\addons\%~2" "便携版 %%~nxB"
  )
)
exit /b 0

:copy_to
mkdir "%~2" 2>nul
robocopy "%~dp0%~1" "%~2" /E /XD __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np >nul
if errorlevel 8 (
  echo 失败  %~3
  echo        %~2
  exit /b 0
)
echo 完成  %~3
echo        %~2
set /a COUNT+=1
exit /b 0

:end
if /I not "%~1"=="/nopause" pause
endlocal
