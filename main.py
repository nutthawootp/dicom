import os
import pydicom
from pydicom.errors import InvalidDicomError
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk  

# ==========================================
# 0. ฟังก์ชันดึงข้อมูลตัวอย่างและ Series
# ==========================================
def get_dicom_summary(folder_path):
    sample_info = {
        'PatientName': 'Not Found / Empty',
        'PatientID': 'Not Found / Empty',
        'PatientBirthDate': 'Not Found / Empty',
        'ReferringPhysicianName': 'Not Found / Empty',
        'PerformingPhysicianName': 'Not Found / Empty',
        'InstitutionName': 'Not Found / Empty',
        'InstitutionAddress': 'Not Found / Empty',
    }
    
    series_info = {}
    found_patient_info = False
    
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            if filename.lower().endswith(('.txt', '.pdf', '.docx', '.jpg', '.png')): 
                continue
            
            try:
                dataset = pydicom.dcmread(filepath, stop_before_pixels=True)
                
                if not found_patient_info:
                    sample_info['InstitutionName'] = str(getattr(dataset, 'InstitutionName', 'Not Found / Empty'))
                    sample_info['InstitutionAddress'] = str(getattr(dataset, 'InstitutionAddress', 'Not Found / Empty'))
                    sample_info['ReferringPhysicianName'] = str(getattr(dataset, 'ReferringPhysicianName', 'Not Found / Empty'))
                    sample_info['PerformingPhysicianName'] = str(getattr(dataset, 'PerformingPhysicianName', 'Not Found / Empty'))
                    sample_info['PatientName'] = str(getattr(dataset, 'PatientName', 'Not Found / Empty'))
                    sample_info['PatientID'] = str(getattr(dataset, 'PatientID', 'Not Found / Empty'))
                    sample_info['PatientBirthDate'] = str(getattr(dataset, 'PatientBirthDate', 'Not Found / Empty'))
                    found_patient_info = True
                
                s_num = str(getattr(dataset, 'SeriesNumber', 'Unknown'))
                s_desc = str(getattr(dataset, 'SeriesDescription', 'No Description'))
                spacing = str(getattr(dataset, 'SpacingBetweenSlices', 'Not Found'))
                thickness = str(getattr(dataset, 'SliceThickness', 'Not Found'))
                
                if s_num not in series_info:
                    series_info[s_num] = {'desc': s_desc, 'spacing': set(), 'thickness': set()}
                
                series_info[s_num]['spacing'].add(spacing)
                series_info[s_num]['thickness'].add(thickness)
                
            except Exception:
                continue
            
    return sample_info, series_info

# ==========================================
# 1. ฟังก์ชันหลักในการรันข้อมูล 
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

                # ==========================================
                # เพิ่มเงื่อนไขตรวจสอบและลบ Series 99999
                # ==========================================
                if str(getattr(dataset, 'SeriesNumber', '')) == '99999':
                    print(f"Skipped Series 99999: {filename}")
                    skip_count += 1
                    continue
                # ==========================================

                if 'InstitutionAddress' in dataset:
                    dataset.InstitutionAddress = ''
                if 'PerformingPhysicianName' in dataset:
                    dataset.PerformingPhysicianName = ''           
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
                        
                if 'GraphicAnnotationSequence' in dataset:
                    del dataset.GraphicAnnotationSequence
                    
                tags_to_delete = []
                for element in dataset:
                    if 0x5000 <= element.tag.group <= 0x50FF:
                        tags_to_delete.append(element.tag)
                    elif 0x6000 <= element.tag.group <= 0x60FF:
                        tags_to_delete.append(element.tag)
                        
                for tag in tags_to_delete:
                    del dataset[tag]
                    
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
# 2. คลาส UI 
# ==========================================

