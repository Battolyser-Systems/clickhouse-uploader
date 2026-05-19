#%%
import os
import clickhouse_connect
import pandas as pd
import numpy as np
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import datetime

#%%
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


def read_arbin_fc_file(file_name, folder_path, exp_id, sub_exp_id, rep, sample_id):
    # Load a single Arbin CSV file and convert its contents into a DataFrame.
    file_path = os.path.join(folder_path, file_name)
    data = np.loadtxt(file_path, delimiter=',')

    # Only process known experiment types based on the filename.
    if 'Wb' in file_name:
        df = pd.DataFrame(index=range(len(data)))

        # Attach metadata to every row in the file.
        df["experiment_id"] = exp_id
        df["sub_experiment_id"] = sub_exp_id
        df["repetition"] = rep
        df["sample_id"] = sample_id
        df["file_name"] = file_name
        df["experiment"] = "EIS"
        return df

    # Warn and skip files that do not match expected experiment types.
    messagebox.showwarning("Unsupported file", f"File {file_name} does not contain EIS, CA, or CP data. Skipping.")
    return pd.DataFrame()

folder = r"C:\Users\CasHofman\Downloads\260413_5_Act_A2_C2_80C_1_2026_04_13_161532"

def read_arbin_fc_folder(folder):
    files_to_process = sorted([f for f in os.listdir(folder) if "Wb" in f])
    folder_df = pd.DataFrame()
    for file in files_to_process:
        file_path = os.path.join(folder, file)

        data_df = pd.read_csv(file_path)
        name_split = file.replace(".CSV","").split("_")
        data_df["experiment_id"] = int(name_split[1])
        data_df["sub_experiment_id"] = np.nan
        data_df["repetition"] = int(name_split[np.argwhere(np.array(name_split) == 'Channel')[0][0]-1])
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


def process_folders(folder_paths):
    # Read existing records from ClickHouse so we avoid duplicate uploads.
    try:
        client = connect()
        rows = client.query("""SELECT DISTINCT file_name, experiment_id, sample_id FROM battolyser.cycler_raw_fc""").result_rows
        existing_combos = {(row[0], int(row[1]), str(row[2])) for row in rows}
    except Exception as e:
        messagebox.showwarning("ClickHouse Warning", f"Could not connect to ClickHouse: {e}")
        existing_combos = set()

    all_folder_df = pd.DataFrame()
    for folder in folder_paths:
        folder_path = folder if os.path.isabs(folder) else os.path.join(os.getcwd(), folder)

        # Skip non-existing directories and warn the user.
        if not os.path.isdir(folder_path):
            messagebox.showerror("Folder error", f"Folder does not exist: {folder_path}")
            continue

        folder_df = read_arbin_fc_folder(folder_path)
        folder_df["folder_name"] = os.path.basename(folder_path) or folder_path
        all_folder_df = pd.concat([all_folder_df, folder_df], ignore_index=True)

    if all_folder_df.empty:
        return all_folder_df

    cleaned_df = clean_folder_df(all_folder_df)
    cleaned_df["file_name"] = cleaned_df["file_name"].astype(str)
    cleaned_df["sample_id"] = cleaned_df["sample_id"].astype(str)

    duplicate_entries = {
        (row["file_name"], int(row["experiment_id"]), str(row["sample_id"]))
        for _, row in cleaned_df[["file_name", "experiment_id", "sample_id"]].drop_duplicates().iterrows()
        if (row["file_name"], int(row["experiment_id"]), str(row["sample_id"])) in existing_combos
    }

    if duplicate_entries:
        details = "\n".join(
            f"file_name={file_name}, experiment_id={exp_id}, sample_id={sample_id}"
            for file_name, exp_id, sample_id in sorted(duplicate_entries)
        )
        messagebox.showwarning(
            "Duplicate entry",
            f"The following data already exists in cycler_raw_fc:\n{details}\nPlease select different folders or remove existing data."
        )
        return None

    return cleaned_df


class ClickHouseUploaderApp:
    # Main application class managing the Tkinter UI and upload workflow.
    def __init__(self, root):
        self.root = root
        self.root.title("ClickHouse Upload")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        self.folder_paths = []
        self.result_df = pd.DataFrame()
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

        self.result_df = process_folders(self.folder_paths)
        if self.result_df is None:
            return
        if self.result_df.empty:
            messagebox.showwarning("No data", "No data was found in the selected folders.")
            return

        self.summary_df = self.build_review_summary(self.result_df)
        self.show_review_frame()

    def build_review_summary(self, df):
        if df.empty:
            return pd.DataFrame(columns=[
                "folder_name",
                "experiment_id",
                "repetition",
                "sample_id",
                "anode",
                "cathode",
                "file_name",
                "experiment",
                "temperature"
            ])

        summary = (
            df.groupby(
                [
                    "folder_name",
                    "experiment_id",
                    "repetition",
                    "sample_id",
                    "anode",
                    "cathode",
                    "experiment",
                    "temperature"
                ], dropna=False, as_index=False
            )["file_name"]
            .agg(lambda names: "\n".join(sorted(pd.unique(names))))
        )
        return summary

    def show_review_frame(self):
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 2: Review and upload", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        summary_text = f"Processed {len(self.result_df)} rows from {len(self.folder_paths)} folder(s)."
        ttk.Label(self.main_frame, text=summary_text).pack(anchor='w', pady=(0, 10))

        table_frame = ttk.Frame(self.main_frame)
        table_frame.pack(fill='both', expand=True)

        columns = [
            "folder_name",
            "experiment_id",
            "repetition",
            "sample_id",
            "anode",
            "cathode",
            "file_name",
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
            messagebox.showinfo("Upload complete", "Data uploaded successfully.")
            self.folder_paths = []
            self.result_df = pd.DataFrame()
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


# %%
