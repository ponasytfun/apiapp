@echo off
setlocal
cd /d "%~dp0"

where cargo >nul 2>nul
if not %errorlevel%==0 (
  echo Rust/Cargo was not found.
  echo Install Rust from https://rustup.rs and run this launcher again.
  pause
  exit /b 1
)

echo Starting API App Rust agent runtime...
cargo run --release
set EXIT_CODE=%errorlevel%
if not %EXIT_CODE%==0 pause
exit /b %EXIT_CODE%
