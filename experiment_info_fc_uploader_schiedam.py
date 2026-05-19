import os
import clickhouse_connect
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Create a ClickHouse client using the stored connection details.
def connect():
    client = clickhouse_connect.get_client(
        host='xrm2j9axsy.germanywestcentral.azure.clickhouse.cloud',
        user='labingester',
        password='rTBKTJ2wx6++fQVUsK03usHto70=',
        secure=True
    )
    return client


def get_table_schema():
    """Retrieve column names from battolyser.experiment_info_fc"""
    try:
        client = connect()
        result = client.query("DESCRIBE TABLE battolyser.experiment_info_fc")
        columns = [row[0] for row in result.result_rows]
        return columns
    except Exception as e:
        messagebox.showerror("Schema Error", f"Could not retrieve table schema: {e}")
        return []


def get_existing_duplicates():
    """Get existing records to check for duplicates"""
    try:
        client = connect()
        rows = client.query(
            "SELECT experiment_id, sample_id, repetition FROM battolyser.experiment_info_fc"
        ).result_rows
        return {(int(row[0]), str(row[1]), int(row[2])) for row in rows}
    except Exception as e:
        messagebox.showwarning("ClickHouse Warning", f"Could not retrieve existing data: {e}")
        return set()


class ExperimentInfoUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Experiment Info ClickHouse Upload")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)

        self.excel_file = None
        self.excel_df = pd.DataFrame()
        self.valid_df = pd.DataFrame()
        self.duplicate_rows = []
        self.table_columns = []

        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill='both', expand=True)

        self.create_file_selection_frame()

    def clear_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def create_file_selection_frame(self):
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 1: Select Excel File", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(anchor='w', pady=(0, 10))

        browse_button = ttk.Button(button_frame, text="Browse Excel File", command=self.browse_file)
        browse_button.pack(side='left', padx=(0, 10))

        self.file_label = ttk.Label(self.main_frame, text="No file selected", foreground="gray")
        self.file_label.pack(anchor='w', pady=(0, 10))

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Excel file",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if file_path:
            self.excel_file = file_path
            self.file_label.config(text=f"Selected: {os.path.basename(file_path)}", foreground="black")
            self.load_and_validate()

    def load_and_validate(self):
        if not self.excel_file:
            messagebox.showwarning("No file", "Please select an Excel file first.")
            return

        try:
            self.excel_df = pd.read_excel(self.excel_file)
            self.table_columns = get_table_schema()

            if not self.table_columns:
                return

            # Check column headers
            excel_cols = set(self.excel_df.columns)
            table_cols = set(self.table_columns)

            missing_cols = table_cols - excel_cols
            extra_cols = excel_cols - table_cols

            # Check for missing columns
            if missing_cols:
                messagebox.showerror(
                    "Column Validation Error",
                    f"Missing required columns in Excel:\n{', '.join(sorted(missing_cols))}"
                )
                return

            # Separate valid rows from duplicates
            existing = get_existing_duplicates()
            valid_rows = []
            self.duplicate_rows = []

            for idx, row in self.excel_df.iterrows():
                try:
                    exp_id = int(row.get('experiment_id', 0))
                    sample_id = str(row.get('sample_id', ''))
                    repetition = int(row.get('repetition', 0))
                    if (exp_id, sample_id, repetition) in existing:
                        self.duplicate_rows.append(row)
                    else:
                        valid_rows.append(row)
                except (ValueError, TypeError):
                    valid_rows.append(row)

            self.valid_df = pd.DataFrame(valid_rows)
            self.duplicate_rows = pd.DataFrame(self.duplicate_rows)

            # Proceed to review
            self.show_review_frame()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load Excel file: {e}")

    def show_review_frame(self):
        self.clear_main_frame()
        ttk.Label(self.main_frame, text="Step 2: Review and Upload", font=(None, 14, 'bold')).pack(anchor='w', pady=(0, 10))

        # Valid rows table
        ttk.Label(self.main_frame, text=f"Rows to Upload ({len(self.valid_df)})", font=(None, 12, 'bold')).pack(anchor='w', pady=(10, 5))
        valid_frame = ttk.Frame(self.main_frame)
        valid_frame.pack(fill='both', expand=True, pady=(0, 10))

        if not self.valid_df.empty:
            columns = list(self.valid_df.columns)
            tree_valid = ttk.Treeview(valid_frame, columns=columns, show='headings', height=7)

            for col in columns:
                tree_valid.heading(col, text=col.replace('_', ' ').title())
                tree_valid.column(col, width=80, anchor='w')

            vsb_valid = ttk.Scrollbar(valid_frame, orient='vertical', command=tree_valid.yview)
            hsb_valid = ttk.Scrollbar(valid_frame, orient='horizontal', command=tree_valid.xview)
            tree_valid.configure(yscrollcommand=vsb_valid.set, xscrollcommand=hsb_valid.set)

            tree_valid.grid(row=0, column=0, sticky='nsew')
            vsb_valid.grid(row=0, column=1, sticky='ns')
            hsb_valid.grid(row=1, column=0, sticky='ew')
            valid_frame.grid_rowconfigure(0, weight=1)
            valid_frame.grid_columnconfigure(0, weight=1)

            for _, row in self.valid_df.iterrows():
                tree_valid.insert('', 'end', values=[row[col] for col in columns])
        else:
            ttk.Label(valid_frame, text="No valid rows to upload", foreground="gray").pack(pady=20)

        # Duplicate rows table
        ttk.Label(self.main_frame, text=f"Duplicates (Discarded) ({len(self.duplicate_rows)})", font=(None, 12, 'bold')).pack(anchor='w', pady=(10, 5))
        dup_frame = ttk.Frame(self.main_frame)
        dup_frame.pack(fill='both', expand=True, pady=(0, 10))

        if not self.duplicate_rows.empty:
            columns = list(self.duplicate_rows.columns)
            tree_dup = ttk.Treeview(dup_frame, columns=columns, show='headings', height=7)

            for col in columns:
                tree_dup.heading(col, text=col.replace('_', ' ').title())
                tree_dup.column(col, width=80, anchor='w')

            vsb_dup = ttk.Scrollbar(dup_frame, orient='vertical', command=tree_dup.yview)
            hsb_dup = ttk.Scrollbar(dup_frame, orient='horizontal', command=tree_dup.xview)
            tree_dup.configure(yscrollcommand=vsb_dup.set, xscrollcommand=hsb_dup.set)

            tree_dup.grid(row=0, column=0, sticky='nsew')
            vsb_dup.grid(row=0, column=1, sticky='ns')
            hsb_dup.grid(row=1, column=0, sticky='ew')
            dup_frame.grid_rowconfigure(0, weight=1)
            dup_frame.grid_columnconfigure(0, weight=1)

            for _, row in self.duplicate_rows.iterrows():
                tree_dup.insert('', 'end', values=[row[col] for col in columns])
        else:
            ttk.Label(dup_frame, text="No duplicates found", foreground="gray").pack(pady=20)

        button_frame = ttk.Frame(self.main_frame)
        button_frame.pack(fill='x', pady=(10, 0))

        back_button = ttk.Button(button_frame, text="Back", command=self.create_file_selection_frame)
        back_button.pack(side='left')

        upload_button = ttk.Button(button_frame, text="Upload Valid Rows", command=self.upload_data)
        upload_button.pack(side='right')

    def upload_data(self):
        if self.valid_df.empty:
            messagebox.showwarning("No data", "There are no valid rows to upload.")
            return

        should_upload = messagebox.askyesno("Confirm upload", f"Upload {len(self.valid_df)} valid rows to experiment_info_fc?")
        if not should_upload:
            return

        try:
            client = connect()
            client.insert_df('battolyser.experiment_info_fc', self.valid_df)
            messagebox.showinfo("Upload complete", f"Successfully uploaded {len(self.valid_df)} rows to experiment_info_fc.")
            self.excel_file = None
            self.excel_df = pd.DataFrame()
            self.valid_df = pd.DataFrame()
            self.duplicate_rows = []
            self.create_file_selection_frame()
        except Exception as e:
            messagebox.showerror("Upload failed", f"Upload failed: {e}")


def main():
    root = tk.Tk()
    app = ExperimentInfoUploaderApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
   