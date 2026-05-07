@echo off
title نظام الامتحانات المدرسية
color 0A
echo.
echo  ================================================
echo    نظام الامتحانات المدرسية - School Exam System
echo  ================================================
echo.
echo  جاري تشغيل السيرفر...
echo  Starting server...
echo.
echo  افتح المتصفح على: http://localhost:5000
echo  Open browser at:  http://localhost:5000
echo.
echo  للإيقاف: اضغط Ctrl+C
echo  To stop: Press Ctrl+C
echo  ================================================
echo.

cd /d "%~dp0"
python app.py

if %errorlevel% neq 0 (
    echo.
    echo  خطأ في التشغيل! تأكد من تثبيت Python والمكتبات
    echo  Error! Make sure Python and packages are installed:
    echo  pip install flask PyJWT reportlab openpyxl pandas
    echo.
    pause
)
