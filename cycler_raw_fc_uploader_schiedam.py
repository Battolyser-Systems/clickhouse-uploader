#!/usr/bin/env python3
import os
import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import datetime


# Create a ClickHouse client using the stored connection details.
# This client is used for both querying existing rows and inserting new data.
def connect():
    client = clickhouse_connect.get_client(
        host='xrm2j9axsy.germanywestcentral.azure.clickhouse.cloud',
        user='labingester',
        password='rTBKTJ2wx6++fQVUsK03usHto70=',
        secure=True
    )
    return client

def read_arbin_fc_folder(folder):
    files_to_process = sorted([f for f in os.listdir(folder) if "Wb" in f])
    folder_df = pd.DataFrame()
    for file in files_to_process:
        file_path = os.path.join(folder, file)

        data_df = pd.read_csv(file_path)
        name_split = file.replace(".CSV","").split("_")
        data_df["experiment_id"] = int(name_split[1])
        data_df["sub_experiment_id"] = np.nan
        data_df["repetition"] = int(name_split[6])
        data_df["sample_id"] = name_split[3] + "_" + name_split[4]
        data_df["anode"] = name_split[3]
        data_df["cathode"] = name_split[4]
        data_df["file_name"] = file
        data_df["experiment"] = name_split[2]
        data_df["temperature"] = name_split[5]
        folder_df = pd.concat([folder_df, data_df], ignore_index=True)
    return folder_df

def clean_folder_df(folder_df):
    folder_df.rename(columns={
        "Data Point": "data_point_num",
        "Date Time" : "timestamp",
        "Test Time (s)" : "test_time",
        "Step Time (s)" : "step_time",
        "Cycle Index": "cycle_index",
        "Step Index": "step_index",
        "Current (A)": "current",
        "Voltage (V)": "voltage",
        "Charge Capacity (Ah)": "charge_capacity",
        "Discharge Capacity (Ah)": "discharge_capacity",
        "Aux_Voltage_1 (V)": "aux_voltage_1",
        "Aux_Voltage_2 (V)": "aux_voltage_2",
        "Aux_Voltage_3 (V)": "aux_voltage_3",
        "Aux_Voltage_4 (V)": "aux_voltage_4",
        "Aux_Temperature_1 (C)": "aux_temperature_1",
        "Aux_Temperature_2 (C)": "aux_temperature_2"
    }, inplace=True)

    folder_df.drop(columns=['Power (W)', 'Charge Energy (Wh)', 
                            'Discharge Energy (Wh)','Capacity (Ah)', 
                            'mAh/g', 'ACR (Ohm)', 'dV/dt (V/s)',
                            'Internal Resistance (Ohm)', 'dQ/dV (Ah/V)', 
                            'dV/dQ (V/Ah)', 'Aux_dV/dt_1 (V/s)', 
                            'Aux_dV/dt_2 (V/s)', 'Aux_dV/dt_3 (V/s)',
                            'Aux_dV/dt_4 (V/s)', 'Aux_dT/dt_1 (C/s)', 
                            'Aux_dT/dt_2 (C/s)'], inplace=True)

    folder_df['timestamp'] = folder_df['timestamp'].str.replace('\t', '')
    folder_df['timestamp'] = [datetime.datetime.strptime(element, '%m/%d/%Y %H:%M:%S.%f') for element in folder_df['timestamp']]
    return folder_df


def get_eis_directory(folder_path):
    parent2 = os.path.dirname(os.path.dirname(folder_path))
    return os.path.join(parent2, 'ACIM_EIS_data')


def read_eis_for_folder(folder_path, folder_df):
    folder_name = os.path.basename(folder_path)
    eis_match = '_'.join(folder_name.split('_')[0:7])
    eis_dir = get_eis_directory(folder_path)

    if not os.path.isdir(eis_dir):
        return None, f"EIS directory not found: {eis_dir}"

    eis_candidates = sorted(
        f for f in os.listdir(eis_dir)
        if f.startswith(eis_match + '_') and f.lower().endswith('.csv')
    )

    if not eis_candidates:
        return None, f"No matching EIS file found in {eis_dir} for prefix {eis_match}_"

    eis_file = eis_candidates[0]
    eis_file_path = os.path.join(eis_dir, eis_file)
    eis_df = pd.read_csv(eis_file_path, index_col=False)

    if eis_df.empty:
        return None, f"Matched EIS file is empty: {eis_file_path}"

    metadata = folder_df.iloc[0]
    eis_df['folder_name'] = os.path.basename(folder_path) or folder_path
    eis_df['experiment_id'] = metadata.get('experiment_id', np.nan)
    eis_df['sub_experiment_id'] = metadata.get('sub_experiment_id', np.nan)
    eis_df['repetition'] = metadata.get('repetition', np.nan)
    eis_df['sample_id'] = metadata.get('sample_id', np.nan)
    eis_df['anode'] = metadata.get('anode', np.nan)
    eis_df['cathode'] = metadata.get('cathode', np.nan)
    eis_df['experiment'] = metadata.get('experiment', np.nan)
    eis_df['temperature'] = metadata.get('temperature', np.nan)
    eis_df['file_name'] = eis_file

    eis_df.rename(columns={
        'Cycle_ID': 'cycle_index',
        'step_ID': 'step_index',
        'Frequency': 'frequency',
        'OCV': 'voltage',
        'Zreal': 'real_impedance',
        'Zimg': 'complex_impedance',
        'Zphz': 'phase',
        'Zmod': 'modulus',
        'AC_Amp_RMS': 'ac_amplitude_rms'
    }, inplace=True)

    for column in ['Channel_ID', 'EIS_Test_ID', 'EIS_Data_Point', 'Test_Time']:
        if column in eis_df.columns:
            eis_df.drop(columns=[column], inplace=True)

    return eis_df, None


