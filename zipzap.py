#!/usr/bin/env python3

import os
import sys
import zipfile
import logging
import json
import hashlib
import threading
import multiprocessing
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

class ProgressTracker:
    def __init__(self, progress_file='zipzap_progress.json'):
        self.progress_file = progress_file
        self.processed_files = set()
        self.pending_saves = set()
        self.load_progress()

    def load_progress(self):
        if Path(self.progress_file).exists():
            try:
                with open(self.progress_file, 'r') as f:
                    data = json.load(f)
                    self.processed_files = set(data.get('processed_files', []))
            except (json.JSONDecodeError, FileNotFoundError):
                self.processed_files = set()

    def save_progress(self):
        with open(self.progress_file, 'w') as f:
            json.dump({
                'processed_files': list(self.processed_files),
                'last_updated': datetime.now().isoformat()
            }, f, indent=2)

    def is_processed(self, file_path):
        file_hash = self.get_file_hash(file_path)
        return file_hash in self.processed_files

    def mark_processed(self, file_path):
        file_hash = self.get_file_hash(file_path)
        self.processed_files.add(file_hash)
        self.pending_saves.add(file_hash)

    def batch_save_progress(self):
        if self.pending_saves:
            self.save_progress()
            self.pending_saves.clear()

    def get_file_hash(self, file_path):
        return hashlib.md5(str(file_path).encode()).hexdigest()

    def clear_progress(self):
        self.processed_files.clear()
        self.pending_saves.clear()
        if Path(self.progress_file).exists():
            Path(self.progress_file).unlink()

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('zipzap.log')
        ]
    )

def extract_single_file_from_zip(args):
    """Extract a single file from a zip archive - used for intra-zip parallelization."""
    zip_path_str, member_info, extract_dir_str = args

    try:
        extract_dir = Path(extract_dir_str)
        target_path = extract_dir / member_info['filename']
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path_str, 'r', allowZip64=True) as zip_ref:
            with zip_ref.open(member_info['filename']) as source:
                with open(target_path, 'wb') as target:
                    while chunk := source.read(16384):
                        target.write(chunk)

        return True, member_info['filename'], None
    except Exception as e:
        return False, member_info['filename'], str(e)

def extract_zip_worker(zip_path_str, intra_zip_workers=1):
    """Worker function for multiprocessing - extracts a single zip file with optional intra-zip parallelization."""
    zip_path = Path(zip_path_str)
    zip_name = zip_path.stem
    extract_dir = zip_path.parent / zip_name

    try:
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r', allowZip64=True) as zip_ref:
            members = [m for m in zip_ref.infolist() if not m.is_dir()]

            # For large zip files with many files, use parallel extraction within the zip
            if len(members) > 20 and intra_zip_workers > 1:
                member_args = [
                    (str(zip_path), {'filename': m.filename}, str(extract_dir))
                    for m in members
                ]

                failed_files = []
                with ThreadPoolExecutor(max_workers=min(intra_zip_workers, len(members))) as executor:
                    futures = [executor.submit(extract_single_file_from_zip, args) for args in member_args]

                    for future in as_completed(futures):
                        success, filename, error = future.result()
                        if not success:
                            failed_files.append((filename, error))

                if failed_files:
                    error_msg = f"Failed to extract {len(failed_files)} files: {failed_files[:3]}"
                    return False, str(zip_path), error_msg
            else:
                # Sequential extraction for smaller zips
                for member in members:
                    source = zip_ref.open(member)
                    target_path = extract_dir / member.filename
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    with open(target_path, 'wb') as target:
                        while chunk := source.read(16384):
                            target.write(chunk)
                    source.close()

        zip_path.unlink()
        return True, str(zip_path), None

    except zipfile.BadZipFile:
        return False, str(zip_path), "Bad zip file"
    except PermissionError:
        return False, str(zip_path), "Permission denied"
    except Exception as e:
        return False, str(zip_path), str(e)

def extract_zip(zip_path, progress_tracker=None, progress_callback=None):
    """Extract a zip file to a folder with the same name as the zip file and delete the zip file."""
    zip_path = Path(zip_path)
    zip_name = zip_path.stem
    extract_dir = zip_path.parent / zip_name

    if progress_tracker and progress_tracker.is_processed(zip_path):
        logging.info(f"Skipping already processed file: {zip_path}")
        return True

    try:
        logging.info(f"Extracting {zip_path} to {extract_dir}")

        if progress_callback:
            progress_callback(f"Extracting {zip_path.name}")

        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r', allowZip64=True) as zip_ref:
            for member in zip_ref.infolist():
                if member.is_dir():
                    continue

                source = zip_ref.open(member)
                target_path = extract_dir / member.filename
                target_path.parent.mkdir(parents=True, exist_ok=True)

                with open(target_path, 'wb') as target:
                    while chunk := source.read(8192):
                        target.write(chunk)
                source.close()

        logging.info(f"Successfully extracted {zip_path} to {extract_dir}")

        zip_path.unlink()
        logging.info(f"Deleted {zip_path}")

        if progress_tracker:
            progress_tracker.mark_processed(zip_path)

        return True

    except zipfile.BadZipFile:
        logging.error(f"Bad zip file: {zip_path}")
        return False
    except PermissionError:
        logging.error(f"Permission denied: {zip_path}")
        return False
    except Exception as e:
        logging.error(f"Error processing {zip_path}: {e}")
        return False

