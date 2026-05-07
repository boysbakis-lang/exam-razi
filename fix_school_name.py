import sqlite3

conn = sqlite3.connect('data/exam_system.db')

settings = [
    ('name_ar',    'مدرسة الرازي حلقة ثانية بنين'),
    ('name_en',    'Al-Razi Boys School Cycle 2'),
    ('address',    'دبي، الامارات العربية المتحدة'),
    ('copyright',  'جميع الحقوق محفوظة : مدرسة الرازي - مديرة المدرسة أ. بدرية سيف - تصميم : هاني ابوالدهب'),
    ('banner_color','#1a3a5c'),
]

for key, value in settings:
    conn.execute('INSERT OR REPLACE INTO school_settings VALUES (?, ?)', (key, value))

conn.commit()
conn.close()

print('✅ تم تحديث اسم المدرسة بنجاح!')
print('الاسم العربي  : مدرسة الرازي حلقة ثانية بنين')
print('الاسم الإنجليزي: Al-Razi Boys School Cycle 2')
print('')
print('الآن شغّل start.bat')
input('اضغط Enter للإغلاق...')
