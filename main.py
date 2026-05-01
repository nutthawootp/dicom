import os
import csv
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import pydicom
from pydicom.errors import InvalidDicomError
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

# ==========================================
# 1. Configuration & Constants
# ==========================================
class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR

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
    TAGS_TO_CLEAR = ['InstitutionAddress', 'PerformingPhysicianName', 'PatientAge', 'PatientSex']
    TAGS_TO_REMOVE_RANGES = [(0x5000, 0x50FF), (0x6000, 0x60FF)]
    SERIES_TO_SKIP = {'99999'}
    SECONDARY_CAPTURE_UID = '1.2.840.10008.5.1.4.1.1.7'
    FORMATS_FILE = 'study_formats.csv'  # เพิ่มชื่อไฟล์สำหรับเก็บ Format คู่มือ

CONFIG = DeIDConfig()

# ==========================================
# 2. Data Models
# ==========================================
@dataclass
class PatientInfo:
    PatientName: str = 'Not Found / Empty'
    PatientID: str = 'Not Found / Empty'
    PatientBirthDate: str = 'Not Found / Empty'
    PatientSex: str = 'Not Found / Empty'
    PatientAge: str = 'Not Found / Empty'
    ReferringPhysicianName: str = 'Not Found / Empty'
    PerformingPhysicianName: str = 'Not Found / Empty'
    InstitutionName: str = 'Not Found / Empty'
    InstitutionAddress: str = 'Not Found / Empty'

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
    failed_files_details: List[str] = field(default_factory=list)

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
    def read_dicom_metadata(filepath: str) -> Optional[pydicom.Dataset]:
        try:
            return pydicom.dcmread(filepath, stop_before_pixels=True)
        except InvalidDicomError:
            logger.error(f"Invalid DICOM file: {filepath}")
            return None
        except Exception as e:
            logger.error(f"Error reading {filepath}: {str(e)}")
            return None

    @staticmethod
    def read_dicom_full(filepath: str) -> Optional[pydicom.Dataset]:
        try:
            return pydicom.dcmread(filepath)
        except InvalidDicomError:
            logger.error(f"Invalid DICOM file: {filepath}")
            return None
        except Exception as e:
            logger.error(f"Error reading {filepath}: {str(e)}")
            return None
    
    @staticmethod
    def get_attribute_safe(dataset: pydicom.Dataset, attr: str, default: str = '') -> str:
        try:
            value = getattr(dataset, attr, default)
            return str(value) if value else default
        except Exception as e:
            logger.debug(f"Could not retrieve {attr}: {e}")
            return default

    @staticmethod
    def run_quality_control(filepath: str, expected_subject: str, expected_protocol: str) -> Tuple[bool, str]:
        try:
            ds = pydicom.dcmread(filepath)
            
            if 'PixelData' not in ds:
                return False, "Missing Pixel Data (7FE0,0010)"
                
            if str(getattr(ds, 'PatientName', '')) != expected_subject:
                return False, "Patient Name was not properly replaced"
                
            if str(getattr(ds, 'PatientID', '')) != expected_protocol:
                return False, "Patient ID was not properly replaced"
                
            return True, "QC Passed"
        except Exception as e:
            return False, f"File corrupted after save ({str(e)})"