class DataPreviewDialog:
    """หน้าต่าง 1: แสดงข้อมูล Preview และ Series พร้อมปุ่ม Close / De-Identification"""
    def __init__(self, parent, sample_info, series_info): 
        self.top = tk.Toplevel(parent)
        self.top.title("ตรวจสอบข้อมูล DICOM ต้นฉบับ (Parameters Preview)")
        self.top.geometry("600x650") 
        self.top.attributes('-topmost', True)
        self.top.focus_force()

        self.action = None

        tk.Label(self.top, text="กรุณาตรวจสอบข้อมูลก่อนดำเนินการทำ De-identification", font=('Arial', 11, 'bold')).pack(pady=10)

        # --- กรอบ 1: ข้อมูลคนไข้ ---
        info_frame = tk.LabelFrame(self.top, text=" ข้อมูลต้นฉบับจากไฟล์ DICOM (ตัวอย่าง) ", font=('Arial', 10, 'bold'), padx=10, pady=5)
        info_frame.pack(fill=tk.X, padx=15, pady=5)

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
            row_frame.pack(fill=tk.X, pady=1)
            tk.Label(row_frame, text=f"{label}:", width=25, anchor="e", font=('Arial', 9)).pack(side=tk.LEFT)
            display_value = value if len(value) < 35 else value[:32] + "..."
            tk.Label(row_frame, text=f" {display_value}", anchor="w", fg="blue", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # --- กรอบ 2: ข้อมูล Series ---
        series_frame = tk.LabelFrame(self.top, text=" ข้อมูล Series (Spacing & Thickness) ", font=('Arial', 10, 'bold'), padx=10, pady=5)
        series_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        scrollbar = tk.Scrollbar(series_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        series_text = tk.Text(series_frame, height=8, width=50, yscrollcommand=scrollbar.set, font=('Arial', 9), bg="#f9f9f9")
        series_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=series_text.yview)

        if not series_info:
            series_text.insert(tk.END, "ไม่พบข้อมูล Series\n")
        else:
            sorted_series = sorted(series_info.keys(), key=lambda x: float(x) if x.replace('.', '', 1).isdigit() else float('inf'))
            for s_num in sorted_series:
                data = series_info[s_num]
                spacing_str = ", ".join(sorted(list(data['spacing'])))
                thickness_str = ", ".join(sorted(list(data['thickness'])))
                
                line = f"Series {s_num}: {data['desc']}\n"
                line += f"  ├ Spacing (0018,0088): {spacing_str}\n"
                line += f"  └ Thickness (0018,0050): {thickness_str}\n\n"
                series_text.insert(tk.END, line)
        series_text.config(state=tk.DISABLED)

        # --- กรอบปุ่มกด ---
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=20)
        
        tk.Button(btn_frame, text="Close (ปิดโปรแกรม)", command=self.on_close, width=18, bg="#f44336", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="De-Identification ➔", command=self.on_deidentify, width=18, bg="#2196F3", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)

        self.top.grab_set()
        parent.wait_window(self.top)

    def on_close(self):
        self.action = 'close'
        self.top.destroy()

    def on_deidentify(self):
        self.action = 'de_identify'
        self.top.destroy()