def process_folders(folder_paths):
    # Read existing records from ClickHouse so we can validate experiment membership and avoid duplicate file uploads.
    experiment_info_keys = set()
    existing_file_names = set()
    existing_eis_file_names = set()
    try:
        client = connect()
        rows = client.query("""SELECT DISTINCT experiment_id, sample_id, repetition FROM battolyser.experiment_info_fc""").result_rows
        experiment_info_keys = {(int(row[0]), str(row[1]), int(row[2])) for row in rows}

        rows = client.query("""SELECT DISTINCT file_name FROM battolyser.cycler_raw_fc""").result_rows
        existing_file_names = {str(row[0]) for row in rows}

        rows = client.query("""SELECT DISTINCT file_name FROM battolyser.eis_raw_fc""").result_rows
        existing_eis_file_names = {str(row[0]) for row in rows}
    except Exception as e:
        messagebox.showwarning("ClickHouse Warning", f"Could not connect to ClickHouse: {e}")

    all_folder_df = pd.DataFrame()
    all_eis_df = pd.DataFrame()
    for folder in folder_paths:
        folder_path = folder if os.path.isabs(folder) else os.path.join(os.getcwd(), folder)

        # Skip non-existing directories and warn the user.
        if not os.path.isdir(folder_path):
            messagebox.showerror("Folder error", f"Folder does not exist: {folder_path}")
            continue

        folder_df = read_arbin_fc_folder(folder_path)
        if folder_df.empty:
            messagebox.showwarning("Folder error", f"No data files found in {folder_path}")
            continue

        folder_df["folder_name"] = os.path.basename(folder_path) or folder_path
        all_folder_df = pd.concat([all_folder_df, folder_df], ignore_index=True)

        eis_df, error = read_eis_for_folder(folder_path, folder_df)
        if error:
            messagebox.showwarning("Missing EIS data", error)
            return None
        all_eis_df = pd.concat([all_eis_df, eis_df], ignore_index=True)

    if all_folder_df.empty:
        return all_folder_df, all_eis_df

    cleaned_df = clean_folder_df(all_folder_df)
    cleaned_df["file_name"] = cleaned_df["file_name"].astype(str)
    cleaned_df["sample_id"] = cleaned_df["sample_id"].astype(str)
    cleaned_df["repetition"] = cleaned_df["repetition"].astype(int)

    if not all_eis_df.empty:
        all_eis_df["file_name"] = all_eis_df["file_name"].astype(str)
        all_eis_df["sample_id"] = all_eis_df["sample_id"].astype(str)
        all_eis_df["repetition"] = all_eis_df["repetition"].astype(int)

    missing_experiment_info = {
        (int(row["experiment_id"]), str(row["sample_id"]), int(row["repetition"]))
        for _, row in cleaned_df[["experiment_id", "sample_id", "repetition"]].drop_duplicates().iterrows()
        if (int(row["experiment_id"]), str(row["sample_id"]), int(row["repetition"])) not in experiment_info_keys
    }

    duplicate_file_names = {
        row["file_name"]
        for _, row in cleaned_df[["file_name"]].drop_duplicates().iterrows()
        if row["file_name"] in existing_file_names
    }

    duplicate_eis_file_names = {
        row["file_name"]
        for _, row in all_eis_df[["file_name"]].drop_duplicates().iterrows()
        if row["file_name"] in existing_eis_file_names
    }

    if missing_experiment_info:
        details = "\n".join(
            f"experiment_id={exp_id}, sample_id={sample_id}, repetition={repetition}"
            for exp_id, sample_id, repetition in sorted(missing_experiment_info)
        )
        messagebox.showwarning(
            "Missing experiment info",
            f"The following experiment info entries were not found in battolyser.experiment_info_fc:\n{details}\nPlease verify the source data."
        )
        return None

    if duplicate_file_names:
        details = "\n".join(sorted(duplicate_file_names))
        messagebox.showwarning(
            "Duplicate file name",
            f"The following file_name entries already exist in cycler_raw_fc:\n{details}\nPlease select different folders or remove existing data."
        )
        return None

    if duplicate_eis_file_names:
        details = "\n".join(sorted(duplicate_eis_file_names))
        messagebox.showwarning(
            "Duplicate EIS file name",
            f"The following file_name entries already exist in eis_raw_fc:\n{details}\nPlease select different folders or remove existing data."
        )
        return None

    return cleaned_df, all_eis_df