class DICOMScanner:
    def __init__(self, processor: DICOMProcessor):
        self.processor = processor
    
    def scan_folder(self, folder_path: str, progress_callback: Callable[[int, int, str], None] = None) -> Tuple[PatientInfo, Dict[str, SeriesData]]: # pyright: ignore[reportArgumentType]
        patient_info = PatientInfo()
        series_info = {}
        found_patient_info = False
        
        logger.info(f"Scanning folder: {folder_path}")
        
        total_files = sum(len(files) for _, _, files in os.walk(folder_path))
        processed_count = 0
        
        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                processed_count += 1
                filepath = os.path.join(root, filename)
                
                if progress_callback:
                    progress_callback(processed_count, total_files, f"Reading: {filename}")
                
                if not self.processor.is_valid_dicom_file(filepath):
                    continue
                
                dataset = self.processor.read_dicom_metadata(filepath)
                if not dataset:
                    continue
                
                if not found_patient_info:
                    patient_info = self._extract_patient_info(dataset)
                    found_patient_info = True
                
                self._extract_series_info(dataset, series_info)
        
        logger.info(f"Scan complete. Found {len(series_info)} series")
        return patient_info, series_info
    
    @staticmethod
    def _extract_patient_info(dataset: pydicom.Dataset) -> PatientInfo:
        processor = DICOMProcessor()
        return PatientInfo(
            PatientName=processor.get_attribute_safe(dataset, 'PatientName', 'Not Found / Empty'),
            PatientID=processor.get_attribute_safe(dataset, 'PatientID', 'Not Found / Empty'),
            PatientBirthDate=processor.get_attribute_safe(dataset, 'PatientBirthDate', 'Not Found / Empty'),
            PatientSex=processor.get_attribute_safe(dataset, 'PatientSex', 'Not Found / Empty'),
            PatientAge=processor.get_attribute_safe(dataset, 'PatientAge', 'Not Found / Empty'),
            ReferringPhysicianName=processor.get_attribute_safe(dataset, 'ReferringPhysicianName', 'Not Found / Empty'),
            PerformingPhysicianName=processor.get_attribute_safe(dataset, 'PerformingPhysicianName', 'Not Found / Empty'),
            InstitutionName=processor.get_attribute_safe(dataset, 'InstitutionName', 'Not Found / Empty'),
            InstitutionAddress=processor.get_attribute_safe(dataset, 'InstitutionAddress', 'Not Found / Empty')
        )
    
    @staticmethod
    def _extract_series_info(dataset: pydicom.Dataset, series_info: Dict):
        processor = DICOMProcessor()
        s_num = processor.get_attribute_safe(dataset, 'SeriesNumber', 'Unknown')
        s_desc = processor.get_attribute_safe(dataset, 'SeriesDescription', 'No Description')
        spacing = processor.get_attribute_safe(dataset, 'SpacingBetweenSlices', 'Not Found')
        thickness = processor.get_attribute_safe(dataset, 'SliceThickness', 'Not Found')
        
        if s_num not in series_info:
            series_info[s_num] = SeriesData(s_desc, set(), set())
        
        series_info[s_num].spacing.add(spacing)
        series_info[s_num].thickness.add(thickness)

