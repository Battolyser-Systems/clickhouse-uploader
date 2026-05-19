import os
import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# Create a ClickHouse client using the stored connection details.
# This client is used for both querying existing rows and inserting new data.
def connect():
    client = clickhouse_connect.get_client(
        host='xrm2j9axsy.germanywestcentral.azure.clickhouse.cloud',
        user='labingester_eindhoven',
        password='G}Y%wQ^VNR%,0p20+v]pBx!-p',
        secure=True
    )
    return client


def read_ivium_file(file_name, folder_path, exp_id, sub_exp_id, rep, sample_id):
    # Load a single Ivium CSV file and convert its contents into a DataFrame.
    file_path = os.path.join(folder_path, file_name)
    data = np.loadtxt(file_path, delimiter=',')

    # Only process known experiment types based on the filename.
    if 'EIS' in file_name or 'CA' in file_name or 'CP' in file_name:
        df = pd.DataFrame(index=range(len(data)))

        if 'EIS' in file_name:
            # Electrochemical impedance spectroscopy data columns.
            df["experiment"] = "EIS"
            df["real_impedance"] = data[:, 0]
            df["complex_impedance"] = data[:, 1]
            df["frequency"] = data[:, 2]

        elif 'CA' in file_name:
            # Chronoamperometry data columns.
            df["experiment"] = "CA"
            df["step_time"] = data[:, 0]
            df["current"] = data[:, 1]
            df["voltage"] = data[:, 2]

        elif 'CP' in file_name:
            # Chronopotentiometry data columns.
            df["experiment"] = "CP"
            df["step_time"] = data[:, 0]
            df["voltage"] = data[:, 1]
            df["current"] = data[:, 2]

        # Attach metadata to every row in the file.
        df["experiment_id"] = exp_id
        df["sub_experiment_id"] = sub_exp_id
        df["repetition"] = rep
        df["sample_id"] = sample_id
        df["file_name"] = file_name
        df["step_index"] = int(file_name[0:4])
        df["timestamp"] = datetime.strptime(file_name.split("_")[1][0:6], "%y%m%d")
        return df

    # Warn and skip files that do not match expected experiment types.
    messagebox.showwarning("Unsupported file", f"File {file_name} does not contain EIS, CA, or CP data. Skipping.")
    return pd.DataFrame()


def process_folders(folder_data):
    # Read existing records from ClickHouse so we avoid duplicate uploads.
    try:
        client = connect()
        rows = client.query("""SELECT DISTINCT file_name, experiment_id, sub_experiment_id, sample_id FROM battolyser.ivium_raw""").result_rows
        existing_combos = {(row[0], int(row[1]), int(row[2]), str(row[3])) for row in rows}
    except Exception as e:
        messagebox.showwarning("ClickHouse Warning", f"Could not connect to ClickHouse: {e}")
        existing_combos = set()

    # Build an empty DataFrame with all expected columns for the combined upload.
    result_df = pd.DataFrame(columns=[
        "experiment_id",
        "sub_experiment_id",
        "repetition",
        "sample_id",
        "file_name",
        "experiment",
        "step_index",
        "timestamp",
        "real_impedance",
        "complex_impedance",
        "frequency",
        "step_time",
        "voltage",
        "current"
    ])

    for folder_info in folder_data:
        folder = folder_info['folder']
        exp_id = folder_info['experiment_id']
        sub_exp_id = folder_info['sub_experiment_id']
        rep = folder_info['repetition']
        sample_id = folder_info['sample_id']
        folder_path = folder if os.path.isabs(folder) else os.path.join(os.getcwd(), folder)

        # Skip non-existing directories and warn the user.
        if not os.path.isdir(folder_path):
            messagebox.showerror("Folder error", f"Folder does not exist: {folder_path}")
            continue

        # Load only CSV files from the selected folder.
        files = [f for f in os.listdir(folder_path) if f.endswith('.csv')]
        files_sorted = sorted(
            files,
            key=lambda x: (
                datetime.strptime(x.split("_")[1][0:6], "%y%m%d"),
                int(x[0:4]) + 1
            )
        )

        for file_name in files_sorted:
            combo = (file_name, exp_id, sub_exp_id, sample_id)
            if combo in existing_combos:
                # If the file metadata already exists, abort early to avoid duplicates.
                messagebox.showwarning(
                    "Duplicate entry",
                    f"The combination already exists in ivium_raw:\n"
                    f"file_name={file_name}\n"
                    f"experiment_id={exp_id}\n"
                    f"sub_experiment_id={sub_exp_id}\n"
                    f"sample_id={sample_id}\n"
                    f"Please select other folders or metadata."
                )
                return None

            df = read_ivium_file(file_name, folder_path, exp_id, sub_exp_id, rep, sample_id)
            result_df = pd.concat([result_df, df], ignore_index=True)

    return result_df


