"""Small optional desktop UI for running the real Optiqo engine."""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from .demo import DemoResult, run_demo_workflow
from .exceptions import OptiqoAIMLError


class DemoWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Optiqo Engine Demo")
        self.root.geometry("1000x700")
        self.paths: dict[str, tk.StringVar] = {}
        self.tables: dict[str, pd.DataFrame] = {}
        self._build()

    def _build(self) -> None:
        form = ttk.Frame(self.root, padding=12)
        form.pack(fill=tk.X)
        labels = (
            ("Demand history CSV", "demand"),
            ("Inventory batches CSV", "inventory"),
            ("Permitted lanes CSV", "lanes"),
            ("Capacity CSV", "capacities"),
            ("Transport costs CSV", "costs"),
            ("Held-out actual demand CSV", "actuals"),
            ("SKU shelf-life requirements CSV", "shelf_life"),
        )
        for row, (label, key) in enumerate(labels):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 8), pady=3)
            path = tk.StringVar()
            self.paths[key] = path
            ttk.Entry(form, textvariable=path, width=90).grid(
                row=row, column=1, sticky=tk.EW, pady=3
            )
            ttk.Button(
                form,
                text="Browse…",
                command=lambda selected=path: self._browse(selected),
            ).grid(row=row, column=2, padx=(8, 0), pady=3)
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(self.root, padding=(12, 0))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Run engine workflow", command=self._run).pack(
            side=tk.LEFT
        )
        ttk.Button(actions, text="Save selected table as CSV", command=self._save).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Label(
            self.root,
            text=(
                "CSV provenance is user-supplied; this demo does not determine "
                "whether uploaded data is synthetic or real."
            ),
            padding=12,
        ).pack(anchor=tk.W)

        viewer = ttk.Frame(self.root, padding=12)
        viewer.pack(fill=tk.BOTH, expand=True)
        self.table_choice = tk.StringVar(value="Forecast")
        self.selector = ttk.Combobox(
            viewer,
            textvariable=self.table_choice,
            state="readonly",
            values=("Forecast", "Allocation", "Verification", "Explanations", "Benchmark"),
        )
        self.selector.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        self.selector.bind("<<ComboboxSelected>>", lambda _event: self._show_table())
        self.tree = ttk.Treeview(viewer, show="headings")
        y_scroll = ttk.Scrollbar(viewer, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(viewer, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=1, column=0, sticky=tk.NSEW)
        y_scroll.grid(row=1, column=1, sticky=tk.NS)
        x_scroll.grid(row=2, column=0, sticky=tk.EW)
        viewer.rowconfigure(1, weight=1)
        viewer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Choose the required CSV files, then run the workflow.")
        ttk.Label(self.root, textvariable=self.status, padding=12).pack(anchor=tk.W)

    def _browse(self, path: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Select CSV input",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if selected:
            path.set(selected)

    def _read_inputs(self) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
        missing = [key for key, value in self.paths.items() if not value.get().strip()]
        if missing:
            raise ValueError(f"Select a CSV file for each input: {', '.join(missing)}.")
        frames = {
            key: pd.read_csv(Path(value.get()))
            for key, value in self.paths.items()
        }
        requirements = frames.pop("shelf_life")
        required_columns = {"sku_id", "min_shelf_life_days"}
        if not required_columns.issubset(requirements.columns):
            raise ValueError(
                "Shelf-life CSV must contain sku_id and min_shelf_life_days columns."
            )
        if requirements["sku_id"].duplicated().any():
            raise ValueError("Shelf-life CSV must contain one row per sku_id.")
        minimums: dict[str, int] = {}
        for row in requirements.to_dict("records"):
            raw_sku = row["sku_id"]
            sku = "" if pd.isna(raw_sku) else str(raw_sku).strip()
            value = pd.to_numeric(row["min_shelf_life_days"], errors="coerce")
            if (
                not sku
                or pd.isna(value)
                or not math.isfinite(float(value))
                or float(value) != int(value)
                or int(value) < 0
            ):
                raise ValueError(
                    "Shelf-life requirements must have non-empty SKU IDs and non-negative whole days."
                )
            minimums[sku] = int(value)
        return frames, minimums

    def _run(self) -> None:
        self.status.set("Running forecast, allocation, verification, and benchmark…")
        self.root.update_idletasks()
        try:
            frames, minimums = self._read_inputs()
            result = run_demo_workflow(
                frames["demand"],
                frames["inventory"],
                frames["lanes"],
                minimums,
                frames["capacities"],
                frames["costs"],
                frames["actuals"],
            )
        except (OptiqoAIMLError, ValueError, TypeError, KeyError, OSError, pd.errors.ParserError) as exc:
            self.status.set("Workflow failed; see the error details.")
            messagebox.showerror("Optiqo workflow failed", str(exc))
            return
        self.tables = _result_tables(result)
        self._show_table()
        self.status.set(
            f"Model: {result.training.model_name}; solver: {result.allocation.status}; "
            f"independent checks valid: {result.verification.is_valid}."
        )

    def _show_table(self) -> None:
        frame = self.tables.get(self.table_choice.get())
        self.tree.delete(*self.tree.get_children())
        if frame is None:
            self.tree["columns"] = ()
            return
        columns = [str(column) for column in frame.columns]
        self.tree["columns"] = columns
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=140, stretch=True)
        for row in frame.itertuples(index=False, name=None):
            self.tree.insert(
                "",
                tk.END,
                values=tuple("" if pd.isna(value) else str(value) for value in row),
            )

    def _save(self) -> None:
        frame = self.tables.get(self.table_choice.get())
        if frame is None:
            messagebox.showinfo("No results", "Run the workflow before saving a table.")
            return
        target = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"),),
        )
        if target:
            frame.to_csv(target, index=False)
            self.status.set(f"Saved {self.table_choice.get()} to {target}.")


def _result_tables(result: DemoResult) -> dict[str, pd.DataFrame]:
    verification = pd.DataFrame(
        [
            {
                "is_valid": result.verification.is_valid,
                "checks_passed": result.verification.checks_passed,
                "checks_failed": result.verification.checks_failed,
                "checks_not_run": len(result.verification.checks_not_run),
                "violations": "; ".join(
                    str(item) for item in result.verification.violations
                ),
            }
        ]
    )
    return {
        "Forecast": result.forecast,
        "Allocation": result.allocation.plan,
        "Verification": verification,
        "Explanations": result.explanations,
        "Benchmark": result.benchmark.metrics,
    }


def launch() -> None:
    root = tk.Tk()
    DemoWindow(root)
    root.mainloop()
