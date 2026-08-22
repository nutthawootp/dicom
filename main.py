import concurrent.futures
import csv
import logging
import os
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pydicom
from pydicom.errors import InvalidDicomError

# ==========================================
# 1. Configuration & Constants
# ==========================================
# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dicom_deidentification.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class DeIDConfig:
    """Configuration for de-identification process"""
    DICOM_EXTENSIONS = {'.dcm', '.DCM'}
    SKIP_EXTENSIONS = {'.txt', '.pdf', '.docx', '.jpg', '.png'}
    # ย้าย PatientAge ออกไปประมวลผลแบบไดนามิกผ่าน Checkbox ด้านล่างแทน
    TAGS_TO_CLEAR = ['InstitutionAddress', 'PerformingPhysicianName']
    TAGS_TO_REMOVE_RANGES = [(0x5000, 0x50FF), (0x6000, 0x60FF)]
    SERIES_TO_SKIP = {'99999'}
    SECONDARY_CAPTURE_UID = '1.2.840.10008.5.1.4.1.1.7'
    FORMATS_FILE = 'study_formats.csv'

CONFIG = DeIDConfig()

def _initialize_dynamic_config():
    """Loads configuration from external files and creates them if they don't exist."""
    skip_list_file = 'series_to_skip.txt'
    if not os.path.exists(skip_list_file):
        try:
            with open(skip_list_file, 'w', encoding='utf-8') as f:
                f.write("# Add series numbers to skip, one per line.\n")
                f.write("# Lines starting with # are comments and will be ignored.\n")
                f.write("99999\n")
            logger.info(f"Created default skip list file: '{skip_list_file}'.")
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Could not create default skip list file '{skip_list_file}': {e}")

    try:
        with open(skip_list_file, 'r', encoding='utf-8') as f:
            loaded_series = {line.strip() for line in f if line.strip() and not line.startswith('#')}
            if loaded_series:
                CONFIG.SERIES_TO_SKIP = loaded_series
                logger.info(f"Loaded {len(loaded_series)} series to skip from '{skip_list_file}'.")
    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Could not load '{skip_list_file}', using default configuration: {e}")


# Palette สีสไตล์ Modern Medical Terminal
COLOR_PRIMARY = "#1E293B"    # Slate Navy
COLOR_SECONDARY = "#0F766E"  # Medical Teal
COLOR_BG_LIGHT = "#F8FAFC"   # Off White
COLOR_CARD_BG = "#FFFFFF"    # White
COLOR_SUCCESS = "#10B981"    # Soft Green
COLOR_DANGER = "#EF4444"     # Soft Red
COLOR_BORDER = "#E2E8F0"     # Light Gray
COLOR_TEXT_DARK = "#0F172A"  # Very Dark Blue

# ==========================================
# 2. Data Models
# ==========================================
@dataclass
class PatientInfo:
    PatientName: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    PatientID: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    PatientBirthDate: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    PatientSex: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    PatientAge: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    StudyDate: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    ReferringPhysicianName: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    PerformingPhysicianName: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    InstitutionName: str = 'ไม่พบข้อมูล / ว่างเปล่า'
    InstitutionAddress: str = 'ไม่พบข้อมูล / ว่างเปล่า'

@dataclass
class SeriesData:
    description: str
    spacing: set
    thickness: set

@dataclass
class ProcessResult:
    success_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    qc_failed_count: int = 0 
    failed_files_details: list[str] = field(default_factory=list)

# ==========================================
# 3. DICOM Processing Service
# ==========================================
class DICOMProcessor:
    @staticmethod
    def is_valid_dicom_file(filepath: str) -> bool:
        ext = Path(filepath).suffix
        if ext not in CONFIG.DICOM_EXTENSIONS:
            return ext not in CONFIG.SKIP_EXTENSIONS
        return True
    
    @staticmethod
    def read_dicom_metadata(filepath: str) -> pydicom.Dataset | None:
        try:
            return pydicom.dcmread(filepath, stop_before_pixels=True)
        except InvalidDicomError:
            return None
        except (OSError, ValueError, RuntimeError)  as e:
            logger.error(f"Error reading {filepath}: {e!s}")
            return None

    @staticmethod
    def read_dicom_full(filepath: str) -> pydicom.Dataset | None:
        try:
            return pydicom.dcmread(filepath)
        except InvalidDicomError:
            return None
        except (OSError, ValueError, RuntimeError)  as e:
            logger.error(f"Error reading {filepath}: {e!s}")
            return None
    
    @staticmethod
    def get_attribute_safe(dataset: pydicom.Dataset, attr: str, default: str = '') -> str:
        try:
            value = getattr(dataset, attr, default)
            return str(value) if value else default
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug(f"Could not retrieve attribute {attr}: {e!s}")
            return default

    @staticmethod
    def run_quality_control(filepath: str, expected_subject: str, expected_protocol: str) -> tuple[bool, str]:
        try:
            ds = pydicom.dcmread(filepath)
            if 'PixelData' not in ds:
                return False, "ไม่พบข้อมูล Pixel Data (7FE0,0010)"
            if str(getattr(ds, 'PatientName', '')) != expected_subject:
                return False, "ค่า Patient Name ไม่ได้รับการแก้ไขอย่างถูกต้อง"
            if str(getattr(ds, 'PatientID', '')) != expected_protocol:
                return False, "ค่า Patient ID ไม่ได้รับการแก้ไขอย่างถูกต้อง"
            return True, "ผ่านการตรวจสอบ QC"
        except (OSError, ValueError, RuntimeError) as e:
            return False, f"ไฟล์เสียหายหลังจากบันทึก ({e!s})"