class DICOMDeIdentifier:
    def __init__(self, processor: DICOMProcessor):
        self.processor = processor
    
    def should_skip_file(self, dataset: pydicom.Dataset) -> Optional[str]:
        sop_class = self.processor.get_attribute_safe(dataset, 'SOPClassUID', '')
        if sop_class == CONFIG.SECONDARY_CAPTURE_UID:
            return "Secondary Capture (Report)"
        
        series_num = self.processor.get_attribute_safe(dataset, 'SeriesNumber', '')
        if series_num in CONFIG.SERIES_TO_SKIP:
            return f"Series {series_num}"
        
        return None
    
    def deidentify(self, dataset: pydicom.Dataset, subject_id: str, protocol_number: str) -> None:
        for tag in CONFIG.TAGS_TO_CLEAR:
            if tag in dataset:
                dataset[tag].value = ''
        
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
    
    def process(self, input_folder: str, output_folder: str, subject_id: str, protocol_number: str, progress_callback: Callable[[int, int, str], None] = None) -> ProcessResult: # pyright: ignore[reportArgumentType]
        result = ProcessResult()
        logger.info(f"Starting de-identification process for {subject_id}")
        
        total_files = sum(len(files) for _, _, files in os.walk(input_folder))
        processed_count = 0
        
        for root, dirs, files in os.walk(input_folder):
            output_dir = self._create_output_dir(root, input_folder, output_folder)
            
            for filename in files:
                processed_count += 1
                input_path = os.path.join(root, filename)
                
                if progress_callback:
                    progress_callback(processed_count, total_files, f"Processing: {filename}")
                
                if not self.processor.is_valid_dicom_file(input_path):
                    result.skip_count += 1
                    continue
                
                meta_dataset = self.processor.read_dicom_metadata(input_path)
                if not meta_dataset:
                    result.error_count += 1
                    continue
                
                skip_reason = self.deidentifier.should_skip_file(meta_dataset)
                if skip_reason:
                    logger.info(f"Skipped {filename}: {skip_reason}")
                    result.skip_count += 1
                    continue
                
                max_retries = 3
                process_success = False
                last_error_message = ""
                
                for attempt in range(1, max_retries + 1):
                    try:
                        dataset = self.processor.read_dicom_full(input_path)
                        if not dataset:
                            last_error_message = "Cannot fully read DICOM file"
                            break 
                        
                        self.deidentifier.deidentify(dataset, subject_id, protocol_number)
                        output_path = os.path.join(output_dir, f"{subject_id}_{filename}")
                        dataset.save_as(output_path)
                        
                        is_qc_passed, qc_message = self.processor.run_quality_control(output_path, subject_id, protocol_number)
                        
                        if is_qc_passed:
                            process_success = True
                            break 
                        else:
                            last_error_message = f"QC Failed: {qc_message}"
                            if os.path.exists(output_path):
                                os.remove(output_path)
                                
                    except Exception as e:
                        last_error_message = f"Error: {str(e)}"
                        output_path = os.path.join(output_dir, f"{subject_id}_{filename}")
                        if os.path.exists(output_path):
                            os.remove(output_path)
                
                if process_success:
                    result.success_count += 1
                else:
                    if "Cannot fully read" in last_error_message:
                        result.error_count += 1
                    else:
                        result.qc_failed_count += 1
                        result.failed_files_details.append(
                            f"📁 Path: {input_path}\n❌ Reason: {last_error_message}"
                        )
        
        return result
    
    @staticmethod
    def _create_output_dir(root: str, input_folder: str, output_folder: str) -> str:
        rel_path = os.path.relpath(root, input_folder)
        output_dir = os.path.join(output_folder, rel_path)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return output_dir

# ==========================================
# 4. UI Classes 
# ==========================================

class ProgressDialog:
    def __init__(self, parent, title="กำลังทำงาน..."):
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("450x150")
        self.top.attributes('-topmost', True)
        self.top.protocol("WM_DELETE_WINDOW", lambda: None) 
        
        tk.Label(self.top, text="กรุณารอสักครู่...", font=("Arial", 11, "bold")).pack(pady=(15, 5))
        
        self.progress = ttk.Progressbar(self.top, orient=tk.HORIZONTAL, length=380, mode='determinate')
        self.progress.pack(pady=5)
        
        self.lbl_percent = tk.Label(self.top, text="0% (0/0)", font=("Arial", 10, "bold"), fg="blue")
        self.lbl_percent.pack()
        
        self.lbl_status = tk.Label(self.top, text="Initializing...", font=("Arial", 9), fg="gray")
        self.lbl_status.pack(pady=(5, 10))
        
        self.top.update()

    def update_progress(self, current: int, total: int, message: str):
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress['value'] = percent
        self.lbl_percent.config(text=f"{percent}%  ({current} / {total} files)")
        
        display_msg = message if len(message) < 55 else message[:52] + "..."
        self.lbl_status.config(text=display_msg)
        self.top.update()
        
    def close(self):
        self.top.destroy()


class BaseDialog:
    def __init__(self, parent, title: str, geometry: str = "600x400"):
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry(geometry)
        self.top.attributes('-topmost', True)
        self.top.focus_force()
        self.action = None
    
    def make_modal(self):
        self.top.grab_set()
        self.top.transient()