class ClickHouseUploaderApp:
    # Main application class managing the Tkinter UI and upload workflow.
    def __init__(self, root):
        self.root = root
        self.root.title("ClickHouse Upload")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        self.folder_paths = []
        self.result_df = pd.DataFrame()
        self.eis_result_df = pd.DataFrame()
        self.summary_df = pd.DataFrame()

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

        self.folder_listbox = tk.Listbox(self.main_frame, height=10, width=120, selectmode='multiple')
        self.folder_listbox.pack(fill='both', expand=True, pady=(0, 10))

        control_frame = ttk.Frame(self.main_frame)
        control_frame.pack(fill='x', pady=(10, 0))

        reset_button = ttk.Button(control_frame, text="Reset", command=self.reset_folders)
        reset_button.pack(side='left')

        process_button = ttk.Button(control_frame, text="Process folders", command=self.process_files)
        process_button.pack(side='right')

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
        for index in reversed(selection):
            self.folder_listbox.delete(index)
            del self.folder_paths[index]

    def reset_folders(self):
        self.folder_paths = []
        self.folder_listbox.delete(0, 'end')

    def process_files(self):
        if not self.folder_paths:
            messagebox.showwarning("No folders", "Please add at least one folder before processing.")
            return

        result = process_folders(self.folder_paths)
        if result is None:
            return

        self.result_df, self.eis_result_df = result
        if self.result_df.empty:
            messagebox.showwarning("No data", "No data was found in the selected folders.")
            return

        self.summary_df = self.build_review_summary(self.result_df)
        self.show_review_frame()

    def build_review_summary(self, df):
        if df.empty:
            return pd.DataFrame(columns=[
                "folder_name",
                "cycler_file_name",
                "eis_file_name",
                "experiment_id",
                "repetition",
                "sample_id",
                "experiment",
                "temperature"
            ])

        eis_by_folder = (
            self.eis_result_df
            .drop_duplicates(subset=["folder_name", "file_name"])
            .groupby("folder_name", dropna=False)["file_name"]
            .agg(lambda names: sorted(pd.unique(names)))
            .to_dict()
        )

        summary_rows = []
        group_keys = [
            "folder_name",
            "experiment_id",
            "repetition",
            "sample_id",
            "experiment",
            "temperature"
        ]

        grouped = df.groupby(group_keys, dropna=False)
        for group_values, group_df in grouped:
            folder_name = group_values[0]
            cycler_files = sorted(pd.unique(group_df["file_name"]))
            eis_files = eis_by_folder.get(folder_name, [])
            eis_file_name = eis_files[0] if eis_files else ""

            for index, cycler_file in enumerate(cycler_files):
                row = {
                    "folder_name": folder_name,
                    "cycler_file_name": cycler_file,
                    "eis_file_name": eis_file_name,
                    "experiment_id": group_values[1] if index == 0 else "",
                    "repetition": group_values[2] if index == 0 else "",
                    "sample_id": group_values[3] if index == 0 else "",
                    "experiment": group_values[4] if index == 0 else "",
                    "temperature": group_values[5] if index == 0 else ""
                }
                summary_rows.append(row)

        return pd.DataFrame(summary_rows, columns=[
            "folder_name",
            "cycler_file_name",
            "eis_file_name",
            "experiment_id",
            "repetition",
            "sample_id",
            "experiment",
            "temperature"
        ])

    def show_review_frame(self):
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 2: Review and upload", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        summary_text = f"Processed {len(self.result_df)} cycler rows from {len(self.folder_paths)} folder(s)."
        ttk.Label(self.main_frame, text=summary_text).pack(anchor='w', pady=(0, 10))

        table_frame = ttk.Frame(self.main_frame)
        table_frame.pack(fill='both', expand=True)

        columns = [
            "folder_name",
            "cycler_file_name",
            "eis_file_name",
            "experiment_id",
            "repetition",
            "sample_id",
            "experiment",
            "temperature"
        ]

        tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=14)
        for col in columns:
            tree.heading(col, text=col.replace('_', ' ').title())
            tree.column(col, width=120, anchor='w')

        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        for _, row in self.summary_df.iterrows():
            tree.insert('', 'end', values=[row[col] for col in columns])

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(fill='x', pady=(10, 0))

        back_button = ttk.Button(button_frame, text="Back", command=self.create_folder_selection_frame)
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
            upload_df = self.result_df.drop(columns=['folder_name'], errors='ignore')
            client.insert_df('battolyser.cycler_raw_fc', upload_df)

            if not self.eis_result_df.empty:
                upload_eis_df = self.eis_result_df.drop(columns=['folder_name'], errors='ignore')
                client.insert_df('battolyser.eis_raw_fc', upload_eis_df)

            messagebox.showinfo("Upload complete", "Data uploaded successfully.")
            self.folder_paths = []
            self.result_df = pd.DataFrame()
            self.eis_result_df = pd.DataFrame()
            self.summary_df = pd.DataFrame()
            self.create_folder_selection_frame()
        except Exception as e:
            messagebox.showerror("Upload failed", f"Upload failed: {e}")


def main():
    # Launch the Tkinter application.
    root = tk.Tk()
    app = ClickHouseUploaderApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()


