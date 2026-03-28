import os
import pydicom
from pydicom.errors import InvalidDicomError
import tkinter as tk
from tkinter import filedialog, messagebox

# ==========================================
# 0. ฟังก์ชันดึงข้อมูลตัวอย่าง (คงเดิม)
# ==========================================
def get_sample_dicom_info(folder_path):
    sample_info = {
        'InstitutionName': 'Not Found / Empty',
        'InstitutionAddress': 'Not Found / Empty',
        'ReferringPhysicianName': 'Not Found / Empty',
        'PerformingPhysicianName': 'Not Found / Empty',
        'PatientName': 'Not Found / Empty',
        'PatientID': 'Not Found / Empty',
        'PatientBirthDate': 'Not Found / Empty'
    }
    
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            if filename.lower().endswith(('.txt', '.pdf', '.docx', '.jpg', '.png')): 
                continue
            
            try:
                dataset = pydicom.dcmread(filepath, stop_before_pixels=True)
                sample_info['InstitutionName'] = str(getattr(dataset, 'InstitutionName', 'Not Found / Empty'))
                sample_info['InstitutionAddress'] = str(getattr(dataset, 'InstitutionAddress', 'Not Found / Empty'))
                sample_info['ReferringPhysicianName'] = str(getattr(dataset, 'ReferringPhysicianName', 'Not Found / Empty'))
                sample_info['PerformingPhysicianName'] = str(getattr(dataset, 'PerformingPhysicianName', 'Not Found / Empty'))
                sample_info['PatientName'] = str(getattr(dataset, 'PatientName', 'Not Found / Empty'))
                sample_info['PatientID'] = str(getattr(dataset, 'PatientID', 'Not Found / Empty'))
                sample_info['PatientBirthDate'] = str(getattr(dataset, 'PatientBirthDate', 'Not Found / Empty'))
                return sample_info 
            except Exception:
                continue
            
    return sample_info

# ==========================================
# 1. ฟังก์ชันหลักในการรันข้อมูล (อัปเดตระบบลบ Annotation)
# ==========================================
def process_dicom_folder(input_folder, output_folder, subject_id, protocol_number):
    
    success_count = 0
    skip_count = 0
    error_count = 0

    for root, dirs, files in os.walk(input_folder):
        rel_path = os.path.relpath(root, input_folder)
        current_output_dir = os.path.join(output_folder, rel_path)
        
        if not os.path.exists(current_output_dir):
            os.makedirs(current_output_dir)

        for filename in files:
            input_path = os.path.join(root, filename)
            
            if filename.lower().endswith(('.txt', '.pdf', '.docx', '.jpg', '.png')):
                print(f"Skipped non-DICOM report file: {input_path}")
                skip_count += 1
                continue

            try:
                dataset = pydicom.dcmread(input_path)
                
                if getattr(dataset, 'SOPClassUID', '') == '1.2.840.10008.5.1.4.1.1.7':
                    print(f"Skipped DICOM Secondary Capture (Report): {filename}")
                    skip_count += 1
                    continue

                if 'InstitutionAddress' in dataset:
                    dataset.InstitutionAddress = ''
                if 'PerformingPhysicianName' in dataset:
                    dataset.PerformingPhysicianName = ''
                # if 'PatientSex' in dataset:
                #     dataset.PatientSex = ''            
                if 'PatientAge' in dataset:
                    dataset.PatientAge = ''            

                dataset.PatientName = subject_id
                dataset.PatientID = protocol_number
                dataset.InstitutionName = protocol_number
                dataset.ReferringPhysicianName = protocol_number

                if 'PatientBirthDate' in dataset and dataset.PatientBirthDate:
                    original_dob = str(dataset.PatientBirthDate).strip()
                    if len(original_dob) >= 4:
                        year = original_dob[:4]
                        dataset.PatientBirthDate = f"{year}0101"
                    else:
                        dataset.PatientBirthDate = '' 
                        
                # ==========================================
                # เริ่มกระบวนการลบ Measurements & Annotations
                # ==========================================
                
                # 1. ลบ Graphic Annotation Sequence (0070,0001) มักใช้เก็บเส้นวาดและกล่องข้อความ
                if 'GraphicAnnotationSequence' in dataset:
                    del dataset.GraphicAnnotationSequence
                    
                # 2. ค้นหาและลบชุดข้อมูลกลุ่ม Overlays (Group 6000-60FF) และ Curves (Group 5000-50FF)
                tags_to_delete = []
                for element in dataset:
                    # ตรวจสอบหมายเลข Group ของ Tag นั้นๆ
                    if 0x5000 <= element.tag.group <= 0x50FF:
                        tags_to_delete.append(element.tag)
                    elif 0x6000 <= element.tag.group <= 0x60FF:
                        tags_to_delete.append(element.tag)
                        
                # สั่งลบ Tag ที่หาเจอทั้งหมด
                for tag in tags_to_delete:
                    del dataset[tag]
                    
                # ==========================================
                
                output_path = os.path.join(current_output_dir, f"{subject_id}_{filename}")
                dataset.save_as(output_path)
                print(f"Successfully processed and saved: {output_path}")
                
                success_count += 1

            except InvalidDicomError:
                print(f"Error: {filename} is not a valid DICOM file. Skipped.")
                error_count += 1
            except Exception as e:
                print(f"Error processing {filename}: {str(e)}")
                error_count += 1

    return success_count, skip_count, error_count


