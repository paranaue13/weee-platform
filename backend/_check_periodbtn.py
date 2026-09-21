# -*- coding: utf-8 -*-
import zipfile
zip_path = r"C:\Users\paran\Desktop\HER app\Windows App\Versions\weee_platform_build_2_5_35_intermediate.zip"
with zipfile.ZipFile(zip_path) as z:
    name = [n for n in z.namelist() if n.endswith('desktop_v11.html')][0]
    backup = z.read(name).decode('utf-8')
i = backup.find('.periodPickerBtn')
print("idx:", i)
if i>=0:
    print(backup[max(0,i-50):i+400])
print("---weeeDateBar---")
i2 = backup.find('.weeeDateBar{')
print(backup[max(0,i2-20):i2+400] if i2>=0 else "not found")
print("---weeeRangeBtn in backup---", 'weeeRangeBtn' in backup)
print("---weeeSegment in backup---", 'weeeSegment' in backup)