def analyze_zip_files(zip_files):
    """Analyze zip files to determine optimal extraction strategy."""
    file_analysis = []

    for zip_path in zip_files:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_count = len([m for m in zip_ref.infolist() if not m.is_dir()])
                zip_size = zip_path.stat().st_size
                file_analysis.append({
                    'path': zip_path,
                    'file_count': file_count,
                    'size_mb': zip_size / (1024 * 1024),
                    'avg_file_size': zip_size / max(file_count, 1)
                })
        except Exception:
            file_analysis.append({
                'path': zip_path,
                'file_count': 1,
                'size_mb': 0,
                'avg_file_size': 0
            })

    return file_analysis

def scan_directory(directory, progress_tracker=None, progress_callback=None, stop_event=None, use_multiprocessing=True, max_workers=None, intra_zip_workers=4):
    """Recursively scan directory for zip files and extract them with intelligent strategy selection."""
    directory = Path(directory)

    if not directory.exists():
        logging.error(f"Directory does not exist: {directory}")
        return 0, 0

    if not directory.is_dir():
        logging.error(f"Path is not a directory: {directory}")
        return 0, 0

    logging.info(f"Scanning directory: {directory}")

    if progress_callback:
        progress_callback("Scanning for zip files...")

    zip_files = list(directory.rglob("*.zip"))

    if not zip_files:
        logging.info("No zip files found")
        return 0, 0

    if progress_tracker:
        zip_files = [zf for zf in zip_files if not progress_tracker.is_processed(zf)]
        if not zip_files:
            logging.info("All zip files already processed")
            return 0, 0

    logging.info(f"Found {len(zip_files)} zip files to process")

    if progress_callback:
        progress_callback("Analyzing zip files for optimal extraction...")

    file_analysis = analyze_zip_files(zip_files)

    # Determine extraction strategy based on analysis
    large_zips = [f for f in file_analysis if f['file_count'] > 20 and f['size_mb'] > 10]
    small_zips = [f for f in file_analysis if f not in large_zips]

    if not use_multiprocessing or len(zip_files) < 2:
        return _scan_directory_sequential([f['path'] for f in file_analysis], progress_tracker, progress_callback, stop_event)
    else:
        return _scan_directory_hybrid(large_zips, small_zips, progress_tracker, progress_callback, stop_event, max_workers, intra_zip_workers)

def _scan_directory_sequential(zip_files, progress_tracker, progress_callback, stop_event):
    """Sequential processing for small numbers of files or when multiprocessing is disabled."""
    success_count = 0
    processed_count = 0

    for i, zip_file in enumerate(zip_files):
        if stop_event and stop_event.is_set():
            logging.info("Operation cancelled by user")
            break

        if progress_callback:
            progress_callback(f"Processing {i+1}/{len(zip_files)}: {zip_file.name}")

        if extract_zip(zip_file, progress_tracker, progress_callback):
            success_count += 1
        processed_count += 1

        if progress_tracker and processed_count % 10 == 0:
            progress_tracker.batch_save_progress()

    if progress_tracker:
        progress_tracker.batch_save_progress()

    logging.info(f"Successfully processed {success_count}/{processed_count} zip files")
    return success_count, processed_count