class DICOMScanner:
    def __init__(self, processor: DICOMProcessor):
        self.processor = processor
    
    # ปรับปรุงให้สแกนไฟล์แบบ Multithreading เพื่อเพิ่มความเร็วในการดึงข้อมูลเบื้องต้น
    def scan_folder(self, folder_path: str, progress_callback: Callable[[int, int, str], None] | None = None) -> tuple[PatientInfo, dict[str, SeriesData]]:
        patient_info = PatientInfo()
        series_info = {}
        found_patient_info = False
        
        filepaths = []
        for root, _, files in os.walk(folder_path):
            for filename in files:
                filepaths.append(os.path.join(root, filename))

        total_files = len(filepaths)
        processed_count = 0
        datasets: list[pydicom.Dataset] = []

        def _scan_worker(filepath: str) -> pydicom.Dataset | None:
            if not self.processor.is_valid_dicom_file(filepath):
                return None
            return self.processor.read_dicom_metadata(filepath)

        max_workers = min(32, (os.cpu_count() or 1) + 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {executor.submit(_scan_worker, path): path for path in filepaths}
            
            for future in concurrent.futures.as_completed(future_to_path):
                path = future_to_path[future]
                processed_count += 1
                
                try:
                    dataset = future.result()
                    if dataset:
                        datasets.append(dataset)
                except (OSError, ValueError, RuntimeError) as exc:
                    logger.error(f"File {path} generated an exception during scan: {exc}")

                if progress_callback:
                    progress_callback(processed_count, total_files, f"กำลังอ่านไฟล์: {os.path.basename(path)}")
        
        for dataset in datasets:
            if not found_patient_info:
                patient_info = self._extract_patient_info(dataset)
                found_patient_info = True
            self._extract_series_info(dataset, series_info)

        return patient_info, series_info
    
    def _extract_patient_info(self, dataset: pydicom.Dataset) -> PatientInfo:
        return PatientInfo(
            PatientName=self.processor.get_attribute_safe(dataset, 'PatientName', 'ไม่พบข้อมูล / ว่างเปล่า'),
            PatientID=self.processor.get_attribute_safe(dataset, 'PatientID', 'ไม่พบข้อมูล / ว่างเปล่า'),
            PatientBirthDate=self.processor.get_attribute_safe(dataset, 'PatientBirthDate', 'ไม่พบข้อมูล / ว่างเปล่า'),
            PatientSex=self.processor.get_attribute_safe(dataset, 'PatientSex', 'ไม่พบข้อมูล / ว่างเปล่า'),
            PatientAge=self.processor.get_attribute_safe(dataset, 'PatientAge', 'ไม่พบข้อมูล / ว่างเปล่า'),
            StudyDate=self.processor.get_attribute_safe(dataset, 'StudyDate', 'ไม่พบข้อมูล / ว่างเปล่า'),
            ReferringPhysicianName=self.processor.get_attribute_safe(dataset, 'ReferringPhysicianName', 'ไม่พบข้อมูล / ว่างเปล่า'),
            PerformingPhysicianName=self.processor.get_attribute_safe(dataset, 'PerformingPhysicianName', 'ไม่พบข้อมูล / ว่างเปล่า'),
            InstitutionName=self.processor.get_attribute_safe(dataset, 'InstitutionName', 'ไม่พบข้อมูล / ว่างเปล่า'),
            InstitutionAddress=self.processor.get_attribute_safe(dataset, 'InstitutionAddress', 'ไม่พบข้อมูล / ว่างเปล่า')
        )
    
    def _extract_series_info(self, dataset: pydicom.Dataset, series_info: dict):
        s_num = self.processor.get_attribute_safe(dataset, 'SeriesNumber', 'Unknown')
        s_desc = self.processor.get_attribute_safe(dataset, 'SeriesDescription', 'ไม่มีรายละเอียด (No Description)')
        spacing = self.processor.get_attribute_safe(dataset, 'SpacingBetweenSlices', 'ไม่ระบุ')
        thickness = self.processor.get_attribute_safe(dataset, 'SliceThickness', 'ไม่ระบุ')
        
        if s_num not in series_info:
            series_info[s_num] = SeriesData(s_desc, set(), set())
        
        series_info[s_num].spacing.add(spacing)
        series_info[s_num].thickness.add(thickness)


class DICOMDeIdentifier:
    def __init__(self, processor: DICOMProcessor):
        self.processor = processor
    
    def should_skip_file(self, dataset: pydicom.Dataset) -> str | None:
        sop_class = self.processor.get_attribute_safe(dataset, 'SOPClassUID', '')
        if sop_class == CONFIG.SECONDARY_CAPTURE_UID:
            return "Secondary Capture (Report)"
        
        series_num = self.processor.get_attribute_safe(dataset, 'SeriesNumber', '')
        if series_num in CONFIG.SERIES_TO_SKIP:
            return f"ข้าม Series {series_num}"
        
        return None
    
    def deidentify(self, dataset: pydicom.Dataset, subject_id: str, protocol_number: str, clear_sex: bool = True, clear_age: bool = True) -> None:
        for tag in CONFIG.TAGS_TO_CLEAR:
            if tag in dataset:
                dataset[tag].value = ''
        
        # จัดการฟิลด์ อายุ และ เพศ แบบเงื่อนไขไดนามิกตามความต้องการของผู้ใช้
        if clear_age and 'PatientAge' in dataset:
            dataset.PatientAge = ''
        if clear_sex and 'PatientSex' in dataset:
            dataset.PatientSex = ''
        
        dataset.PatientName = subject_id
        dataset.PatientID = protocol_number
        dataset.InstitutionName = protocol_number
        dataset.ReferringPhysicianName = protocol_number
        
        self._process_date_of_birth(dataset)
        self._remove_annotations(dataset)
        self._remove_private_tags(dataset)
    
    @staticmethod
    def _process_date_of_birth(dataset: pydicom.Dataset) -> None:
        if 'PatientBirthDate' in dataset and dataset.PatientBirthDate:
            original_dob = str(dataset.PatientBirthDate).strip()
            if len(original_dob) >= 4:
                year = original_dob[:4]
                dataset.PatientBirthDate = f"{year}0101"
            else:
                dataset.PatientBirthDate = ''
    
    @staticmethod
    def _remove_annotations(dataset: pydicom.Dataset) -> None:
        if 'GraphicAnnotationSequence' in dataset:
            del dataset.GraphicAnnotationSequence
    
    @staticmethod
    def _remove_private_tags(dataset: pydicom.Dataset) -> None:
        tags_to_delete = []
        for element in dataset:
            group = element.tag.group
            for start, end in CONFIG.TAGS_TO_REMOVE_RANGES:
                if start <= group <= end:
                    tags_to_delete.append(element.tag)
                    break
        
        for tag in tags_to_delete:
            del dataset[tag]


class DICOMFolderProcessor:
    def __init__(self, deidentifier: DICOMDeIdentifier):
        self.deidentifier = deidentifier
        self.processor = deidentifier.processor
    
    # นำระบบ Multithreading กลับมาใช้เพื่อคงประสิทธิภาพในการแปลงไฟล์จำนวนมาก
    def process(self, input_folder: str, output_folder: str, subject_id: str, protocol_number: str, clear_sex: bool = True, clear_age: bool = True, progress_callback: Callable[[int, int, str], None] | None = None) -> ProcessResult:
        result = ProcessResult()
        
        tasks = []
        for root, _, files in os.walk(input_folder):
            output_dir = self._create_output_dir(root, input_folder, output_folder)
            for filename in files:
                input_path = os.path.join(root, filename)
                tasks.append((input_path, output_dir, filename))
                
        total_files = len(tasks)
        processed_count = 0
        
        def _process_worker(task_data):
            input_path, out_dir, fname = task_data
            
            if not self.processor.is_valid_dicom_file(input_path):
                return 'SKIP', "Not a DICOM file"
                
            meta_dataset = self.processor.read_dicom_metadata(input_path)
            if not meta_dataset:
                return 'ERROR', "ไม่สามารถอ่านโครงสร้างไฟล์ DICOM เต็มรูปแบบได้"
                
            skip_reason = self.deidentifier.should_skip_file(meta_dataset)
            if skip_reason:
                return 'SKIP', skip_reason
                
            last_error_message = ""
            output_path = os.path.join(out_dir, f"{subject_id}_{fname}")
            for attempt in range(1, 4): 
                try:
                    dataset = self.processor.read_dicom_full(input_path)
                    if not dataset:
                        last_error_message = "ไม่สามารถอ่านโครงสร้างไฟล์ DICOM เต็มรูปแบบได้"
                        break 
                    
                    self.deidentifier.deidentify(dataset, subject_id, protocol_number, clear_sex, clear_age)
                    dataset.save_as(output_path)
                    
                    is_qc_passed, qc_message = self.processor.run_quality_control(output_path, subject_id, protocol_number)
                    
                    if is_qc_passed:
                        return 'SUCCESS', ""
                    else:
                        last_error_message = f"QC Failed: {qc_message}"
                        if os.path.exists(output_path):
                            os.remove(output_path)
                            
                except (OSError, ValueError, RuntimeError)  as e:
                    last_error_message = f"ข้อผิดพลาด: {e!s}"
                    if os.path.exists(output_path):
                        os.remove(output_path)
                        
            if "ไม่สามารถอ่านโครงสร้าง" in last_error_message:
                return 'ERROR', last_error_message
            else:
                return 'QC_FAIL', f"📁 Path: {input_path}\n❌ สาเหตุ: {last_error_message}"

        max_workers = min(32, (os.cpu_count() or 1) + 4) 
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(_process_worker, task): task for task in tasks}
            
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]
                input_path, _out_dir, fname = task
                processed_count += 1
                
                try:
                    status, message = future.result()
                    if status == 'SUCCESS':
                        result.success_count += 1
                    elif status == 'SKIP':
                        result.skip_count += 1
                    elif status == 'ERROR':
                        result.error_count += 1
                    elif status == 'QC_FAIL':
                        result.qc_failed_count += 1
                        result.failed_files_details.append(message)
                except (OSError, ValueError, RuntimeError) as exc:
                    result.error_count += 1
                    logger.error(f"File {fname} generated an exception: {exc}")
                
                if progress_callback:
                    progress_callback(processed_count, total_files, f"กำลังประมวลผล: {fname}")
                    
        return result
    
    @staticmethod
    def _create_output_dir(root: str, input_folder: str, output_folder: str) -> str:
        rel_path = os.path.relpath(root, input_folder)
        output_dir = os.path.join(output_folder, rel_path)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return output_dir