class DataPreviewDialog(BaseDialog):
    def __init__(self, parent, patient_info: PatientInfo, series_info: Dict[str, SeriesData]):
        super().__init__(parent, "ตรวจสอบข้อมูล DICOM ต้นฉบับ", "600x680")
        self.patient_info = patient_info
        self.series_info = series_info
        self._build_ui()
        self.make_modal()
        parent.wait_window(self.top)
    
    def _build_ui(self):
        tk.Label(self.top, text="กรุณาตรวจสอบข้อมูลก่อนดำเนินการ", font=('Arial', 11, 'bold')).pack(pady=10)
        self._create_patient_info_frame()
        self._create_series_info_frame()
        self._create_button_frame()
    
    def _create_patient_info_frame(self):
        info_frame = tk.LabelFrame(self.top, text=" ข้อมูลต้นฉบับจากไฟล์ DICOM ", font=('Arial', 10, 'bold'), padx=10, pady=5)
        info_frame.pack(fill=tk.X, padx=15, pady=5)
        
        tags_display = [
            ("(0010,0010) Patient Name", self.patient_info.PatientName),
            ("(0010,0020) Patient ID", self.patient_info.PatientID),
            ("(0010,0030) Patient Birth Date", self.patient_info.PatientBirthDate),
            ("(0010,0040) Patient Sex", self.patient_info.PatientSex),
            ("(0010,1010) Patient Age", self.patient_info.PatientAge),
            ("(0008,0080) Institution Name", self.patient_info.InstitutionName),
            ("(0008,0081) Institution Address", self.patient_info.InstitutionAddress),
            ("(0008,0090) Ref. Physician", self.patient_info.ReferringPhysicianName),
            ("(0008,1050) Perf. Physician", self.patient_info.PerformingPhysicianName)
        ]
        
        for label, value in tags_display:
            self._create_info_row(info_frame, label, value)
    
    @staticmethod
    def _create_info_row(parent, label: str, value: str):
        row_frame = tk.Frame(parent)
        row_frame.pack(fill=tk.X, pady=1)
        tk.Label(row_frame, text=f"{label}:", width=25, anchor="e", font=('Arial', 9)).pack(side=tk.LEFT)
        display_value = value if len(value) < 35 else value[:32] + "..."
        tk.Label(row_frame, text=f" {display_value}", anchor="w", fg="blue", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    def _create_series_info_frame(self):
        series_frame = tk.LabelFrame(self.top, text=" ข้อมูล Series ", font=('Arial', 10, 'bold'), padx=10, pady=5)
        series_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        scrollbar = tk.Scrollbar(series_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        series_text = tk.Text(series_frame, height=8, width=50, yscrollcommand=scrollbar.set, font=('Arial', 9), bg="#f9f9f9")
        series_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=series_text.yview)
        
        self._populate_series_info(series_text)
        series_text.config(state=tk.DISABLED)
    
    def _populate_series_info(self, text_widget):
        if not self.series_info:
            text_widget.insert(tk.END, "ไม่พบข้อมูล Series\n")
        else:
            sorted_series = sorted(self.series_info.keys(), key=lambda x: float(x) if x.replace('.', '', 1).isdigit() else float('inf'))
            for s_num in sorted_series:
                data = self.series_info[s_num]
                spacing_str = ", ".join(sorted(list(data.spacing)))
                thickness_str = ", ".join(sorted(list(data.thickness)))
                
                line = f"Series {s_num}: {data.description}\n"
                line += f"  ├ Spacing: {spacing_str}\n"
                line += f"  └ Thickness: {thickness_str}\n\n"
                text_widget.insert(tk.END, line)
    
    def _create_button_frame(self):
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Close", command=self.on_close, width=18, bg="#f44336", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="De-Identification ➔", command=self.on_deidentify, width=18, bg="#2196F3", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
    
    def on_close(self):
        self.action = 'close'
        self.top.destroy()
    
    def on_deidentify(self):
        self.action = 'de_identify'
        self.top.destroy()


class DataEntryDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "กำหนดข้อมูล De-identification", "850x600")
        self.subject_id = None
        self.protocol_number = None
        self._build_ui()
        self.make_modal()
        parent.wait_window(self.top)
    
    def _load_study_formats(self) -> list:
        """ฟังก์ชันสำหรับดึงข้อมูล Format จากไฟล์ CSV"""
        filepath = CONFIG.FORMATS_FILE
        # ข้อมูลตั้งต้นในกรณีที่ยังไม่มีไฟล์
        default_formats = [
            ("20210033", "Study number 3 หลัก ('933') + Site number 5 หลัก ('62001') + participant number 3 หลัก (93362001XXX)"),
            ("OP-1250-301", "6606-6XXX"),
            ("OP-1250-302", "6606-7XXX"),
            ("BNT327-06", "Site number + participant number (764-01-XXXX)"),
            ("BO43249", "XXXXX"),
            ("CT-P51 3.1", "Site number + participant number (5602XXXX)"),
            ("MB12-C-02-24", "Site number + participant number (XXXXXXXXX)"),
            ("MK-2400-001", "Site 4 หลัก (0887)+ Screening 5 หลัก (0887-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-1022-016", "Site 4 หลัก (2924)+ Screening 5 หลัก (2924-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-2870-009", "Site 4 หลัก (4006)+ Screening 5 หลัก (4006-YYYYY) หรือ Randomization 6 หลัก"),
            ("MK-2870-023", "Site 4 หลัก (2300)+ Screening 5 หลัก (2300-YYYYY) หรือ Randomization 6 หลัก"),
            ("V940-011", "Site number 4 หลัก + Screening number 5 หลัก (3002-YYYYY)"),
            ("MO41552", "Site number + participant number (501243-XXXX)"),
            ("TAS-6417-301", "Site number + participant number (800-XXX)"),
        ]
        
        # ถ้าไม่มีไฟล์ ให้สร้างไฟล์ใหม่ขึ้นมาและใส่ Default ลงไป
        if not os.path.exists(filepath):
            try:
                # ใช้ utf-8-sig เพื่อให้เปิดใน Excel แล้วภาษาไทยไม่เพี้ยน
                with open(filepath, mode='w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["StudyName", "Format"])
                    writer.writerows(default_formats)
            except Exception as e:
                logger.error(f"Cannot create default study_formats.csv: {e}")
            return default_formats

        # ถ้ามีไฟล์อยู่แล้ว ให้อ่านจากไฟล์ขึ้นมาแสดง
        formats = []
        try:
            with open(filepath, mode='r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader, None)  # ข้าม Header
                for row in reader:
                    if len(row) >= 2:
                        formats.append((row[0].strip(), row[1].strip()))
        except Exception as e:
            logger.error(f"Error reading {filepath}: {e}")
            return default_formats
            
        return formats

    def _build_ui(self):
        tk.Label(self.top, text="คู่มือรูปแบบการกำหนดรหัส", font=('Arial', 11, 'bold')).pack(pady=10)
        self._create_study_table()
        self._create_entry_form()
        self._create_button_frame()
    
    def _create_study_table(self):
        table_frame = tk.Frame(self.top, padx=15)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("StudyName", "Format")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        self.tree.heading("StudyName", text="Study Name")
        self.tree.heading("Format", text="Participant ID Format")
        self.tree.column("StudyName", width=150, anchor=tk.W)
        self.tree.column("Format", width=650, anchor=tk.W)
        
        # ดึงข้อมูลผ่านฟังก์ชันที่เขียนไว้
        study_formats = self._load_study_formats()
        
        for item in study_formats:
            self.tree.insert("", tk.END, values=item)
        
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
    def _create_entry_form(self):
        form_frame = tk.Frame(self.top, pady=15)
        form_frame.pack()
        
        tk.Label(form_frame, text="Subject Number:", font=('Arial', 10, 'bold')).grid(row=0, column=0, padx=10, pady=5, sticky=tk.E)
        self.subj_entry = tk.Entry(form_frame, width=40, font=('Arial', 10))
        self.subj_entry.grid(row=0, column=1, pady=5)
        self.subj_entry.focus()
        
        tk.Label(form_frame, text="Protocol Number:", font=('Arial', 10, 'bold')).grid(row=1, column=0, padx=10, pady=5, sticky=tk.E)
        self.prot_entry = tk.Entry(form_frame, width=40, font=('Arial', 10))
        self.prot_entry.grid(row=1, column=1, pady=5)
    
    def _create_button_frame(self):
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=15)
        
        tk.Button(btn_frame, text="⬅ Back", command=self.on_back, width=15, bg="#9E9E9E", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="OK ✓", command=self.on_ok, width=15, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)
    
    def on_back(self):
        self.action = 'back'
        self.top.destroy()
    
    def on_ok(self):
        self.subject_id = self.subj_entry.get().strip()
        self.protocol_number = self.prot_entry.get().strip()
        
        if not self.subject_id or not self.protocol_number:
            messagebox.showwarning("Input Error", "Please fill both fields")
            return
        
        self.action = 'ok'
        self.top.destroy()

class SummaryDialog:
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


class FinalResultDialog(BaseDialog):
    def __init__(self, parent, result: ProcessResult, output_dir: str, original_info: PatientInfo, new_subject_id: str, new_protocol: str):
        super().__init__(parent, "กระบวนการเสร็จสมบูรณ์ (Process Completed)", "750x700")
        self.result = result
        self.output_dir = output_dir
        self.original_info = original_info
        self.new_subject_id = new_subject_id
        self.new_protocol = new_protocol
        
        self._build_ui()
        self.make_modal()
        parent.wait_window(self.top)
        
    def _build_ui(self):
        header_frame = tk.Frame(self.top, bg="#E8F5E9", pady=15)
        header_frame.pack(fill=tk.X)
        tk.Label(header_frame, text="✅ De-identification สำเร็จเรียบร้อย!", font=("Arial", 14, "bold"), fg="#2E7D32", bg="#E8F5E9").pack()
        
        stats_text = f"แปลงผ่าน QC สำเร็จ: {self.result.success_count} | ข้าม Report & Series: {self.result.skip_count}\nพบข้อผิดพลาด/ไฟล์เสีย: {self.result.error_count} | ไม่ผ่าน QC (ลบทิ้ง): {self.result.qc_failed_count}"
        tk.Label(header_frame, text=stats_text, font=("Arial", 11), bg="#E8F5E9").pack(pady=5)
        
        if self.result.qc_failed_count > 0:
            tk.Button(header_frame, text="⚠️ ดูรายละเอียดไฟล์ที่ไม่ผ่าน QC", 
                      command=self.show_failed_files, 
                      bg="#FF9800", fg="white", font=('Arial', 10, 'bold')).pack(pady=5)
                      
        tk.Label(header_frame, text=f"📂 บันทึกไว้ที่: {self.output_dir}", font=("Arial", 9), bg="#E8F5E9").pack(pady=(5,0))

        tk.Label(self.top, text="ตารางเปรียบเทียบค่าพารามิเตอร์ (Before vs After)", font=('Arial', 11, 'bold')).pack(pady=10)

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

        dob_after = "(ว่างเปล่า / ลบทิ้ง)"
        orig_dob = self.original_info.PatientBirthDate
        if orig_dob and len(orig_dob) >= 4 and orig_dob != 'Not Found / Empty':
            dob_after = f"{orig_dob[:4]}0101"

        comparison_data = [
            ("Patient Name", self.original_info.PatientName, self.new_subject_id),
            ("Patient ID", self.original_info.PatientID, self.new_protocol),
            ("Patient Birth Date", orig_dob, dob_after),
            ("Patient Sex", self.original_info.PatientSex, "(ว่างเปล่า / ลบทิ้ง)"), 
            ("Patient Age", self.original_info.PatientAge, "(ว่างเปล่า / ลบทิ้ง)"), 
            ("Institution Name", self.original_info.InstitutionName, self.new_protocol),
            ("Institution Address", self.original_info.InstitutionAddress, "(ว่างเปล่า / ลบทิ้ง)"),
            ("Referring Physician", self.original_info.ReferringPhysicianName, self.new_protocol),
            ("Performing Physician", self.original_info.PerformingPhysicianName, "(ว่างเปล่า / ลบทิ้ง)"),
            ("Annotations", "(อาจมีเส้นวาด หรือ กล่องข้อความ)", "(ลบทิ้งทั้งหมด)")
        ]

        for item in comparison_data:
            tree.insert("", tk.END, values=item)

        tree.pack(fill=tk.BOTH, expand=True)

        tk.Button(self.top, text="Finish (เสร็จสิ้น)", command=self.top.destroy, width=20, bg="#4CAF50", fg="white", font=('Arial', 11, 'bold')).pack(pady=20)

    def show_failed_files(self):
        fail_window = tk.Toplevel(self.top)
        fail_window.title("รายละเอียดไฟล์ที่ไม่ผ่าน QC (Failed Files Details)")
        fail_window.geometry("700x400")
        fail_window.attributes('-topmost', True)
        
        tk.Label(fail_window, text=f"รายการไฟล์ที่ไม่ผ่านการ QC ทั้ง {len(self.result.failed_files_details)} ไฟล์", 
                 font=('Arial', 11, 'bold'), fg="red").pack(pady=10)
                 
        text_area = tk.Text(fail_window, font=('Courier', 9), bg="#FFF3E0", padx=10, pady=10)
        text_area.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        scrollbar = tk.Scrollbar(text_area)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_area.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=text_area.yview)
        
        for details in self.result.failed_files_details:
            text_area.insert(tk.END, details + "\n" + "-"*60 + "\n")
            
        text_area.config(state=tk.DISABLED)
        
        tk.Button(fail_window, text="ปิดหน้าต่าง", command=fail_window.destroy, 
                  width=15, bg="#9E9E9E", fg="white").pack(pady=10)