class DataEntryDialog:
    """หน้าต่าง 2: แสดงตาราง Format กติกา และรับค่า Subject / Protocol Number"""
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("กำหนดข้อมูล De-identification (Subject & Protocol)")
        self.top.geometry("850x600")
        self.top.attributes('-topmost', True)
        self.top.focus_force()

        self.subject_id = None
        self.protocol_number = None
        self.action = None

        tk.Label(self.top, text="คู่มือรูปแบบการกำหนดรหัสผู้เข้าร่วมวิจัย (Participant ID Format)", font=('Arial', 11, 'bold')).pack(pady=10)

        # --- ตารางแสดงคำแนะนำ ---
        table_frame = tk.Frame(self.top, padx=15)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("StudyName", "Format")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        self.tree.heading("StudyName", text="ชื่อการศึกษา (Study Name)")
        self.tree.heading("Format", text="รูปแบบการกำหนดรหัส (Participant ID Format)")
        self.tree.column("StudyName", width=150, anchor=tk.W)
        self.tree.column("Format", width=650, anchor=tk.W)

        # ข้อมูลอ้างอิงจากไฟล์ CSV
        study_formats = [
            ("Amgen 20210033", "Study number 3 หลัก ('933') + Site number 5 หลัก + รหัสผู้เข้าร่วม 3 หลัก (93362001XXX)"),
            ("Opera-01", "6606-6XXX"),
            ("Opera-02", "6606-7XXX"),
            ("BNT327-06", "Site number + participant number (XXX-XX-XXXX)"),
            ("BO43249", "XXXXX"),
            ("CT-P51 3.1", "Site number + participant number (5602XXXX)"),
            ("MB12-C-02-24", "Site number + participant number (XXXXXXXXX)"),
            ("MK-2400-001", "Site 4 หลัก + Screening 5 หลัก (XXXX-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-1022-016", "Site 4 หลัก + Screening 5 หลัก (XXXX-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-2870-009", "Site 4 หลัก + Screening 5 หลัก (XXXX-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-2870-023", "Site 4 หลัก + Screening 5 หลัก (XXXX-YYYYY) หรือ Randomization 6 หลัก"),
            ("MO41552", "XXXX"),
            ("TAS6417-301", "Site number + participant number (800-XXX)"),
            ("V940-011", "Site number 4 หลัก + Screening number 5 หลัก (XXXX-YYYYY)")
        ]
        
        for item in study_formats:
            self.tree.insert("", tk.END, values=item)
            
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- ฟอร์มรับข้อมูล ---
        form_frame = tk.Frame(self.top, pady=15)
        form_frame.pack()

        tk.Label(form_frame, text="Subject Number :", font=('Arial', 10, 'bold')).grid(row=0, column=0, padx=10, pady=5, sticky=tk.E)
        self.subj_entry = tk.Entry(form_frame, width=40, font=('Arial', 10))
        self.subj_entry.grid(row=0, column=1, pady=5)
        self.subj_entry.focus()

        tk.Label(form_frame, text="Protocol Number :", font=('Arial', 10, 'bold')).grid(row=1, column=0, padx=10, pady=5, sticky=tk.E)
        self.prot_entry = tk.Entry(form_frame, width=40, font=('Arial', 10))
        self.prot_entry.grid(row=1, column=1, pady=5)

        # --- ปุ่มกด ---
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=15)
        
        tk.Button(btn_frame, text="⬅ Back (กลับ)", command=self.on_back, width=15, bg="#9E9E9E", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="OK (ตกลง)", command=self.on_ok, width=15, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)

        self.top.grab_set()
        parent.wait_window(self.top)

    def on_back(self):
        self.action = 'back'
        self.top.destroy()

    def on_ok(self):
        self.subject_id = self.subj_entry.get().strip()
        self.protocol_number = self.prot_entry.get().strip()
        
        if not self.subject_id or not self.protocol_number:
            self.top.attributes('-topmost', False)
            messagebox.showwarning("ข้อผิดพลาด", "กรุณากรอกข้อมูลให้ครบทั้งสองช่อง")
            self.top.attributes('-topmost', True)
            return
            
        self.action = 'ok'
        self.top.destroy()


class SummaryDialog:
    """หน้าต่าง 3: สรุปข้อมูลก่อนรัน"""
    def __init__(self, parent, input_dir, output_dir, subj_id, prot_num):
        self.top = tk.Toplevel(parent)
        self.top.title("สรุปข้อมูลก่อนเริ่มทำงาน")
        self.top.geometry("650x350")
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