# ==========================================
# 4. UI Engine: Single-Window Modern Layout
# ==========================================
class ModernDICOMDeIDApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DICOM Client De-identification Workspace")
        
        # ตั้งค่าให้หน้าต่างหลักเปิดเต็มจอก่อนตามที่ระบุ
        try:
            self.root.state('zoomed')
        except tk.TclError:
            self.root.geometry("1100x750") # Fallback ในกรณีที่ไม่รองรับ zoomed
            
        self.root.minsize(1050, 700)
        self.root.configure(bg=COLOR_BG_LIGHT)
        
        self.processor = DICOMProcessor()
        self.scanner = DICOMScanner(self.processor)
        self.deidentifier = DICOMDeIdentifier(self.processor)
        self.folder_processor = DICOMFolderProcessor(self.deidentifier)
        
        self.input_dir = ""
        self.output_dir = ""
        self.patient_info = PatientInfo()
        self.series_info = {}
        
        # กำหนดตัวแปรสำหรับเก็บบริบทการกดเลือก Checkbox ลบ เพศ/อายุ (Default = True)
        self.var_clear_age = tk.BooleanVar(value=True)
        self.var_clear_sex = tk.BooleanVar(value=False)
        
        self._init_styles()
        self._build_main_layout()
        self.show_step(1)

    def _init_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure("Treeview", 
                        background=COLOR_CARD_BG, 
                        foreground=COLOR_TEXT_DARK, 
                        rowheight=26, 
                        fieldbackground=COLOR_CARD_BG,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", 
                        background=COLOR_BORDER, 
                        foreground=COLOR_TEXT_DARK, 
                        font=("Segoe UI", 10, "bold"),
                        borderwidth=1)
        style.map("Treeview.Heading", background=[('active', '#CBD5E1')])
        style.map("Treeview", background=[('selected', "#0f766e")])

    def _build_main_layout(self):
        self.sidebar = tk.Frame(self.root, bg=COLOR_PRIMARY, width=220)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        
        lbl_app_title = tk.Label(self.sidebar, text="DICOM De-ID\nWorkspace", fg="white", bg=COLOR_PRIMARY, 
                                font=("Segoe UI", 15, "bold"), pady=20)
        lbl_app_title.pack(fill=tk.X)
        
        self.steps_indicators = []
        steps_text = ["1. ตรวจสอบข้อมูลต้นฉบับ", "2. กรอกข้อมูล De-ID", "3. ดำเนินการและประเมินผล"]
        for i, text in enumerate(steps_text, 1):
            frame_ind = tk.Frame(self.sidebar, bg=COLOR_PRIMARY, pady=12, padx=15)
            frame_ind.pack(fill=tk.X)
            lbl_num = tk.Label(frame_ind, text=f" {i} ", fg=COLOR_PRIMARY, bg="white", font=("Segoe UI", 9, "bold"), width=3)
            lbl_num.pack(side=tk.LEFT, padx=(0, 10))
            lbl_txt = tk.Label(frame_ind, text=text, fg="#94A3B8", bg=COLOR_PRIMARY, font=("Segoe UI", 10, "bold"))
            lbl_txt.pack(side=tk.LEFT)
            self.steps_indicators.append((frame_ind, lbl_num, lbl_txt))

        self.workstage = tk.Frame(self.root, bg=COLOR_BG_LIGHT)
        self.workstage.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=25, pady=20)
        
        self.footer = tk.Frame(self.root, bg=COLOR_BG_LIGHT, height=60, bd=1, relief=tk.FLAT)
        self.footer.pack(side=tk.BOTTOM, fill=tk.X, padx=25, pady=(0, 20))
        
        self.btn_back = tk.Button(self.footer, text="⬅ ย้อนกลับ", command=self.on_back, bg="#F1F5F9", fg=COLOR_TEXT_DARK, 
                                font=("Segoe UI", 10, "bold"), padx=20, borderwidth=0, activebackground="#E2E8F0")
        self.btn_back.pack(side=tk.LEFT)
        
        self.btn_next = tk.Button(self.footer, text="ขั้นตอนถัดไป ➔", command=self.on_next, bg=COLOR_SECONDARY, fg="white", 
                                font=("Segoe UI", 10, "bold"), padx=20, borderwidth=0, activebackground="#0D9488")
        self.btn_next.pack(side=tk.RIGHT)

        self.stage_frames = {}
        self._build_stage1()
        self._build_stage2()
        self._build_stage3()

    def update_sidebar_status(self, active_step: int):
        for i, (frame, lbl_num, lbl_txt) in enumerate(self.steps_indicators, 1):
            if i == active_step:
                frame.config(bg="#1E293B")
                lbl_num.config(bg=COLOR_SECONDARY, fg="white")
                lbl_txt.config(fg="white")
            elif i < active_step:
                frame.config(bg=COLOR_PRIMARY)
                lbl_num.config(bg=COLOR_SUCCESS, fg="white")
                lbl_txt.config(fg="#94A3B8")
            else:
                frame.config(bg=COLOR_PRIMARY)
                lbl_num.config(bg="white", fg=COLOR_PRIMARY)
                lbl_txt.config(fg="#64748B")

    def show_step(self, step_num: int):
        self.current_step = step_num
        self.update_sidebar_status(step_num)
        
        for step, frame in self.stage_frames.items():
            if step == step_num:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

        if step_num == 1:
            self.btn_back.pack_forget()
            self.btn_next.config(text="ระบุข้อมูลถัดไป ➔")
        elif step_num == 2:
            self.btn_back.pack(side=tk.LEFT)
            self.btn_next.config(text="เริ่มกระบวนการ De-ID ➔")
        else:
            self.btn_back.pack_forget()
            self.btn_next.config(text="แปลงเสร็จสิ้น / โฟลเดอร์ถัดไป ➔")

    # ==========================================
    # STAGE 1: เลือกโฟลเดอร์ และ Preview ข้อมูลเดิม
    # ==========================================
    def _build_stage1(self):
        frame = tk.Frame(self.workstage, bg=COLOR_BG_LIGHT)
        self.stage_frames[1] = frame
        
        folder_frame = tk.Frame(frame, bg=COLOR_BG_LIGHT)
        folder_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(folder_frame, text="โฟลเดอร์เป้าหมาย:", font=("Segoe UI", 10, "bold"), bg=COLOR_BG_LIGHT, fg=COLOR_TEXT_DARK).pack(side=tk.LEFT)
        self.ent_folder = tk.Entry(folder_frame, bg="white", borderwidth=1, relief=tk.SOLID, font=("Segoe UI", 10), fg=COLOR_TEXT_DARK)
        self.ent_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, ipady=4)
        
        btn_browse = tk.Button(folder_frame, text="เลือกโฟลเดอร์ DICOM...", command=self.browse_folder, bg=COLOR_PRIMARY, fg="white", 
                            font=("Segoe UI", 9, "bold"), borderwidth=0, activebackground="#334155")
        btn_browse.pack(side=tk.LEFT, ipadx=10, ipady=3)

        split_frame = tk.Frame(frame, bg=COLOR_BG_LIGHT)
        split_frame.pack(fill=tk.BOTH, expand=True)

        self.left_card = tk.LabelFrame(split_frame, text=" รายละเอียดคนไข้และสถานพยาบาล ", font=("Segoe UI", 10, "bold"), 
                                    bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID)
        self.left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.right_card = tk.LabelFrame(split_frame, text=" รายละเอียดและคุณสมบัติ Series ที่พบ ", font=("Segoe UI", 10, "bold"), 
                                    bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID)
        self.right_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        cols = ("num", "desc", "spacing", "thickness")
        self.tree_series = ttk.Treeview(self.right_card, columns=cols, show="headings")
        self.tree_series.heading("num", text="Series")
        self.tree_series.heading("desc", text="รายละเอียด")
        self.tree_series.heading("spacing", text="Spacing")
        self.tree_series.heading("thickness", text="Thickness")
        
        self.tree_series.column("num", width=60, anchor=tk.CENTER)
        self.tree_series.column("desc", width=160, anchor=tk.W)
        self.tree_series.column("spacing", width=90, anchor=tk.CENTER)
        self.tree_series.column("thickness", width=90, anchor=tk.CENTER)
        
        scrollbar = ttk.Scrollbar(self.right_card, orient=tk.VERTICAL, command=self.tree_series.yview)
        self.tree_series.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_series.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def browse_folder(self):
        folder = filedialog.askdirectory(title="เลือกโฟลเดอร์ข้อมูล DICOM")
        if not folder:
            return
        
        self.input_dir = folder
        self.ent_folder.delete(0, tk.END)
        self.ent_folder.insert(0, folder)
        
        self.run_folder_scan()

    def run_folder_scan(self):
        progress_win = tk.Toplevel(self.root)
        progress_win.title("สแกนข้อมูล DICOM...")
        progress_win.geometry("400x120")
        progress_win.configure(bg=COLOR_BG_LIGHT)
        progress_win.attributes('-topmost', True)
        progress_win.grab_set()
        
        lbl_info = tk.Label(progress_win, text="กรุณารอสักครู่ กำลังทำการดึงข้อมูล Metadata...", font=("Segoe UI", 10), bg=COLOR_BG_LIGHT)
        lbl_info.pack(pady=(15, 5))
        
        pbar = ttk.Progressbar(progress_win, orient=tk.HORIZONTAL, length=320, mode='determinate')
        pbar.pack(pady=5)
        
        def update_progress(current, total, msg):
            if not progress_win.winfo_exists():
                return
            if current == 1 or current == total or current % 50 == 0:
                pct = int((current / total) * 100) if total > 0 else 0
                pbar['value'] = pct
                lbl_info.config(text=f"กำลังอ่าน: {current} / {total} ไฟล์")
                progress_win.update_idletasks()

        self.root.update_idletasks()
        self.patient_info, self.series_info = self.scanner.scan_folder(self.input_dir, progress_callback=update_progress)
        
        if progress_win.winfo_exists():
            progress_win.grab_release()
            progress_win.destroy()
        
        self.populate_metadata_preview()

    def populate_metadata_preview(self):
        for widget in self.left_card.winfo_children():
            widget.destroy()

        patient_tags = [
            ("Patient Name", self.patient_info.PatientName),
            ("Patient ID", self.patient_info.PatientID),
            ("Patient Birth Date", self.patient_info.PatientBirthDate),
            ("Patient Sex", self.patient_info.PatientSex),
            ("Patient Age", self.patient_info.PatientAge),
            ("Study Date", self.patient_info.StudyDate),
            ("Institution Name", self.patient_info.InstitutionName),
            ("Institution Address", self.patient_info.InstitutionAddress),
            ("Ref. Physician", self.patient_info.ReferringPhysicianName),
            ("Perf. Physician", self.patient_info.PerformingPhysicianName)
        ]

        for i, (label, val) in enumerate(patient_tags):
            tk.Label(self.left_card, text=f"{label}:", bg=COLOR_CARD_BG, fg="#64748B", font=("Segoe UI", 9, "bold"), anchor="e", width=18).grid(row=i, column=0, sticky="e", pady=5, padx=5)
            tk.Label(self.left_card, text=val, bg=COLOR_CARD_BG, fg=COLOR_TEXT_DARK, font=("Segoe UI", 9, "bold"), anchor="w").grid(row=i, column=1, sticky="w", pady=5, padx=5)

        for i in self.tree_series.get_children():
            self.tree_series.delete(i)

        sorted_keys = sorted(self.series_info.keys(), key=lambda x: float(x) if x.replace('.', '', 1).isdigit() else float('inf'))
        for key in sorted_keys:
            data = self.series_info[key]
            spacing = ", ".join(sorted(data.spacing))
            thickness = ", ".join(sorted(data.thickness))
            self.tree_series.insert("", tk.END, values=(key, data.description, spacing, thickness))

    # ==========================================
    # STAGE 2: กำหนดและตรวจรหัสการวิจัยใหม่
    # ==========================================
    def _build_stage2(self):
        frame = tk.Frame(self.workstage, bg=COLOR_BG_LIGHT)
        self.stage_frames[2] = frame

        interactive_frame = tk.Frame(frame, bg=COLOR_BG_LIGHT)
        interactive_frame.pack(fill=tk.BOTH, expand=True)

        guide_frame = tk.LabelFrame(interactive_frame, text=" คู่มือรูปแบบรหัสอ้างอิงของแต่ละ Study (ดับเบิ้ลคลิกแถวเพื่อเลือกกรอกอัตโนมัติ) ", 
                                    font=("Segoe UI", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID)
        guide_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.tree_formats = ttk.Treeview(guide_frame, columns=("StudyName", "Format"), show="headings")
        self.tree_formats.heading("StudyName", text="Study Name")
        self.tree_formats.heading("Format", text="Participant ID Format Structure")
        self.tree_formats.column("StudyName", width=150, anchor=tk.W)
        self.tree_formats.column("Format", width=380, anchor=tk.W)
        
        scroller = ttk.Scrollbar(guide_frame, orient=tk.VERTICAL, command=self.tree_formats.yview)
        self.tree_formats.configure(yscrollcommand=scroller.set)
        scroller.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_formats.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.tree_formats.bind("<Double-1>", self.on_format_double_click)

        input_card = tk.LabelFrame(interactive_frame, text=" กำหนดรหัสข้อมูล De-identification ", font=("Segoe UI", 10, "bold"), 
                                bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID, padx=15, pady=15)
        input_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        lbl_tip = tk.Label(input_card, text="💡 คำแนะนำการป้อนข้อมูล\nโปรดตรวจสอบให้แน่ใจว่ารหัสตรงกับคู่มือด้านซ้ายมือ", 
                        bg="#EFF6FF", fg="#1D4ED8", font=("Segoe UI", 9, "bold"), justify=tk.LEFT, bd=1, relief=tk.SOLID, padx=10, pady=8)
        lbl_tip.pack(fill=tk.X, pady=(0, 15))

        tk.Label(input_card, text="Subject Number *", font=("Segoe UI", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_TEXT_DARK).pack(anchor="w", pady=2)
        self.ent_subject = tk.Entry(input_card, bg="white", borderwidth=1, relief=tk.SOLID, font=("Segoe UI", 11), fg=COLOR_TEXT_DARK)
        self.ent_subject.pack(fill=tk.X, ipady=5, pady=(0, 15))
        self.ent_subject.bind("<KeyRelease>", self.validate_inputs)

        tk.Label(input_card, text="Protocol Number *", font=("Segoe UI", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_TEXT_DARK).pack(anchor="w", pady=2)
        self.ent_protocol = tk.Entry(input_card, bg="white", borderwidth=1, relief=tk.SOLID, font=("Segoe UI", 11), fg=COLOR_TEXT_DARK)
        self.ent_protocol.pack(fill=tk.X, ipady=5, pady=(0, 15))
        self.ent_protocol.bind("<KeyRelease>", self.validate_inputs)

        # --- ส่วนของอินเทอร์เฟซเพิ่มทางเลือกลบข้อมูล เพศ และ อายุ ---
        options_frame = tk.LabelFrame(input_card, text=" ตัวเลือกการลบ/ปกปิดข้อมูลสถิติประชากร ", font=("Segoe UI", 10, "bold"),
                                bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID, padx=10, pady=8)
        options_frame.pack(fill=tk.X, pady=(0, 15))

        cb_age = tk.Checkbutton(options_frame, text="ลบข้อมูลอายุคนไข้ (Clear Patient Age)", variable=self.var_clear_age, 
                                bg=COLOR_CARD_BG, fg=COLOR_TEXT_DARK, font=("Segoe UI", 9, "bold"), activebackground=COLOR_CARD_BG)
        cb_age.pack(anchor="w", pady=2)

        cb_sex = tk.Checkbutton(options_frame, text="ลบข้อมูลเพศคนไข้ (Clear Patient Sex)", variable=self.var_clear_sex, 
                                bg=COLOR_CARD_BG, fg=COLOR_TEXT_DARK, font=("Segoe UI", 9, "bold"), activebackground=COLOR_CARD_BG)
        cb_sex.pack(anchor="w", pady=2)
        # -----------------------------------------------------

        preview_frame = tk.Frame(input_card, bg="#F1F5F9", bd=1, relief=tk.SOLID, padx=10, pady=8)
        preview_frame.pack(fill=tk.X, pady=(15, 0))
        self.lbl_path_preview = tk.Label(preview_frame, text="ตำแหน่งบันทึกไฟล์ส่งออก: -", font=("Segoe UI", 9, "bold"), bg="#F1F5F9", fg="#475569", anchor="w", justify=tk.LEFT, wraplength=350)
        self.lbl_path_preview.pack(fill=tk.X)

        self._load_and_populate_formats()

    def _load_and_populate_formats(self):
        filepath = CONFIG.FORMATS_FILE
        default_formats = [
            ("20210033", "Study number 3 หลัก ('933') + Site 5 หลัก ('62001') + pt ID 3 หลัก (93362001XXX)"),
            ("OP-1250-301", "6606-6XXX"),
            ("OP-1250-302", "6606-7XXX"),
            ("BNT327-06", "Site number + participant number (XXX-XX-XXXX)"),
            ("BO43249", "XXXXX"),
            ("CT-P51 3.1", "Site number + participant number (5602XXXX)"),
            ("MB12-C-02-24", "Site number + participant number (XXXXXXXXX)"),
            ("MK-2400-001", "Site 4 หลัก (0887)+ Screen 5 หลัก (XXXX-YYYYY) หรือ Rand 6 หลัก"),
            ("MK-1022-016", "Site 4 หลัก (2924)+ Screen 5 หลัก (XXXX-YYYYY) หรือ Rand 6 หลัก"),
            ("MK-2870-009", "Site 4 หลัก (4006)+ Screen 5 หลัก (XXXX-YYYYY) หรือ Rand 6 หลัก"),
            ("MK-2870-023", "Site 4 หลัก (2300)+ Screen 5 หลัก (XXXX-YYYYY) หรือ Rand 6 หลัก"),
            ("MO41552", "XXXX"),
            ("TAS-6417-301", "Site number + participant number (800-XXX)"),
            ("V940-011", "Site number 4 หลัก + Screening number 5 หลัก (XXXX-YYYYY)")
        ]
        
        formats = []
        if not os.path.exists(filepath):
            try:
                with open(filepath, mode='w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["StudyName", "Format"])
                    writer.writerows(default_formats)
            except (OSError, ValueError, RuntimeError) as e:
                logger.error(f"Cannot create default study_formats.csv: {e}")
            formats = default_formats
        else:
            try:
                with open(filepath, mode='r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None)  
                    for row in reader:
                        if len(row) >= 2:
                            formats.append((row[0].strip(), row[1].strip()))
            except (OSError, ValueError, RuntimeError) as e:
                logger.error(f"Error reading {filepath}: {e}")
                formats = default_formats

        for item in formats:
            self.tree_formats.insert("", tk.END, values=item)

    def on_format_double_click(self, event):
        selected_item = self.tree_formats.selection()
        if not selected_item:
            return
        
        values = self.tree_formats.item(selected_item[0], "values")
        if values:
            study_name = values[0]
            self.ent_protocol.delete(0, tk.END)
            self.ent_protocol.insert(0, study_name)
            self.validate_inputs(None)

    def validate_inputs(self, event=None):
        subj = self.ent_subject.get().strip()
        prot = self.ent_protocol.get().strip()
        
        if subj:
            self.ent_subject.config(highlightbackground=COLOR_SUCCESS, highlightcolor=COLOR_SUCCESS, highlightthickness=1)
        else:
            self.ent_subject.config(highlightbackground=COLOR_DANGER, highlightcolor=COLOR_DANGER, highlightthickness=1)

        if prot:
            self.ent_protocol.config(highlightbackground=COLOR_SUCCESS, highlightcolor=COLOR_SUCCESS, highlightthickness=1)
        else:
            self.ent_protocol.config(highlightbackground=COLOR_DANGER, highlightcolor=COLOR_DANGER, highlightthickness=1)

        if subj and prot:
            out_folder_name = f"{Path(self.input_dir).name}_DeID_{subj}"
            self.output_dir = os.path.join(str(Path(self.input_dir).parent), out_folder_name)
            self.lbl_path_preview.config(text=f"ตำแหน่งบันทึกไฟล์ส่งออก:\n{self.output_dir}", fg=COLOR_SECONDARY)
        else:
            self.lbl_path_preview.config(text="ตำแหน่งบันทึกไฟล์ส่งออก: (กรุณากรอกรหัสให้ครบก่อน)", fg="#94A3B8")

    # ==========================================
    # STAGE 3: ดำเนินการเสร็จสิ้น & ตารางสรุปเปรียบเทียบ
    # ==========================================
    def _build_stage3(self):
        frame = tk.Frame(self.workstage, bg=COLOR_BG_LIGHT)
        self.stage_frames[3] = frame

        self.card_status = tk.Frame(frame, bg="#E8F5E9", bd=1, relief=tk.SOLID, padx=15, pady=12)
        self.card_status.pack(fill=tk.X, pady=(0, 15))
        
        self.lbl_summary_title = tk.Label(self.card_status, text="✅ แปลงข้อมูลสำเร็จเสร็จสิ้นเรียบร้อย!", font=("Segoe UI", 12, "bold"), fg="#1B5E20", bg="#E8F5E9")
        self.lbl_summary_title.pack(anchor="w")
        
        self.lbl_summary_details = tk.Label(self.card_status, text="-", font=("Segoe UI", 10), fg="#2E7D32", bg="#E8F5E9", justify=tk.LEFT)
        self.lbl_summary_details.pack(anchor="w", pady=(5, 0))

        tbl_frame = tk.LabelFrame(frame, text=" ตารางเปรียบเทียบค่าพารามิเตอร์ของระบบก่อน-หลังแปลงข้อมูล (Before vs After) ", 
                                font=("Segoe UI", 10, "bold"), bg=COLOR_CARD_BG, fg=COLOR_SECONDARY, bd=1, relief=tk.SOLID)
        tbl_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("tag", "orig", "mod")
        self.tree_comp = ttk.Treeview(tbl_frame, columns=cols, show="headings")
        self.tree_comp.heading("tag", text="คุณลักษณะของ DICOM TAG")
        self.tree_comp.heading("orig", text="ข้อมูลต้นฉบับดั้งเดิม (Before)")
        self.tree_comp.heading("mod", text="ข้อมูลที่ได้รับการปกปิด (After)")
        
        self.tree_comp.column("tag", width=180, anchor=tk.W)
        self.tree_comp.column("orig", width=320, anchor=tk.W)
        self.tree_comp.column("mod", width=320, anchor=tk.W)

        scroller = ttk.Scrollbar(tbl_frame, orient=tk.VERTICAL, command=self.tree_comp.yview)
        self.tree_comp.configure(yscrollcommand=scroller.set)
        scroller.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_comp.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def run_deidentification(self):
        subj = self.ent_subject.get().strip()
        prot = self.ent_protocol.get().strip()
        
        # ดึงสถานะปัจจุบันของ Checkbox
        clear_age = self.var_clear_age.get()
        clear_sex = self.var_clear_sex.get()
        
        progress_win = tk.Toplevel(self.root)
        progress_win.title("กำลังรันการ De-ID...")
        progress_win.geometry("420x130")
        progress_win.configure(bg=COLOR_BG_LIGHT)
        progress_win.attributes('-topmost', True)
        progress_win.grab_set()
        
        lbl_info = tk.Label(progress_win, text="กำลังประมวลผล De-ID ในข้อมูลภาพ...", font=("Segoe UI", 10), bg=COLOR_BG_LIGHT)
        lbl_info.pack(pady=(15, 5))
        
        pbar = ttk.Progressbar(progress_win, orient=tk.HORIZONTAL, length=320, mode='determinate')
        pbar.pack(pady=5)
        
        def update_progress(current, total, msg):
            if not progress_win.winfo_exists():
                return
            if current == 1 or current == total or current % 50 == 0:
                pct = int((current / total) * 100) if total > 0 else 0
                pbar['value'] = pct
                lbl_info.config(text=f"กำลังประมวลผล: {current} / {total} ไฟล์")
                progress_win.update_idletasks()

        self.root.update_idletasks()
        
        # ส่งผ่านตัวแปรการปิดบังอายุและเพศเข้าสู่ Loop ระดับโฟลเดอร์แบบ Multithreading
        result = self.folder_processor.process(
            self.input_dir, self.output_dir, subj, prot, 
            clear_sex=clear_sex, clear_age=clear_age, 
            progress_callback=update_progress
        )
        
        if progress_win.winfo_exists():
            progress_win.grab_release()
            progress_win.destroy()

        self.lbl_summary_details.config(
            text=f"แปลงผ่านการรับรองและตรวจ QC สำเร็จ: {result.success_count} ไฟล์ | ข้ามไฟล์/รายงาน: {result.skip_count} ไฟล์\n"
                f"ไม่ผ่านระบบตรวจสอบโครงสร้าง: {result.error_count} ไฟล์ | ไม่ผ่านเกณฑ์ควบคุมมาตรฐาน QC (ถูกทำลายทิ้ง): {result.qc_failed_count} ไฟล์\n"
                f"โฟลเดอร์ผลลัพธ์ใหม่เก็บไว้ที่: {self.output_dir}"
        )

        for idx_row in self.tree_comp.get_children():
            self.tree_comp.delete(idx_row)

        orig_dob = self.patient_info.PatientBirthDate
        dob_after = "ว่างเปล่า / ลบทิ้ง"
        if orig_dob and len(orig_dob) >= 4 and orig_dob != 'ไม่พบข้อมูล / ว่างเปล่า':
            dob_after = f"{orig_dob[:4]}0101"

        # ปรับการแสดงผลของตารางเปรียบเทียบ (Before vs After) ตามที่เลือกจริง
        sex_after_display = "ว่างเปล่า / ลบทิ้ง" if clear_sex else f"{self.patient_info.PatientSex} (คงค่าเดิมไว้)"
        age_after_display = "ว่างเปล่า / ลบทิ้ง" if clear_age else f"{self.patient_info.PatientAge} (คงค่าเดิมไว้)"

        comparison_rows = [
            ("Patient Name", self.patient_info.PatientName, subj),
            ("Patient ID", self.patient_info.PatientID, prot),
            ("Patient Birth Date", orig_dob, dob_after),
            ("Patient Sex", self.patient_info.PatientSex, sex_after_display),
            ("Patient Age", self.patient_info.PatientAge, age_after_display),
            ("Study Date", self.patient_info.StudyDate, f"{self.patient_info.StudyDate} (คงไว้ตามมาตรฐานการจัดเก็บ)"),
            ("Institution Name", self.patient_info.InstitutionName, prot),
            ("Institution Address", self.patient_info.InstitutionAddress, "ว่างเปล่า / ลบทิ้ง"),
            ("Referring Physician", self.patient_info.ReferringPhysicianName, prot),
            ("Performing Physician", self.patient_info.PerformingPhysicianName, "ว่างเปล่า / ลบทิ้ง"),
            ("Annotation Layers", "(อาจพบลายเส้นพิกเซลหรือกล่องข้อความบรรยาย)", "(ลบทิ้งทั้งหมดผ่าน Graphic Annotation Sequence)")
        ]

        for item in comparison_rows:
            self.tree_comp.insert("", tk.END, values=item)

        if result.qc_failed_count > 0:
            details_str = "\n\n".join(result.failed_files_details)
            messagebox.showwarning("ตรวจสอบความเข้ากันได้", 
                                f"คำเตือน: มีไฟล์จำนวน {result.qc_failed_count} ไฟล์ที่ไม่ผ่านการทำ QC และถูกลบทิ้งจากปลายทาง\n\nรายละเอียดข้อผิดพลาดเพิ่มเติม:\n{details_str}")

    # ==========================================
    # Controller Logic: ทิศทางการสลับหน้าจอ (Wizard Navigation)
    # ==========================================
    def on_back(self):
        if self.current_step == 2:
            self.show_step(1)

    def on_next(self):
        if self.current_step == 1:
            if not self.input_dir:
                messagebox.showwarning("กรุณาเลือกไฟล์", "กรุณาทำการเลือกโฟลเดอร์ที่เก็บ DICOM ต้นฉบับเพื่อสแกนโครงสร้างข้อมูลก่อน")
                return
            self.show_step(2)
            self.validate_inputs()
        elif self.current_step == 2:
            subj = self.ent_subject.get().strip()
            prot = self.ent_protocol.get().strip()
            if not subj or not prot:
                messagebox.showwarning("กรอกข้อมูลให้ครบถ้วน", "กรุณาระบุ Subject Number และ Protocol Number ก่อนเริ่มขั้นตอนแปลงข้อมูล")
                return
            self.show_step(3)
            self.run_deidentification()
        elif self.current_step == 3:
            self.input_dir = ""
            self.output_dir = ""
            self.ent_folder.delete(0, tk.END)
            self.ent_subject.delete(0, tk.END)
            self.ent_protocol.delete(0, tk.END)
            # รีเซ็ตค่าตัวเลือกกลับเป็น Default (ลบ) สำหรับโฟลเดอร์ถัดไป
            self.var_clear_age.set(True)
            self.var_clear_sex.set(True)
            
            for i in self.tree_series.get_children():
                self.tree_series.delete(i)
            for widget in self.left_card.winfo_children():
                widget.destroy()
                
            self.show_step(1)

if __name__ == "__main__":
    _initialize_dynamic_config()
    root = tk.Tk()
    app = ModernDICOMDeIDApp(root)
    root.mainloop()