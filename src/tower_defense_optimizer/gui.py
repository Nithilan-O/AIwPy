"""Optional Tk desktop adapter; all searches use the application service."""

from queue import Empty, Queue
import sys
from threading import Thread

try:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:
    tk = ttk = ScrolledText = None

from .application import run_searches
from .config import DEFAULT_SCENARIO
from .domain import TowerConfiguration
from .ui_model import ALGORITHM_LABELS, MEASURE_LABELS, grid_cells, parse_limits, result_view


_COLORS = {
    "other": "#f4f6f8", "buildable": "#d7eade", "path": "#c7cbd1",
    "spawn": "#b8dbf5", "base": "#ffe1a8", "arrow": "#92c5ff",
    "cannon": "#f4b4a6", "sniper": "#d6b8ef",
}


class OptimizerApp:
    """Tk events only validate inputs, dispatch work, and display presentation data."""

    def __init__(self, root):
        self.root = root
        self.scenario = DEFAULT_SCENARIO
        self.views = ()
        self.cells = grid_cells(TowerConfiguration(), self.scenario)
        self.messages = Queue()
        self.busy = False
        root.title("Intelligent Tower Defense Optimizer")
        root.geometry("1180x840")
        root.minsize(880, 680)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        shell = ttk.Frame(root, padding=12)
        shell.grid(sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(5, weight=1)

        ttk.Label(shell, text="Intelligent Tower Defense Optimizer",
                  font=("TkDefaultFont", 18, "bold")).grid(sticky="w")
        intro = ttk.Label(shell, justify="left", text=(
            "One fixed map • one wave of 20 identical enemies • no live gameplay. "
            "Choose placements that defeat the most enemies; break outcome ties with more base health. "
            "Spending is a build constraint, never a performance measure."))
        intro.grid(row=1, sticky="ew", pady=(6, 10))
        shell.bind("<Configure>", lambda event: intro.configure(wraplength=max(300, event.width - 30)))

        controls = ttk.LabelFrame(shell, text="Run a search", padding=8)
        controls.grid(row=2, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Algorithm").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.selection = tk.StringVar(value="Compare all three")
        self.algorithm = ttk.Combobox(controls, textvariable=self.selection,
                                      values=tuple(ALGORITHM_LABELS), state="readonly")
        self.algorithm.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.run_button = ttk.Button(controls, text="Run search", command=self.start)
        self.run_button.grid(row=0, column=2, sticky="e")
        settings = ttk.Frame(controls)
        settings.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.expanded = tk.StringVar(value="32")
        self.seconds = tk.StringVar(value="3")
        self.steps = tk.StringVar(value="5")
        self.entries = []
        for index, (label, variable) in enumerate((
            ("Explored-state limit", self.expanded), ("Time limit (s; blank = none)", self.seconds),
            ("Trace stages (0–20)", self.steps),
        )):
            settings.columnconfigure(index * 2 + 1, weight=1)
            ttk.Label(settings, text=label).grid(row=0, column=index * 2, padx=(0, 5))
            entry = ttk.Entry(settings, textvariable=variable, width=7)
            entry.grid(row=0, column=index * 2 + 1, sticky="ew", padx=(0, 12))
            self.entries.append(entry)
        self.status = tk.StringVar(value="Ready. Limits apply separately and equally to every selected algorithm.")
        ttk.Label(shell, textvariable=self.status).grid(row=3, sticky="w", pady=8)

        comparison = ttk.LabelFrame(shell, text="Comparison — select a row to inspect its recommendation", padding=6)
        comparison.grid(row=4, sticky="ew", pady=(0, 8))
        comparison.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(comparison, columns=("algorithm", *range(6)),
                                  show="headings", height=3, selectmode="browse")
        for key, label, width in [("algorithm", "Algorithm", 175)] + [
            (index, label, 125) for index, label in enumerate(MEASURE_LABELS)
        ]:
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=100, anchor="w" if key == "algorithm" else "e")
        self.table.grid(sticky="ew")
        scroll = ttk.Scrollbar(comparison, orient="horizontal", command=self.table.xview)
        scroll.grid(row=1, sticky="ew")
        self.table.configure(xscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>", self.select_result)

        panes = ttk.Panedwindow(shell, orient="horizontal")
        panes.grid(row=5, sticky="nsew")
        map_frame = ttk.LabelFrame(panes, text="Fixed map / selected recommendation", padding=8)
        map_frame.columnconfigure(0, weight=1)
        map_frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(map_frame, background="#ffffff", highlightthickness=0,
                                width=410, height=380)
        self.canvas.grid(sticky="nsew")
        self.canvas.bind("<Configure>", self.draw_grid)
        legend = ttk.Label(map_frame, justify="left", text=(
            "S spawn → # path → B base\n+ available build site • A Arrow • C Cannon • N Sniper\n"
            "Coordinates are (row, column), starting at 0."))
        legend.grid(row=1, sticky="ew", pady=(6, 0))
        map_frame.bind("<Configure>", lambda event: legend.configure(wraplength=max(200, event.width - 25)))
        panes.add(map_frame, weight=1)

        details = ttk.Frame(panes, padding=(10, 0, 0, 0))
        self.details = details
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        details.rowconfigure(3, weight=1)
        self.recommendation = tk.StringVar(value="No completed search yet. The grid shows the empty start.")
        recommendation = ttk.Label(details, textvariable=self.recommendation, justify="left")
        recommendation.grid(sticky="ew", pady=(0, 6))
        details.bind("<Configure>", lambda event: recommendation.configure(wraplength=max(200, event.width - 25)))
        self.explanation = ScrolledText(details, width=48, height=9, wrap="word", state="disabled")
        self.explanation.grid(row=1, sticky="nsew")
        self.trace_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(details, text="Show short teaching trace", variable=self.trace_visible,
                        command=self.toggle_trace).grid(row=2, sticky="w", pady=6)
        self.trace_box = ScrolledText(details, width=48, height=11, wrap="none",
                                     font="TkFixedFont", state="disabled")
        self.trace_box.grid(row=3, sticky="nsew")
        self.trace_scroll = ttk.Scrollbar(details, orient="horizontal", command=self.trace_box.xview)
        self.trace_scroll.grid(row=4, sticky="ew")
        self.trace_box.configure(xscrollcommand=self.trace_scroll.set)
        self.toggle_trace()
        panes.add(details, weight=1)
        note = ttk.Label(shell, justify="left", text=(
            "Execution time and memory vary by machine. Memory = peak traced Python allocations, not total process memory. "
            "Explored = unique states admitted for expansion; evaluated-only neighbors do not count. "
            "A limited result is best-so-far; hill climbing can stop at a local optimum."))
        note.grid(row=6, sticky="ew", pady=(8, 0))
        note.bind("<Configure>", lambda event: note.configure(wraplength=max(300, event.width)))

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def toggle_trace(self):
        self.details.rowconfigure(3, weight=1 if self.trace_visible.get() else 0)
        for widget in (self.trace_box, self.trace_scroll):
            if self.trace_visible.get():
                widget.grid()
            else:
                widget.grid_remove()

    def start(self):
        if self.busy:
            return
        try:
            limits = parse_limits(self.expanded.get(), self.seconds.get(), self.steps.get())
        except ValueError as error:
            self.status.set(str(error))
            return
        selection = ALGORITHM_LABELS[self.selection.get()]
        self.busy = True
        self.run_button.configure(state="disabled")
        self.algorithm.configure(state="disabled")
        for entry in self.entries:
            entry.configure(state="disabled")
        self.status.set("Running… same settings for every selection. Previous results remain visible until complete.")
        Thread(target=self._worker, args=(selection, limits), daemon=True).start()
        self.root.after(100, self.poll)

    def _worker(self, selection, limits):
        # Never access a Tk object from the worker. Measurement belongs to core.
        try:
            results = run_searches(selection, self.scenario, limits)
            self.messages.put((results, limits, None))
        except Exception as error:
            self.messages.put(((), limits, str(error)))

    def poll(self):
        try:
            results, limits, error = self.messages.get_nowait()
        except Empty:
            self.root.after(100, self.poll)
            return
        self.busy = False
        self.run_button.configure(state="normal")
        self.algorithm.configure(state="readonly")
        for entry in self.entries:
            entry.configure(state="normal")
        if error is not None:
            self.status.set(f"Search failed: {error}. Check limits and stop external memory tracing if active.")
            return
        self.views = tuple(result_view(result, self.scenario, limits) for result in results)
        for item in self.table.get_children():
            self.table.delete(item)
        for index, view in enumerate(self.views):
            self.table.insert("", "end", iid=str(index), values=(view.algorithm, *view.measures))
        if self.views:
            self.table.selection_set("0")
            self.select_result()
        self.status.set(f"Completed {len(results)} algorithm(s). Select a row; termination and limits are explained below.")

    def select_result(self, event=None):
        selected = self.table.selection()
        if not selected:
            return
        view = self.views[int(selected[0])]
        self.cells = view.grid
        self.recommendation.set(f"{view.algorithm}\n{view.configuration}\nTermination: {view.termination}")
        self._text(self.explanation, view.explanation)
        self._text(self.trace_box, view.trace)
        self.draw_grid()

    def draw_grid(self, event=None):
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        size = max(1, min((width - 40) / self.scenario.columns,
                          (height - 40) / self.scenario.rows))
        left = (width - size * self.scenario.columns) / 2
        top = (height - size * self.scenario.rows) / 2 + 8
        font = ("TkDefaultFont", max(8, min(15, int(size * 0.38))))
        for column in range(self.scenario.columns):
            self.canvas.create_text(left + (column + .5) * size, top - 12, text=str(column), font=font)
        for row in range(self.scenario.rows):
            self.canvas.create_text(left - 12, top + (row + .5) * size, text=str(row), font=font)
        for cell in self.cells:
            x, y = left + cell.column * size, top + cell.row * size
            self.canvas.create_rectangle(x, y, x + size, y + size,
                                         fill=_COLORS[cell.kind], outline="#ffffff", tags="cell")
            self.canvas.create_text(x + size / 2, y + size / 2, text=cell.symbol,
                                    font=font, fill="#172b3a")


def main() -> int:
    """Fail helpfully if Tk or a graphical display is unavailable; CLI is separate."""
    if tk is None:
        print("UI unavailable: install Python with Tk support (see README.md). "
              "The CLI still works: python -m tower_defense_optimizer --help", file=sys.stderr)
        return 2
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"UI unavailable: {error}. Use a desktop session with Tk support; "
              "the CLI still works: python -m tower_defense_optimizer --help", file=sys.stderr)
        return 2
    OptimizerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
