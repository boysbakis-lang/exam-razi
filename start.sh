#!/bin/bash
echo ""
echo "================================================"
echo "  نظام الامتحانات المدرسية - School Exam System"
echo "================================================"
echo ""
echo "  جاري تشغيل السيرفر... Starting server..."
echo "  افتح المتصفح على: http://localhost:5000"
echo "  للإيقاف: Ctrl+C"
echo "================================================"
echo ""

cd "$(dirname "$0")"
python3 app.py