class FinalResultDialog:
    """หน้าต่าง 4: สรุปผลลัพธ์และเปรียบเทียบ Before/After"""
    def __init__(self, parent, success, skipped, errors, output_dir, sample_info, subj_id, prot_num):
        self.top = tk.Toplevel(parent)
        self.top.title("กระบวนการเสร็จสมบูรณ์ (Process Completed)")
        self.top.geometry("750x650")
        self.top.attributes('-topmost', True)
        self.top.focus_force()

        # ส่วนหัว 
        header_frame = tk.Frame(self.top, bg="#E8F5E9", pady=15)
        header_frame.pack(fill=tk.X)
        tk.Label(header_frame, text="✅ De-identification สำเร็จเรียบร้อย!", font=("Arial", 14, "bold"), fg="#2E7D32", bg="#E8F5E9").pack()
        
        stats_text = f"แปลงไฟล์สำเร็จ: {success} | ข้าม Report & Series: {skipped} | พบข้อผิดพลาด: {errors}"
        tk.Label(header_frame, text=stats_text, font=("Arial", 11), bg="#E8F5E9").pack(pady=5)
        tk.Label(header_frame, text=f"📂 บันทึกไว้ที่: {output_dir}", font=("Arial", 9), bg="#E8F5E9").pack()

        tk.Label(self.top, text="ตารางเปรียบเทียบค่าพารามิเตอร์ (Before vs After)", font=('Arial', 11, 'bold')).pack(pady=10)

        # ตารางเปรียบเทียบ
        table_frame = tk.Frame(self.top, padx=15)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("Tag", "Before", "After")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        tree.heading("Tag", text="DICOM Tag")
        tree.heading("Before", text="ค่าต้นฉบับ (Before)")
        tree.heading("After", text="ค่าที่ถูกเปลี่ยนแปลง (After)")
        
        tree.column("Tag", width=150, anchor=tk.W)
        tree.column("Before", width=250, anchor=tk.W)
        tree.column("After", width=250, anchor=tk.W)

        # ประมวลผลวันเกิดเพื่อโชว์ในตาราง
        dob_after = "(ว่างเปล่า / ลบทิ้ง)"
        if sample_info['PatientBirthDate'] and len(sample_info['PatientBirthDate']) >= 4 and sample_info['PatientBirthDate'] != 'Not Found / Empty':
            dob_after = f"{sample_info['PatientBirthDate'][:4]}0101"

        comparison_data = [
            ("Patient Name", sample_info['PatientName'], subj_id),
            ("Patient ID", sample_info['PatientID'], prot_num),
            ("Patient Birth Date", sample_info['PatientBirthDate'], dob_after),
            ("Institution Name", sample_info['InstitutionName'], prot_num),
            ("Institution Address", sample_info['InstitutionAddress'], "(ว่างเปล่า / ลบทิ้ง)"),
            ("Referring Physician", sample_info['ReferringPhysicianName'], prot_num),
            ("Performing Physician", sample_info['PerformingPhysicianName'], "(ว่างเปล่า / ลบทิ้ง)"),
            ("Annotations", "(อาจมีเส้นวาด หรือ กล่องข้อความ)", "(ลบทิ้งทั้งหมด)")
        ]

        for item in comparison_data:
            tree.insert("", tk.END, values=item)

        tree.pack(fill=tk.BOTH, expand=True)

        tk.Button(self.top, text="Finish (เสร็จสิ้น)", command=self.top.destroy, width=20, bg="#4CAF50", fg="white", font=('Arial', 11, 'bold')).pack(pady=20)

        self.top.grab_set()
        parent.wait_window(self.top)

# ==========================================
# 3. ลูปการทำงานหลัก (ควบคุมโฟลว์หน้าต่าง)
# ==========================================
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    while True:
        # Step 1: เลือกโฟลเดอร์
        input_directory = filedialog.askdirectory(title="ขั้นตอนที่ 1: เลือกโฟลเดอร์ DICOM ที่ต้องการ De-identify")
        
        if not input_directory:
            print("ผู้ใช้ยกเลิกการเลือกโฟลเดอร์ สิ้นสุดการทำงาน")
            break 
            
        print("กำลังสแกนข้อมูลจากทุกไฟล์ในโฟลเดอร์... กรุณารอสักครู่")
        sample_dicom_data, series_dicom_data = get_dicom_summary(input_directory)
        
        # Loop ย่อย ควบคุมการกดย้อนกลับ
        process_cancelled = False
        while True:
            # Step 2: หน้า Preview
            preview_dialog = DataPreviewDialog(root, sample_dicom_data, series_dicom_data)
            
            if preview_dialog.action == 'close' or preview_dialog.action is None:
                process_cancelled = True
                break 
                
            elif preview_dialog.action == 'de_identify':
                # Step 3: หน้า Entry
                entry_dialog = DataEntryDialog(root)
                
                if entry_dialog.action == 'back':
                    continue 
                elif entry_dialog.action == 'ok':
                    subj_id = entry_dialog.subject_id
                    prot_num = entry_dialog.protocol_number
                    break 
                else:
                    process_cancelled = True
                    break 
                    
        if process_cancelled:
            print("ปิดโปรแกรม")
            break

        # Step 4: หน้าสรุปข้อมูล
        output_directory = f"{input_directory}_DeID_{subj_id}"
        summary_dialog = SummaryDialog(root, input_directory, output_directory, subj_id, prot_num)
        
        if summary_dialog.action == 'run':
            print("\n" + "="*60)
            print(f"Starting Process for Subject: {subj_id}...")
            print("="*60)
            
            success, skipped, errors = process_dicom_folder(input_directory, output_directory, subj_id, prot_num)
            
            print("="*60)
            print("กระบวนการเสร็จสมบูรณ์!\n")
            
            # Step 5: หน้าสรุปผลแบบตาราง
            FinalResultDialog(root, success, skipped, errors, output_directory, sample_dicom_data, subj_id, prot_num)
            
            continue 
            
        elif summary_dialog.action == 'reselect':
            continue 
            
        else:
            print("ผู้ใช้ยกเลิกการทำงาน สิ้นสุดโปรแกรม")
            break
        