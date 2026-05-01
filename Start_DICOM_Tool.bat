@echo off
echo Starting DICOM De-identification Tool...
echo Please wait while the environment is loading...

:: เปลี่ยน directory ไปยังโฟลเดอร์ที่เก็บไฟล์ main.py ของคุณ
:: (หากไฟล์ .bat นี้อยู่ในโฟลเดอร์เดียวกันกับ main.py อยู่แล้ว ไม่ต้องเปลี่ยนบรรทัดล่างนี้)
cd /d "%~dp0"

:: สั่งรันคำสั่ง uv run
uv run main.py

:: ในกรณีที่เกิดข้อผิดพลาด หน้าต่างจะไม่ปิดทันที เพื่อให้อ่าน Error ได้
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ----------------------------------------------------
    echo Program exited with an error. Please check the log.
    echo ----------------------------------------------------
    pause
)