class ClickHouseUploaderApp:
    # Main application class managing the Tkinter UI and upload workflow.
    def __init__(self, root):
        self.root = root
        self.root.title("ClickHouse Upload")
        self.root.geometry("900x600")
        self.root.resizable(True, True)

        # Internal state tracking selected folders, metadata, and final result.
        self.folder_paths = []
        self.metadata_entries = []
        self.result_df = pd.DataFrame()
        self.folder_data = []

        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill='both', expand=True)

        # Start with the folder selection step.
        self.create_folder_selection_frame()

    def clear_main_frame(self):
        # Remove all widgets from the main frame before redrawing a new step.
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def create_folder_selection_frame(self):
        # Build the first screen where the user chooses input directories.
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 1: Select directories", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(anchor='w', pady=(0, 10))

        add_button = ttk.Button(button_frame, text="Add folder", command=self.add_folder)
        add_button.pack(side='left', padx=(0, 10))

        add_group_button = ttk.Button(button_frame, text="Add folders from parent", command=self.add_folders_from_parent)
        add_group_button.pack(side='left', padx=(0, 10))

        remove_button = ttk.Button(button_frame, text="Remove selected", command=self.remove_selected_folder)
        remove_button.pack(side='left')

        self.folder_listbox = tk.Listbox(self.main_frame, height=10, width=120, selectmode='single')
        self.folder_listbox.pack(fill='both', expand=True, pady=(0, 10))

        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill='x', pady=(10, 0))

        back_button = ttk.Button(control_frame, text="Reset", command=self.reset_folders)
        back_button.pack(side='left')

        continue_button = ttk.Button(control_frame, text="Continue", command=self.go_to_metadata)
        continue_button.pack(side='right')

    def add_folder(self):
        # Let the user choose one folder and add it to the list.
        folder = filedialog.askdirectory(title="Select folder")
        if folder and folder not in self.folder_paths:
            self.folder_paths.append(folder)
            self.folder_listbox.insert('end', folder)

    def add_folders_from_parent(self):
        # Let the user choose a parent directory and add selected subfolders.
        parent = filedialog.askdirectory(title="Select parent directory")
        if not parent:
            return

        subfolders = [
            os.path.join(parent, name)
            for name in sorted(os.listdir(parent))
            if os.path.isdir(os.path.join(parent, name))
        ]

        if not subfolders:
            messagebox.showinfo("No subfolders", "No subfolders found under the selected directory.")
            return

        popup = tk.Toplevel(self.root)
        popup.title("Select folders")
        popup.geometry("700x400")

        ttk.Label(popup, text="Select folders to add:", font=(None, 12, 'bold')).pack(anchor='w', padx=10, pady=(10, 5))

        listbox_frame = ttk.Frame(popup)
        listbox_frame.pack(fill='both', expand=True, padx=10, pady=5)

        folder_listbox = tk.Listbox(listbox_frame, selectmode='extended', width=100, height=15)
        folder_listbox.pack(side='left', fill='both', expand=True)

        list_scroll = ttk.Scrollbar(listbox_frame, orient='vertical', command=folder_listbox.yview)
        list_scroll.pack(side='right', fill='y')
        folder_listbox.config(yscrollcommand=list_scroll.set)

        for folder in subfolders:
            folder_listbox.insert('end', folder)

        control_frame = ttk.Frame(popup)
        control_frame.pack(fill='x', padx=10, pady=(0, 10))

        def add_selected():
            # Add only the selected folders from the chooser popup.
            selection = folder_listbox.curselection()
            for index in selection:
                folder = subfolders[index]
                if folder not in self.folder_paths:
                    self.folder_paths.append(folder)
                    self.folder_listbox.insert('end', folder)
            popup.destroy()

        ttk.Button(control_frame, text="Add selected folders", command=add_selected).pack(side='right')
        ttk.Button(control_frame, text="Cancel", command=popup.destroy).pack(side='right', padx=(0, 10))

    def remove_selected_folder(self):
        # Remove the currently highlighted folder from the selection.
        selection = self.folder_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.folder_listbox.delete(index)
        del self.folder_paths[index]

    def reset_folders(self):
        self.folder_paths = []
        self.folder_listbox.delete(0, 'end')

    def go_to_metadata(self):
        # Move to metadata entry only when one or more folders are selected.
        if len(self.folder_paths) == 0:
            messagebox.showwarning("No folders", "Please add at least one folder before continuing.")
            return
        self.create_metadata_frame()

    def create_metadata_frame(self):
        # Show a table where each selected folder gets experiment metadata.
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 2: Fill table data", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        container = ttk.Frame(self.main_frame)
        container.pack(fill='both', expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        hscrollbar = ttk.Scrollbar(container, orient='horizontal', command=canvas.xview)
        scrollable_frame = ttk.Frame(canvas)

        # Make the metadata table scrollable for many folders.
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=hscrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        hscrollbar.pack(side='bottom', fill='x')

        self.metadata_entries = []
        scrollable_frame.grid_columnconfigure(0, weight=4)
        scrollable_frame.grid_columnconfigure(1, weight=1)
        scrollable_frame.grid_columnconfigure(2, weight=1)
        scrollable_frame.grid_columnconfigure(3, weight=1)
        scrollable_frame.grid_columnconfigure(4, weight=1)

        headers = [
            ("Folder", 4),
            ("experiment_id", 1),
            ("sub_experiment_id", 1),
            ("repetition", 1),
            ("sample_id", 1)
        ]
        for col, (text, weight) in enumerate(headers):
            label = ttk.Label(scrollable_frame, text=text, anchor='w')
            label.grid(row=0, column=col, padx=2, pady=2, sticky='ew')
            scrollable_frame.grid_columnconfigure(col, weight=weight)

        for i, folder in enumerate(self.folder_paths):
            row_index = i + 1
            folder_entry = ttk.Entry(scrollable_frame)
            folder_entry.grid(row=row_index, column=0, padx=2, pady=2, sticky='ew')
            folder_entry.insert(0, os.path.basename(folder) or folder)
            folder_entry.state(['readonly'])

            exp_var = tk.StringVar(value='1')
            sub_exp_var = tk.StringVar(value='1')
            rep_var = tk.StringVar(value='1')
            sample_var = tk.StringVar(value='')

            exp_entry = ttk.Entry(scrollable_frame, textvariable=exp_var, width=14)
            sub_exp_entry = ttk.Entry(scrollable_frame, textvariable=sub_exp_var, width=16)
            rep_entry = ttk.Entry(scrollable_frame, textvariable=rep_var, width=12)
            sample_entry = ttk.Entry(scrollable_frame, textvariable=sample_var, width=24)

            exp_entry.grid(row=row_index, column=1, padx=2, pady=2, sticky='ew')
            sub_exp_entry.grid(row=row_index, column=2, padx=2, pady=2, sticky='ew')
            rep_entry.grid(row=row_index, column=3, padx=2, pady=2, sticky='ew')
            sample_entry.grid(row=row_index, column=4, padx=2, pady=2, sticky='ew')

            self.metadata_entries.append({
                'folder': folder,
                'experiment_id': exp_var,
                'sub_experiment_id': sub_exp_var,
                'repetition': rep_var,
                'sample_id': sample_var
            })

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(fill='x', pady=10)

        back_button = ttk.Button(button_frame, text="Back", command=self.create_folder_selection_frame)
        back_button.pack(side='left')

        process_button = ttk.Button(button_frame, text="Process Files", command=self.process_files)
        process_button.pack(side='right')

    def process_files(self):
        # Validate all metadata fields and convert them into typed folder data.
        folder_data = []
        for row in self.metadata_entries:
            folder = row['folder']
            try:
                exp_id = int(row['experiment_id'].get())
                sub_exp_id = int(row['sub_experiment_id'].get())
                rep = int(row['repetition'].get())
            except ValueError:
                messagebox.showerror("Validation error", "experiment_id, sub_experiment_id, and repetition must be integers.")
                return
            sample_id = row['sample_id'].get().strip()
            if sample_id == "":
                messagebox.showerror("Validation error", "sample_id cannot be empty.")
                return

            folder_data.append({
                'folder': folder,
                'experiment_id': exp_id,
                'sub_experiment_id': sub_exp_id,
                'repetition': rep,
                'sample_id': sample_id
            })

        # Ensure each metadata combination is unique to avoid processing the same sample twice.
        combos = {(item['experiment_id'], item['sub_experiment_id'], item['repetition'], item['sample_id']) for item in folder_data}
        if len(combos) < len(folder_data):
            messagebox.showerror("Validation error", "There are overlapping entries in experiment_id, sub_experiment_id, repetition, and sample_id. Please ensure all combinations are unique.")
            return

        self.folder_data = folder_data
        result = process_folders(folder_data)
        if result is None:
            # If processing aborted due to duplicates or an error, return to the first step.
            self.create_folder_selection_frame()
            return
        self.result_df = result
        self.show_review_frame()

    def show_review_frame(self):
        # Display a preview of the processed rows and allow the user to upload them.
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 3: Review and upload", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        summary_text = f"Processed {len(self.result_df)} rows from {len(self.folder_data)} folder(s)."
        ttk.Label(self.main_frame, text=summary_text).pack(anchor='w', pady=(0, 10))

        preview = self.result_df.head(20).to_string(index=False)
        text_widget = tk.Text(self.main_frame, height=16, wrap='none')
        text_widget.insert('1.0', preview)
        text_widget.configure(state='disabled')
        text_widget.pack(fill='both', expand=True, pady=(0, 10))

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(fill='x')

        back_button = ttk.Button(button_frame, text="Back", command=self.create_metadata_frame)
        back_button.pack(side='left')

        upload_button = ttk.Button(button_frame, text="Upload to ClickHouse", command=self.upload_data)
        upload_button.pack(side='right')

    def upload_data(self):
        # Upload the processed DataFrame to ClickHouse after confirmation.
        if self.result_df.empty:
            messagebox.showwarning("No data", "There is no data to upload.")
            return

        should_upload = messagebox.askyesno("Confirm upload", "Upload the processed data to ClickHouse?")
        if not should_upload:
            return

        try:
            client = connect()
            client.insert_df('battolyser.ivium_raw', self.result_df)
            messagebox.showinfo("Upload complete", "Data uploaded successfully.")
            self.create_folder_selection_frame()
            self.folder_paths = []
            self.metadata_entries = []
            self.result_df = pd.DataFrame()
            self.folder_data = []
        except Exception as e:
            messagebox.showerror("Upload failed", f"Upload failed: {e}")


def main():
    # Launch the Tkinter application.
    root = tk.Tk()
    app = ClickHouseUploaderApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()