def _scan_directory_hybrid(large_zips, small_zips, progress_tracker, progress_callback, stop_event, max_workers, intra_zip_workers):
    """Hybrid extraction strategy: parallel processing with intra-zip parallelization for large files."""
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), 8)

    success_count = 0
    processed_count = 0
    total_files = len(large_zips) + len(small_zips)
    batch_size = 5

    logging.info(f"Hybrid strategy: {len(large_zips)} large zips, {len(small_zips)} small zips")
    logging.info(f"Using {max_workers} processes, {intra_zip_workers} threads per large zip")

    if progress_callback:
        progress_callback(f"Starting hybrid extraction (large zips with {intra_zip_workers} threads each)...")

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            # Submit large zips with intra-zip parallelization
            for zip_info in large_zips:
                future = executor.submit(extract_zip_worker, str(zip_info['path']), intra_zip_workers)
                futures.append((future, zip_info['path'], 'large'))

            # Submit small zips with single-threaded extraction
            for zip_info in small_zips:
                future = executor.submit(extract_zip_worker, str(zip_info['path']), 1)
                futures.append((future, zip_info['path'], 'small'))

            for future, zip_path, zip_type in futures:
                if stop_event and stop_event.is_set():
                    logging.info("Operation cancelled by user")
                    break

                try:
                    success, extracted_path, error = future.result()
                    processed_count += 1

                    if success:
                        success_count += 1
                        logging.info(f"Successfully extracted {zip_type} zip: {extracted_path}")
                        if progress_tracker:
                            progress_tracker.mark_processed(Path(extracted_path))
                    else:
                        logging.error(f"Failed to extract {zip_type} zip {extracted_path}: {error}")

                    if progress_callback:
                        progress_callback(f"Processed {processed_count}/{total_files} zips ({success_count} successful)")

                    if progress_tracker and processed_count % batch_size == 0:
                        progress_tracker.batch_save_progress()

                except Exception as e:
                    processed_count += 1
                    logging.error(f"Error processing {zip_path}: {e}")

    except Exception as e:
        logging.error(f"Error in hybrid processing: {e}")
        # Fallback to sequential processing
        all_paths = [z['path'] for z in large_zips + small_zips]
        return _scan_directory_sequential(all_paths, progress_tracker, progress_callback, stop_event)

    if progress_tracker:
        progress_tracker.batch_save_progress()

    logging.info(f"Successfully processed {success_count}/{processed_count} zip files")
    return success_count, processed_count

def _scan_directory_parallel(zip_files, progress_tracker, progress_callback, stop_event, max_workers):
    """Legacy parallel processing function - kept for compatibility."""
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), len(zip_files), 8)

    success_count = 0
    processed_count = 0
    batch_size = 10

    logging.info(f"Using {max_workers} worker processes")

    if progress_callback:
        progress_callback(f"Starting parallel extraction with {max_workers} workers...")

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            zip_paths_str = [str(zf) for zf in zip_files]
            future_to_path = {executor.submit(extract_zip_worker, path): path for path in zip_paths_str}

            for future in as_completed(future_to_path):
                if stop_event and stop_event.is_set():
                    logging.info("Operation cancelled by user")
                    break

                path = future_to_path[future]
                try:
                    success, zip_path, error = future.result()
                    processed_count += 1

                    if success:
                        success_count += 1
                        logging.info(f"Successfully extracted: {zip_path}")
                        if progress_tracker:
                            progress_tracker.mark_processed(Path(zip_path))
                    else:
                        logging.error(f"Failed to extract {zip_path}: {error}")

                    if progress_callback:
                        progress_callback(f"Processed {processed_count}/{len(zip_files)} files ({success_count} successful)")

                    if progress_tracker and processed_count % batch_size == 0:
                        progress_tracker.batch_save_progress()

                except Exception as e:
                    processed_count += 1
                    logging.error(f"Error processing {path}: {e}")

    except Exception as e:
        logging.error(f"Error in parallel processing: {e}")
        return _scan_directory_sequential(zip_files, progress_tracker, progress_callback, stop_event)

    if progress_tracker:
        progress_tracker.batch_save_progress()

    logging.info(f"Successfully processed {success_count}/{processed_count} zip files")
    return success_count, processed_count

class ZipZapGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ZipZap - Zip File Extractor")
        self.root.geometry("600x450")
        
        self.progress_tracker = ProgressTracker()
        self.stop_event = threading.Event()
        self.current_thread = None
        
        self.setup_ui()
        setup_logging()
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        ttk.Label(main_frame, text="Directory to scan:").grid(row=0, column=0, sticky=tk.W, pady=5)
        
        path_frame = ttk.Frame(main_frame)
        path_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.directory_var = tk.StringVar()
        self.directory_entry = ttk.Entry(path_frame, textvariable=self.directory_var, width=50)
        self.directory_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        ttk.Button(path_frame, text="Browse", command=self.browse_directory).grid(row=0, column=1)
        
        path_frame.columnconfigure(0, weight=1)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, pady=10)
        
        self.start_button = ttk.Button(button_frame, text="Start Extraction", command=self.start_extraction)
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_extraction, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=5)
        
        self.clear_button = ttk.Button(button_frame, text="Clear Progress", command=self.clear_progress)
        self.clear_button.grid(row=0, column=2, padx=5)

        ttk.Label(main_frame, text="Max Workers:").grid(row=2, column=0, sticky=tk.W, pady=(10, 0))

        worker_frame = ttk.Frame(main_frame)
        worker_frame.grid(row=2, column=0, sticky=tk.E, pady=(10, 0))

        self.workers_var = tk.StringVar(value=str(min(multiprocessing.cpu_count(), 8)))
        worker_spinbox = ttk.Spinbox(worker_frame, from_=1, to=multiprocessing.cpu_count(),
                                   textvariable=self.workers_var, width=5)
        worker_spinbox.grid(row=0, column=0, padx=5)

        self.multiprocessing_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(worker_frame, text="Use Multiprocessing",
                       variable=self.multiprocessing_var).grid(row=0, column=1, padx=5)

        ttk.Label(worker_frame, text="Intra-zip threads:").grid(row=0, column=2, padx=5)
        self.intra_zip_var = tk.StringVar(value="4")
        intra_zip_spinbox = ttk.Spinbox(worker_frame, from_=1, to=8,
                                      textvariable=self.intra_zip_var, width=3)
        intra_zip_spinbox.grid(row=0, column=3, padx=5)
        
        ttk.Label(main_frame, text="Progress:").grid(row=4, column=0, sticky=tk.W, pady=(10, 5))
        
        self.progress_var = tk.StringVar(value="Ready to start...")
        ttk.Label(main_frame, textvariable=self.progress_var).grid(row=5, column=0, sticky=tk.W)

        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_bar.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(main_frame, text="Log:").grid(row=7, column=0, sticky=tk.W, pady=(10, 5))

        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=8, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.log_text = tk.Text(log_frame, height=12, width=70)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(8, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
    
    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.directory_var.set(directory)
    
    def start_extraction(self):
        directory = self.directory_var.get()
        if not directory:
            messagebox.showerror("Error", "Please select a directory")
            return
        
        if not Path(directory).exists():
            messagebox.showerror("Error", "Directory does not exist")
            return
        
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.stop_event.clear()
        
        self.log_text.delete(1.0, tk.END)
        self.progress_bar.start()
        
        self.current_thread = threading.Thread(
            target=self.run_extraction,
            args=(directory,),
            daemon=True
        )
        self.current_thread.start()
    
    def run_extraction(self, directory):
        try:
            use_multiprocessing = self.multiprocessing_var.get()
            max_workers = None
            intra_zip_workers = 4

            if use_multiprocessing:
                try:
                    max_workers = int(self.workers_var.get())
                except ValueError:
                    max_workers = min(multiprocessing.cpu_count(), 8)

                try:
                    intra_zip_workers = int(self.intra_zip_var.get())
                except ValueError:
                    intra_zip_workers = 4

            success_count, processed_count = scan_directory(
                directory,
                self.progress_tracker,
                self.update_progress,
                self.stop_event,
                use_multiprocessing,
                max_workers,
                intra_zip_workers
            )

            self.root.after(0, self.extraction_complete, success_count, processed_count)
        except Exception as e:
            self.root.after(0, self.extraction_error, str(e))
    
    def stop_extraction(self):
        self.stop_event.set()
        self.update_progress("Stopping...")
    
    def clear_progress(self):
        self.progress_tracker.clear_progress()
        messagebox.showinfo("Progress Cleared", "Progress tracking has been reset")
    
    def update_progress(self, message):
        self.root.after(0, self._update_progress_ui, message)
    
    def _update_progress_ui(self, message):
        self.progress_var.set(message)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
    
    def extraction_complete(self, success_count, processed_count):
        self.progress_bar.stop()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        message = f"Extraction complete! Successfully processed {success_count}/{processed_count} zip files"
        self.progress_var.set(message)
        messagebox.showinfo("Complete", message)
    
    def extraction_error(self, error_message):
        self.progress_bar.stop()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        self.progress_var.set("Error occurred")
        messagebox.showerror("Error", f"An error occurred: {error_message}")

def main():
    setup_logging()

    if len(sys.argv) > 1 and sys.argv[1] != '--gui':
        if len(sys.argv) not in [2, 4]:
            gui_option = " or python zipzap.py --gui" if GUI_AVAILABLE else ""
            print(f"Usage: python zipzap.py <directory> [--workers N] {gui_option}")
            sys.exit(1)

        directory = sys.argv[1]
        progress_tracker = ProgressTracker()

        max_workers = None
        if len(sys.argv) == 4 and sys.argv[2] == '--workers':
            try:
                max_workers = int(sys.argv[3])
            except ValueError:
                print("Invalid worker count. Using default.")

        success_count, processed_count = scan_directory(
            directory, progress_tracker, max_workers=max_workers, intra_zip_workers=4
        )
        print(f"Successfully processed {success_count}/{processed_count} zip files")
    else:
        if not GUI_AVAILABLE:
            print("GUI not available. tkinter is not installed.")
            print("Usage: python zipzap.py <directory> [--workers N]")
            sys.exit(1)

        root = tk.Tk()
        app = ZipZapGUI(root)
        root.mainloop()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()