# ==========================================
# 5. Main Application
# ==========================================
class DICOMDeIDApplication:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        
        self.processor = DICOMProcessor()
        self.scanner = DICOMScanner(self.processor)
        self.deidentifier = DICOMDeIdentifier(self.processor)
        self.folder_processor = DICOMFolderProcessor(self.deidentifier)
    
    def run(self):
        try:
            self.main_loop()
        except Exception as e:
            logger.exception("Application error")
            messagebox.showerror("Error", f"Application error: {str(e)}")
        finally:
            self.root.destroy()
    
    def main_loop(self):
        while True:
            input_dir = filedialog.askdirectory(title="Step 1: Select DICOM folder")
            
            if not input_dir:
                break
            
            scan_prog = ProgressDialog(self.root, title="กำลังสแกนข้อมูล DICOM ต้นฉบับ...")
            patient_info, series_info = self.scanner.scan_folder(input_dir, progress_callback=scan_prog.update_progress)
            scan_prog.close()
            
            if not self._process_workflow(input_dir, patient_info, series_info):
                break
    
    def _process_workflow(self, input_dir: str, patient_info: PatientInfo, series_info: Dict) -> bool:
        while True:
            preview = DataPreviewDialog(self.root, patient_info, series_info)
            
            if preview.action != 'de_identify':
                return False
            
            entry = DataEntryDialog(self.root)
            
            if entry.action == 'back':
                continue
            elif entry.action == 'ok':
                return self._execute_deidentification(input_dir, patient_info, entry.subject_id, entry.protocol_number) # pyright: ignore[reportArgumentType]
            else:
                return False
    
    def _execute_deidentification(self, input_dir: str, patient_info: PatientInfo, 
                                    subject_id: str, protocol_number: str) -> bool:
        output_dir = f"{input_dir}_DeID_{subject_id}"
        
        process_prog = ProgressDialog(self.root, title="กำลังทำ De-identification (อย่าปิดโปรแกรม)...")
        result = self.folder_processor.process(input_dir, output_dir, subject_id, protocol_number, progress_callback=process_prog.update_progress)
        process_prog.close() 
        
        FinalResultDialog(self.root, result, output_dir, patient_info, subject_id, protocol_number)
        
        return True


if __name__ == "__main__":
    app = DICOMDeIDApplication()
    app.run()