# ==========================================
# 2. คลาส UI (คงเดิม)
# ==========================================
class UserInputDialog:
    def __init__(self, parent, sample_info): 
        self.top = tk.Toplevel(parent)
        self.top.title("กำหนดตัวแปร (Parameters)")
        self.top.geometry("450x450") 
        
        self.top.attributes('-topmost', True)
        self.top.focus_force()

        self.subject_id = None
        self.protocol_number = None

        info_frame = tk.LabelFrame(self.top, text=" ข้อมูลต้นฉบับจากไฟล์ DICOM (ตัวอย่าง) ", font=('Arial', 10, 'bold'), padx=10, pady=10)
        info_frame.pack(fill=tk.X, padx=15, pady=10)

        tags_display = [
            ("(0010,0010) Patient Name", sample_info['PatientName']),
            ("(0010,0020) Patient ID", sample_info['PatientID']),
            ("(0010,0030) Patient Birth Date", sample_info['PatientBirthDate']),
            ("(0008,0080) Institution Name", sample_info['InstitutionName']),
            ("(0008,0081) Institution Address", sample_info['InstitutionAddress']),
            ("(0008,0090) Ref. Physician", sample_info['ReferringPhysicianName']),
            ("(0008,1050) Perf. Physician", sample_info['PerformingPhysicianName'])
        ]

        for label, value in tags_display:
            row_frame = tk.Frame(info_frame)
            row_frame.pack(fill=tk.X, pady=2)
            tk.Label(row_frame, text=f"{label}:", width=25, anchor="e", font=('Arial', 9)).pack(side=tk.LEFT)
            display_value = value if len(value) < 30 else value[:27] + "..."
            tk.Label(row_frame, text=f" {display_value}", anchor="w", fg="blue", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(self.top, text="กรุณากรอกข้อมูลสำหรับแทนที่ (De-identification)", font=('Arial', 11, 'bold')).pack(pady=10)

        tk.Label(self.top, text="Subject Number:").pack()
        self.subj_entry = tk.Entry(self.top, width=40)
        self.subj_entry.pack(pady=2)
        self.subj_entry.focus()

        tk.Label(self.top, text="Protocol Number:").pack()
        self.prot_entry = tk.Entry(self.top, width=40)
        self.prot_entry.pack(pady=2)

        tk.Button(self.top, text="ตกลง", command=self.on_submit, width=15, bg="#2196F3", fg="white").pack(pady=15)

        self.top.grab_set()
        parent.wait_window(self.top)

    def on_submit(self):
        self.subject_id = self.subj_entry.get().strip()
        self.protocol_number = self.prot_entry.get().strip()
        
        if not self.subject_id or not self.protocol_number:
            self.top.attributes('-topmost', False)
            messagebox.showwarning("ข้อผิดพลาด", "กรุณากรอกข้อมูลให้ครบทั้งสองช่อง")
            self.top.attributes('-topmost', True)
            return
            
        self.top.destroy()

class SummaryDialog:
    def __init__(self, parent, input_dir, output_dir, subj_id, prot_num):
        self.top = tk.Toplevel(parent)
        self.top.title("สรุปข้อมูลก่อนเริ่มทำงาน")
        self.top.geometry("600x350")
        
        self.top.attributes('-topmost', True)
        self.top.focus_force()
        
        self.action = None 

        tk.Label(self.top, text="กรุณาตรวจสอบความถูกต้องของข้อมูล", font=("Arial", 12, "bold")).pack(pady=15)
        
        info_frame = tk.Frame(self.top, bg="#f0f0f0", padx=10, pady=10)
        info_frame.pack(pady=10, padx=20, fill=tk.X)
        
        tk.Label(info_frame, text=f"Input Folder : {input_dir}", bg="#f0f0f0", anchor="w").pack(fill=tk.X, pady=2)
        tk.Label(info_frame, text=f"Output Folder : {output_dir}", bg="#f0f0f0", anchor="w").pack(fill=tk.X, pady=2)
        tk.Label(info_frame, text=f"Subject Number : {subj_id}", bg="#f0f0f0", anchor="w", fg="blue", font=('Arial', 10, 'bold')).pack(fill=tk.X, pady=2)
        tk.Label(info_frame, text=f"Protocol Number : {prot_num}", bg="#f0f0f0", anchor="w", fg="blue", font=('Arial', 10, 'bold')).pack(fill=tk.X, pady=2)

        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Run (เริ่มทำงาน)", command=self.on_run, width=15, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=15)
        tk.Button(btn_frame, text="เลือก Folder ใหม่", command=self.on_reselect, width=15, bg="#f44336", fg="white").pack(side=tk.LEFT, padx=15)

        self.top.grab_set()
        parent.wait_window(self.top)

    def on_run(self):
        self.action = 'run'
        self.top.destroy()

    def on_reselect(self):
        self.action = 'reselect'
        self.top.destroy()


# ==========================================
# 3. ลูปการทำงานหลัก (คงเดิม)
# ==========================================
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    while True:
        input_directory = filedialog.askdirectory(title="ขั้นตอนที่ 1: เลือกโฟลเดอร์ DICOM ที่ต้องการ De-identify")
        
        if not input_directory:
            print("ผู้ใช้ยกเลิกการเลือกโฟลเดอร์ สิ้นสุดการทำงาน")
            break 
            
        print("กำลังดึงข้อมูลต้นฉบับจากโฟลเดอร์... กรุณารอสักครู่")
        sample_dicom_data = get_sample_dicom_info(input_directory)
            
        input_dialog = UserInputDialog(root, sample_dicom_data)
        
        if not input_dialog.subject_id or not input_dialog.protocol_number:
            print("ผู้ใช้ยกเลิกการกรอกข้อมูล สิ้นสุดการทำงาน")
            break

        output_directory = f"{input_directory}_DeID_{input_dialog.subject_id}"

        summary_dialog = SummaryDialog(root, input_directory, output_directory, 
                                       input_dialog.subject_id, input_dialog.protocol_number)
        
        if summary_dialog.action == 'run':
            print("\n" + "="*60)
            print(f"Starting Process for Subject: {input_dialog.subject_id}...")
            print("="*60)
            
            success, skipped, errors = process_dicom_folder(input_directory, output_directory, 
                                                            input_dialog.subject_id, input_dialog.protocol_number)
            
            print("="*60)
            print("กระบวนการเสร็จสมบูรณ์!\n")
            
            summary_message = (
                f"กระบวนการ De-identification เสร็จสมบูรณ์!\n\n"
                f"📊 สรุปผลการประมวลผล:\n"
                f"✅ แปลงไฟล์สำเร็จ: {success} ไฟล์\n"
                f"⏭️ ข้าม (Report/เอกสาร): {skipped} ไฟล์\n"
                f"❌ พบข้อผิดพลาด (ไฟล์เสีย): {errors} ไฟล์\n\n"
                f"📂 ไฟล์ถูกบันทึกไว้ที่:\n{output_directory}"
            )
            
            root.attributes('-topmost', True)
            messagebox.showinfo("สรุปผลการทำงาน", summary_message)
            root.attributes('-topmost', False)
            break 
            
        elif summary_dialog.action == 'reselect':
            continue 
            
        else:
            print("ผู้ใช้ยกเลิกการทำงาน สิ้นสุดโปรแกรม")
            break