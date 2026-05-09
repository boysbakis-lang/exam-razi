@echo off
title مدرسة الرازي - نظام الامتحانات
color 0A
echo.
echo  ================================================
echo    مدرسة الرازي - نظام الامتحانات الذكي
echo  ================================================
echo  http://localhost:5000
echo  ================================================
cd /d "%~dp0"
python app.py
if %errorlevel% neq 0 (
    echo خطأ! تأكد من تثبيت: pip install flask PyJWT reportlab openpyxl pandas
    pause
)
