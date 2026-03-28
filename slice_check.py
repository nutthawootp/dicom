import os
import pydicom
from pydicom.errors import InvalidDicomError
import tkinter as tk
from tkinter import filedialog, messagebox

# ==========================================
# ส่วนเพิ่มใหม่: ฟังก์ชันช่วยสแกนและสร้าง Dialog Box
# ==========================================
def get_available_series(dicom_folder):
    """
    ฟังก์ชันสแกนไฟล์ในโฟลเดอร์อย่างรวดเร็วเพื่อหา Series Number ทั้งหมดที่มี
    พร้อมดึง Series Description มาแสดงผลให้ผู้ใช้เลือกได้ง่ายขึ้น
    """
    series_dict = {}
    for filename in os.listdir(dicom_folder):
        filepath = os.path.join(dicom_folder, filename)
        if not os.path.isfile(filepath):
            continue
            
        try:
            # อ่านเฉพาะ Header เพื่อความรวดเร็ว
            dataset = pydicom.dcmread(filepath, stop_before_pixels=True)
            s_num = str(getattr(dataset, 'SeriesNumber', 'Unknown'))
            s_desc = str(getattr(dataset, 'SeriesDescription', 'No Description'))
            
            # เก็บข้อมูลเฉพาะ Series ที่ยังไม่เคยเจอ
            if s_num not in series_dict and s_num != 'Unknown':
                series_dict[s_num] = s_desc
        except InvalidDicomError:
            continue
        except Exception:
            pass
            
    return series_dict

class SeriesSelectDialog:
    """หน้าต่าง Dialog สำหรับแสดง List ของ Series และรับค่าที่เลือก"""
    def __init__(self, parent, series_dict):
        self.top = tk.Toplevel(parent)
        self.top.title("Select DICOM Series")
        self.top.geometry("450x300")
        self.selected_series = None
        self.series_keys = list(series_dict.keys())
        
        # เรียงลำดับ Series Number จากน้อยไปมาก
        self.series_keys.sort(key=lambda x: int(x) if x.isdigit() else float('inf'))

        tk.Label(self.top, text="กรุณาเลือก Series Number ที่ต้องการตรวจสอบ:", font=('Arial', 10, 'bold')).pack(padx=10, pady=10)

        # สร้าง Listbox สำหรับแสดงรายการ
        self.listbox = tk.Listbox(self.top, width=60, font=('Arial', 10))
        self.listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        # ใส่ข้อมูลลงใน Listbox
        for key in self.series_keys:
            description = series_dict[key]
            self.listbox.insert(tk.END, f"Series {key} : {description}")

        # ปุ่มตกลง
        tk.Button(self.top, text="ตกลง (OK)", command=self.on_ok, width=15, bg="#4CAF50", fg="white").pack(pady=10)

    def on_ok(self):
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            self.selected_series = self.series_keys[index]
        self.top.destroy()

# ==========================================
# ฟังก์ชันหลัก (คงโครงสร้างเดิม 100%)
# ==========================================
def check_slice_parameters(dicom_folder, target_series_number):
    """
    ฟังก์ชันตรวจสอบค่า Spacing Between Slices และ Slice Thickness
    ของทุกภาพใน Series Number ที่กำหนด
    """
    spacing_values = set()
    thickness_values = set()
    matching_files_count = 0

    print(f"Scanning folder: {dicom_folder}")
    print(f"Looking for Series Number: {target_series_number}...\n")

    for filename in os.listdir(dicom_folder):
        filepath = os.path.join(dicom_folder, filename)
        
        if not os.path.isfile(filepath):
            continue
            
        try:
            dataset = pydicom.dcmread(filepath, stop_before_pixels=True)
            series_num = getattr(dataset, 'SeriesNumber', None)
            
            if str(series_num) == str(target_series_number):
                matching_files_count += 1
                
                spacing = getattr(dataset, 'SpacingBetweenSlices', 'Not Found')
                spacing_values.add(str(spacing))
                
                thickness = getattr(dataset, 'SliceThickness', 'Not Found')
                thickness_values.add(str(thickness))
                
        except InvalidDicomError:
            continue
        except Exception as e:
            print(f"Error reading {filename}: {str(e)}")

    print("-" * 50)
    print(f"RESULTS FOR SERIES NUMBER: {target_series_number}")
    print(f"Total images found: {matching_files_count}")
    print("-" * 50)
    
    if matching_files_count > 0:
        print(f"(0018,0088) Spacing Between Slices : {', '.join(spacing_values)}")
        print(f"(0018,0050) Slice Thickness        : {', '.join(thickness_values)}")
        
        if len(spacing_values) > 1 or len(thickness_values) > 1:
            print("\n⚠️ WARNING: พบค่าที่แตกต่างกันมากกว่า 1 รูปแบบใน Series นี้!")
            print("อาจมีการตั้งค่า Protocol การสแกนที่ไม่สม่ำเสมอ หรือมีไฟล์ปะปนกัน")
    else:
        print("ไม่พบไฟล์ภาพที่ตรงกับ Series Number นี้ในโฟลเดอร์")
    print("-" * 50)

# ==========================================
# ส่วนตั้งค่าและสั่งรันสคริปต์ (อัปเดตใหม่ให้ใช้ UI)
# ==========================================
if __name__ == "__main__":
    # ซ่อนหน้าต่างหลักของ tkinter
    root = tk.Tk()
    root.withdraw()

    # 1. เปิด Dialog Box ให้เลือกโฟลเดอร์
    print("Waiting for folder selection...")
    selected_dir = filedialog.askdirectory(title="เลือกโฟลเดอร์ DICOM ที่ต้องการตรวจสอบ")
    
    if not selected_dir:
        print("ยกเลิกการเลือกโฟลเดอร์ สิ้นสุดการทำงาน")
    else:
        print(f"Selected Directory: {selected_dir}")
        print("กำลังสแกนหา Series ทั้งหมด... กรุณารอสักครู่")
        
        # สแกนหา Series ที่มีอยู่ในโฟลเดอร์
        available_series = get_available_series(selected_dir)
        
        if not available_series:
            messagebox.showwarning("Warning", "ไม่พบไฟล์ DICOM ที่สามารถอ่าน Series Number ได้ในโฟลเดอร์นี้")
            print("ไม่พบข้อมูล Series ในโฟลเดอร์ สิ้นสุดการทำงาน")
        else:
            # 2. เปิด Dialog Box ให้เลือก Series
            dialog = SeriesSelectDialog(root, available_series)
            root.wait_window(dialog.top) # รอจนกว่าจะปิดหน้าต่าง
            
            target_series = dialog.selected_series
            
            # 3. นำค่าที่เลือกไปรันฟังก์ชันหลัก
            if target_series:
                print("\n" + "="*50)
                check_slice_parameters(selected_dir, target_series)
            else:
                print("ยกเลิกการเลือก Series สิ้นสุดการทำงาน")